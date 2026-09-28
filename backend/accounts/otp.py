import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from .models import OTPCode
from .sms import SMSError, send_sms

OTP_LENGTH = 6
OTP_EXPIRY = timedelta(minutes=5)
MAX_ATTEMPTS = 5
RESEND_COOLDOWN = timedelta(seconds=60)

CHANNEL_SMS = "sms"
CHANNEL_EMAIL = "email"

MESSAGES = {
    OTPCode.Purpose.PHONE_VERIFICATION: (
        "Your Nyikwa Abiya Welfare verification code is {code}. It expires in 5 minutes."
    ),
    OTPCode.Purpose.PASSWORD_RESET: (
        "Your Nyikwa Abiya Welfare password reset code is {code}. It expires in 5 minutes. "
        "If you did not ask to reset your password, ignore this message."
    ),
}

EMAIL_SUBJECTS = {
    OTPCode.Purpose.PHONE_VERIFICATION: "Your verification code",
    OTPCode.Purpose.PASSWORD_RESET: "Your password reset code",
}


class OTPError(Exception):
    """A code could not be issued or verified. The message is safe to show users."""


class OTPCooldownError(OTPError):
    def __init__(self, seconds_remaining):
        self.seconds_remaining = seconds_remaining
        super().__init__(
            f"Please wait {seconds_remaining} seconds before requesting a new code."
        )


class OTPDeliveryError(OTPError):
    """The code could not be sent by SMS or email."""


def mask_phone(phone_number):
    """254712345678 becomes +2547*****678."""
    if not phone_number or len(phone_number) < 7:
        return "your phone"
    return f"+{phone_number[:4]}*****{phone_number[-3:]}"


def mask_email(email):
    """brenda.njeri@example.com becomes b***@example.com."""
    name, _, domain = (email or "").partition("@")
    if not name or not domain:
        return "your email"
    return f"{name[0]}***@{domain}"


def available_channels(user):
    """The contacts registered to this account, partly hidden, for the user to choose from."""
    channels = []
    if user.phone_number:
        channels.append({"channel": CHANNEL_SMS, "destination": mask_phone(user.phone_number)})
    if user.email:
        channels.append({"channel": CHANNEL_EMAIL, "destination": mask_email(user.email)})
    return channels


def _deliver(user, channel, purpose, code):
    """Sends the code to the account's own registered contact. Returns the hidden destination."""
    message = MESSAGES[purpose].format(code=code)

    if channel == CHANNEL_EMAIL:
        if not user.email:
            raise OTPDeliveryError("This account has no email address.")
        try:
            send_mail(
                subject=f"Nyikwa Abiya Welfare: {EMAIL_SUBJECTS[purpose]}",
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False,
            )
        except Exception as exc:
            raise OTPDeliveryError("We could not send the email. Please try again shortly.") from exc
        return mask_email(user.email)

    if channel == CHANNEL_SMS:
        if not user.phone_number:
            raise OTPDeliveryError("This account has no phone number.")
        try:
            send_sms(user.phone_number, message)
        except SMSError as exc:
            raise OTPDeliveryError("We could not send the SMS. Please try again shortly.") from exc
        return mask_phone(user.phone_number)

    raise OTPDeliveryError("Unknown delivery method.")


def issue_otp(user, purpose, channel=CHANNEL_SMS):
    """
    Creates a fresh code, cancels older ones, and sends it to the account's
    registered phone or email. The returned code carries `sent_to`, the
    hidden destination, for showing to the user.
    """
    now = timezone.now()

    latest = (
        OTPCode.objects.filter(user=user, purpose=purpose)
        .order_by("-created_at")
        .first()
    )
    if latest and now - latest.created_at < RESEND_COOLDOWN:
        remaining = RESEND_COOLDOWN - (now - latest.created_at)
        raise OTPCooldownError(int(remaining.total_seconds()) + 1)

    OTPCode.objects.filter(user=user, purpose=purpose, is_used=False).update(is_used=True)

    code = "".join(secrets.choice("0123456789") for _ in range(OTP_LENGTH))
    otp = OTPCode.objects.create(
        user=user,
        purpose=purpose,
        code_hash=make_password(code),
        expires_at=now + OTP_EXPIRY,
    )

    try:
        otp.sent_to = _deliver(user, channel, purpose, code)
    except Exception:
        otp.delete()  # a code the user never received should not block a resend
        raise
    return otp


def verify_otp(user, purpose, code):
    """Checks a code. Raises OTPError with a user-friendly message on failure."""
    error = None

    with transaction.atomic():
        otp = (
            OTPCode.objects.select_for_update()
            .filter(user=user, purpose=purpose, is_used=False)
            .order_by("-created_at")
            .first()
        )

        if otp is None:
            error = "No active code. Request a new one."
        elif timezone.now() >= otp.expires_at:
            otp.is_used = True
            otp.save(update_fields=["is_used"])
            error = "This code has expired. Request a new one."
        elif not check_password(code, otp.code_hash):
            otp.attempts += 1
            remaining = MAX_ATTEMPTS - otp.attempts
            if remaining <= 0:
                otp.is_used = True
                error = "Too many incorrect attempts. Request a new code."
            else:
                error = f"Incorrect code. {remaining} attempt(s) left."
            otp.save(update_fields=["attempts", "is_used"])
        else:
            otp.is_used = True
            otp.save(update_fields=["is_used"])

    # Raise outside the transaction so the attempt count stays saved.
    if error:
        raise OTPError(error)