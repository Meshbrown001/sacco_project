from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from contributions.services import run_penalty_sweep


class Command(BaseCommand):
    help = "Charges penalties for finished months that are not fully paid."

    def add_arguments(self, parser):
        parser.add_argument(
            "--today",
            help="Pretend today is this date (YYYY-MM-DD). For testing only.",
        )
        parser.add_argument(
            "--member",
            help="Sweep only this username. For testing only.",
        )

    def handle(self, *args, **options):
        today = None
        if options["today"]:
            try:
                today = datetime.strptime(options["today"], "%Y-%m-%d").date()
            except ValueError:
                raise CommandError("--today must look like 2026-11-02")

        result = run_penalty_sweep(today=today, username=options["member"])

        if "error" in result:
            self.stdout.write(self.style.WARNING(result["error"]))
            return

        for key, value in result.items():
            self.stdout.write(f"{key.replace('_', ' ').capitalize()}: {value}")
        self.stdout.write(self.style.SUCCESS("Penalty sweep finished."))