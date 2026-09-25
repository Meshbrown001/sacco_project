from django.conf import settings


class SMSError(Exception):
    """Raised when an SMS cannot be sent."""


def send_sms(phone_number, message):
    """
    Sends one SMS. phone_number is stored as 2547XXXXXXXX.
    SMS_BACKEND = "console" prints the message in the server terminal.
    SMS_BACKEND = "africastalking" sends a real SMS.
    """
    if not phone_number:
        raise SMSError("This account has no phone number.")

    recipient = f"+{phone_number}"
    backend = getattr(settings, "SMS_BACKEND", "console")

    if backend == "console":
        print(
            f"\n===== SMS to {recipient} =====\n{message}\n"
            "==============================\n",
            flush=True,
        )
        return

    if backend == "africastalking":
        try:
            import africastalking
        except ImportError as exc:
            raise SMSError("Run: pip install africastalking") from exc

        africastalking.initialize(
            settings.AFRICASTALKING_USERNAME,
            settings.AFRICASTALKING_API_KEY,
        )
        sender_id = getattr(settings, "AFRICASTALKING_SENDER_ID", None) or None

        try:
            response = africastalking.SMS.send(message, [recipient], sender_id)
        except Exception as exc:
            raise SMSError(f"Africa's Talking error: {exc}") from exc

        recipients = response.get("SMSMessageData", {}).get("Recipients", [])
        if not recipients or recipients[0].get("status") != "Success":
            raise SMSError(f"SMS not delivered: {response}")
        return

    raise SMSError(f"Unknown SMS_BACKEND: {backend}")