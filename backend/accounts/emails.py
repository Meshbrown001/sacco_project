import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)

WELCOME_SUBJECT = "Welcome to Nyikwa Abiya Welfare"


def send_welcome_email(user):
    """
    Emails a new member a short welcome note. Returns True if it was sent.
    Never raises: a failed welcome email must not block a registration.
    """
    if not user.email:
        return False

    first_name = (user.first_name or user.username).strip()
    body = (
        f"Dear {first_name},\n\n"
        "Welcome to Nyikwa Abiya Welfare. Your account has been created "
        f"with the username {user.username}.\n\n"
        "To get started, log in, view your contributions and pay through M-Pesa.\n\n"
        "If you did not create this account, contact the SACCO office.\n"
    )

    try:
        send_mail(
            WELCOME_SUBJECT,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
        logger.info("Welcome email sent to user %s", user.pk)
        return True
    except Exception:
        logger.exception("Welcome email failed for user %s", user.pk)
        return False