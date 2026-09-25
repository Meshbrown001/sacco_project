import logging

from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import OTPCode
from .otp import OTPCooldownError, OTPError, issue_otp, mask_phone, verify_otp
from .serializers import (
    CustomTokenObtainPairSerializer,
    MemberRegistrationSerializer,
    OTPCodeSerializer,
    UserSerializer,
)
from .sms import SMSError

logger = logging.getLogger(__name__)


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
    Requires a valid access token.
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
    Requires a valid access token.
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

        # Stop one user from logging out another user's session.
        if str(token.get("user_id")) != str(request.user.pk):
            return Response(
                {"detail": "Token does not belong to this user."},
                status=status.HTTP_403_FORBIDDEN,
            )

        token.blacklist()
        return Response(
            {"detail": "Logged out successfully."},
            status=status.HTTP_200_OK,
        )


class ResendPhoneOTPView(APIView):
    """
    Sends a new phone verification code.
    POST /api/accounts/verify-phone/resend/
    Requires a valid access token.
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
        except SMSError:
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
    Body: {"code": "123456"}
    Requires a valid access token.
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
            verify_otp(
                user,
                OTPCode.Purpose.PHONE_VERIFICATION,
                serializer.validated_data["code"],
            )
        except OTPError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        user.phone_verified = True
        user.save(update_fields=["phone_verified"])
        return Response(
            {"detail": "Phone number verified.", "phone_verified": True},
            status=status.HTTP_200_OK,
        )