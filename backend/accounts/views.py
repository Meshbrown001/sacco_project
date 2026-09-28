import logging

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import OTPCode
from .otp import (
    OTPCooldownError,
    OTPDeliveryError,
    OTPError,
    available_channels,
    issue_otp,
    mask_phone,
    verify_otp,
)
from .serializers import (
    CustomTokenObtainPairSerializer,
    MemberRegistrationSerializer,
    OTPCodeSerializer,
    PasswordResetCompleteSerializer,
    PasswordResetSendSerializer,
    PasswordResetStartSerializer,
    PasswordResetVerifySerializer,
    UserSerializer,
)
from .sms import SMSError

logger = logging.getLogger(__name__)
User = get_user_model()


class MemberRegisterView(generics.CreateAPIView):
    """
    Public endpoint - anyone can register as a member.
    POST /api/accounts/register/
    Creates the member, sends a phone verification code, and returns
    tokens so the frontend can go straight to the verification page.
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = MemberRegistrationSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        otp_sent = True
        try:
            issue_otp(user, OTPCode.Purpose.PHONE_VERIFICATION)
        except (OTPError, SMSError):
            logger.exception("Could not send verification code to user %s", user.pk)
            otp_sent = False

        refresh = CustomTokenObtainPairSerializer.get_token(user)
        return Response(
            {
                "user": serializer.data,
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "otp_sent": otp_sent,
                "phone_hint": mask_phone(user.phone_number),
            },
            status=status.HTTP_201_CREATED,
        )


class CustomLoginView(TokenObtainPairView):
    """
    Shared login endpoint for members AND staff.
    POST /api/accounts/login/
    Returns access + refresh tokens, plus role, username and phone_verified.
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = CustomTokenObtainPairSerializer


class MyProfileView(APIView):
    """
    Returns the logged-in user's own profile info.
    GET /api/accounts/me/
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)


class LogoutView(APIView):
    """
    Logs the user out by blacklisting their refresh token.
    POST /api/accounts/logout/
    Body: {"refresh": "<refresh token>"}
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response(
                {"detail": "Refresh token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            token = RefreshToken(refresh_token)
        except TokenError:
            return Response(
                {"detail": "Invalid or expired refresh token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if str(token.get("user_id")) != str(request.user.pk):
            return Response(
                {"detail": "Token does not belong to this user."},
                status=status.HTTP_403_FORBIDDEN,
            )

        token.blacklist()
        return Response({"detail": "Logged out successfully."}, status=status.HTTP_200_OK)


class ResendPhoneOTPView(APIView):
    """
    Sends a new phone verification code.
    POST /api/accounts/verify-phone/resend/
    """
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "otp_send"

    def post(self, request):
        user = request.user
        if user.phone_verified:
            return Response(
                {"detail": "Your phone number is already verified."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            issue_otp(user, OTPCode.Purpose.PHONE_VERIFICATION)
        except OTPCooldownError as exc:
            return Response(
                {"detail": str(exc), "retry_after": exc.seconds_remaining},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        except (OTPDeliveryError, SMSError):
            logger.exception("SMS failed for user %s", user.pk)
            return Response(
                {"detail": "We could not send the code. Try again shortly."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {"detail": f"A new code has been sent to {mask_phone(user.phone_number)}."},
            status=status.HTTP_200_OK,
        )


class VerifyPhoneView(APIView):
    """
    Confirms the phone number with the SMS code.
    POST /api/accounts/verify-phone/
    """
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "otp_verify"

    def post(self, request):
        user = request.user
        if user.phone_verified:
            return Response(
                {"detail": "Your phone number is already verified."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = OTPCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            verify_otp(user, OTPCode.Purpose.PHONE_VERIFICATION, serializer.validated_data["code"])
        except OTPError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        user.phone_verified = True
        user.save(update_fields=["phone_verified"])
        return Response(
            {"detail": "Phone number verified.", "phone_verified": True},
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Forgot password
#   1. start    - username in, the account's hidden contacts out
#   2. send     - a code goes to the chosen registered contact
#   3. verify   - a correct code returns a short-lived reset token
#   4. complete - the reset token and new password set the password
# ---------------------------------------------------------------------------

NO_ACCOUNT = "No active account uses that username."


def get_reset_user(username):
    return User.objects.filter(username__iexact=username.strip(), is_active=True).first()


class PasswordResetStartView(APIView):
    """
    POST /api/accounts/password-reset/start/
    Body: {"username": "bnjeri"}
    """
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"

    def post(self, request):
        serializer = PasswordResetStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = get_reset_user(serializer.validated_data["username"])
        if user is None:
            return Response({"detail": NO_ACCOUNT}, status=status.HTTP_404_NOT_FOUND)

        channels = available_channels(user)
        if not channels:
            return Response(
                {"detail": "This account has no phone number or email on record. Please contact the SACCO office."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({"username": user.username, "channels": channels})


class PasswordResetSendView(APIView):
    """
    POST /api/accounts/password-reset/send/
    Body: {"username": "bnjeri", "channel": "sms" or "email"}
    The code goes only to the contact registered on the account.
    """
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"

    def post(self, request):
        serializer = PasswordResetSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = get_reset_user(serializer.validated_data["username"])
        if user is None:
            return Response({"detail": NO_ACCOUNT}, status=status.HTTP_404_NOT_FOUND)

        channel = serializer.validated_data["channel"]
        if channel not in [c["channel"] for c in available_channels(user)]:
            return Response(
                {"detail": "That delivery method is not registered on this account."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            otp = issue_otp(user, OTPCode.Purpose.PASSWORD_RESET, channel)
        except OTPCooldownError as exc:
            return Response(
                {"detail": str(exc), "retry_after": exc.seconds_remaining},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        except OTPError as exc:
            logger.warning("Password reset code not sent for user %s: %s", user.pk, exc)
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response({
            "channel": channel,
            "sent_to": otp.sent_to,
            "expires_at": otp.expires_at.isoformat(),
            "expires_in": int((otp.expires_at - otp.created_at).total_seconds()),
        })


class PasswordResetVerifyView(APIView):
    """
    POST /api/accounts/password-reset/verify/
    Body: {"username": "bnjeri", "code": "123456"}
    """
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "otp_verify"

    def post(self, request):
        serializer = PasswordResetVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = get_reset_user(serializer.validated_data["username"])
        if user is None:
            return Response({"detail": NO_ACCOUNT}, status=status.HTTP_404_NOT_FOUND)

        try:
            verify_otp(user, OTPCode.Purpose.PASSWORD_RESET, serializer.validated_data["code"])
        except OTPError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        # Valid for PASSWORD_RESET_TIMEOUT, and useless once the password changes.
        return Response({"reset_token": default_token_generator.make_token(user)})


class PasswordResetCompleteView(APIView):
    """
    POST /api/accounts/password-reset/complete/
    Body: {"username", "reset_token", "new_password", "new_password2"}
    Sets the password and logs the account out everywhere.
    """
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"

    def post(self, request):
        serializer = PasswordResetCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = get_reset_user(data["username"])
        if user is None or not default_token_generator.check_token(user, data["reset_token"]):
            return Response(
                {"detail": "This reset session has expired. Please start again."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            validate_password(data["new_password"], user=user)
        except DjangoValidationError as exc:
            return Response({"new_password": list(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(data["new_password"])
        user.save(update_fields=["password"])

        # Log out every existing session, since someone else may know the old password.
        for token in OutstandingToken.objects.filter(user=user):
            BlacklistedToken.objects.get_or_create(token=token)
        OTPCode.objects.filter(
            user=user, purpose=OTPCode.Purpose.PASSWORD_RESET, is_used=False,
        ).update(is_used=True)

        logger.info("Password reset completed for user %s", user.pk)
        return Response({"detail": "Your password has been changed. You can now log in."})