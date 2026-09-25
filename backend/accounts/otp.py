import secrets
from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone

from .models import OTPCode
from .sms import send_sms

OTP_LENGTH = 6
OTP_EXPIRY = timedelta(minutes=5)
MAX_ATTEMPTS = 5
RESEND_COOLDOWN = timedelta(seconds=60)

MESSAGES = {
    OTPCode.Purpose.PHONE_VERIFICATION: (
        "Your SACCO verification code is {code}. It expires in 5 minutes."
    ),
    OTPCode.Purpose.PASSWORD_RESET: (
        "Your SACCO password reset code is {code}. It expires in 5 minutes. "
        "If you did not request it, ignore this message."
    ),
}


class OTPError(Exception):
    """A code could not be issued or verified. The message is safe to show users."""


class OTPCooldownError(OTPError):
    def __init__(self, seconds_remaining):
        self.seconds_remaining = seconds_remaining
        super().__init__(
            f"Please wait {seconds_remaining} seconds before requesting a new code."
        )


def mask_phone(phone_number):
    """254712345678 becomes +2547*****678."""
    if not phone_number or len(phone_number) < 7:
        return "your phone"
    return f"+{phone_number[:4]}*****{phone_number[-3:]}"


def issue_otp(user, purpose):
    """Creates a fresh code, cancels older ones, and sends it by SMS."""
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
        send_sms(user.phone_number, MESSAGES[purpose].format(code=code))
    except Exception:
        otp.delete()  # a code the member never received should not block a resend
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