from django.core.management.base import BaseCommand

from payments.daraja import DarajaError, get_access_token


class Command(BaseCommand):
    help = "Checks that the Daraja keys in .env work."

    def handle(self, *args, **options):
        try:
            token = get_access_token(force_refresh=True)
        except DarajaError as exc:
            self.stdout.write(self.style.ERROR(f"Failed: {exc}"))
            if exc.details:
                self.stdout.write(f"Details: {exc.details}")
            return
        self.stdout.write(self.style.SUCCESS(
            f"Daraja accepted the keys. Token received ({len(token)} characters)."
        ))