from django.core.management.base import BaseCommand

from contributions.services import send_arrears_prompts


class Command(BaseCommand):
    help = "Send automatic M-Pesa prompts to members whose debt is at or above the threshold."

    def add_arguments(self, parser):
        parser.add_argument(
            "--member", dest="username", default=None,
            help="Only this member, by username.",
        )
        parser.add_argument(
            "--force", action="store_true",
            help="Ignore the quiet hours, the four-hour gap and the daily cap. For testing.",
        )

    def handle(self, *args, **options):
        result = send_arrears_prompts(username=options["username"], force=options["force"])
        for key, value in result.items():
            self.stdout.write(f"{key}: {value}")