import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.models import CustomUser
from accounts.serializers import normalize_kenyan_phone
from payments.models import MpesaTransaction
from payments.services import PaymentError, initiate_payment, refresh_status, status_message


class Command(BaseCommand):
    help = "SANDBOX ONLY: sends a real PIN prompt and waits for the result."

    def add_arguments(self, parser):
        parser.add_argument("username", help="Member the payment belongs to")
        parser.add_argument("phone", help="Safaricom number to prompt, e.g. 0712345678")
        parser.add_argument("amount", nargs="?", default="1", help="Whole shillings, default 1")

    def handle(self, *args, **options):
        if settings.MPESA_ENV != "sandbox":
            raise CommandError("This test command only runs with MPESA_ENV=sandbox.")

        try:
            member = CustomUser.objects.get(username=options["username"])
        except CustomUser.DoesNotExist:
            raise CommandError(f"No user named {options['username']}.")

        try:
            phone = normalize_kenyan_phone(options["phone"])
        except Exception:
            raise CommandError("Enter a valid Kenyan phone number, e.g. 0712345678.")

        try:
            tx, message = initiate_payment(member, int(options["amount"]), phone)
        except PaymentError as exc:
            raise CommandError(str(exc))

        self.stdout.write(self.style.SUCCESS(f"Prompt sent. Transaction {tx.pk}. {message}"))
        self.stdout.write("Enter your PIN on the phone. Waiting up to 2 minutes...")

        for _ in range(24):
            time.sleep(5)
            tx.refresh_from_db()
            if tx.status == MpesaTransaction.Status.PENDING:
                tx = refresh_status(tx)
            if tx.status != MpesaTransaction.Status.PENDING:
                break
            self.stdout.write("  still waiting...")

        tx.refresh_from_db()
        self.stdout.write(f"\nStatus:   {tx.get_status_display()}")
        self.stdout.write(f"Message:  {status_message(tx)}")
        self.stdout.write(f"Receipt:  {tx.mpesa_receipt or '-'}")
        self.stdout.write(f"Credited: {tx.credited}")