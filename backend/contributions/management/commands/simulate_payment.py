from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import CustomUser
from contributions.models import MonthlyContribution, Penalty
from contributions.services import record_payment


class Command(BaseCommand):
    help = "TESTING ONLY: records a fake payment and prints the member's statement."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("amount")
        parser.add_argument("--at", help='When Safaricom "completed" it: "YYYY-MM-DD HH:MM"')
        parser.add_argument("--today", help="Pretend today is this date: YYYY-MM-DD")
        parser.add_argument("--reference", default="", help="Fake M-Pesa receipt number")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("simulate_payment only runs with DEBUG=True.")

        try:
            member = CustomUser.objects.get(username=options["username"])
        except CustomUser.DoesNotExist:
            raise CommandError(f"No user named {options['username']}.")

        effective_at = None
        if options["at"]:
            try:
                effective_at = timezone.make_aware(
                    datetime.strptime(options["at"], "%Y-%m-%d %H:%M")
                )
            except ValueError:
                raise CommandError('--at must look like "2026-09-30 23:58"')

        today = None
        if options["today"]:
            today = datetime.strptime(options["today"], "%Y-%m-%d").date()

        result = record_payment(
            member,
            options["amount"],
            reference=options["reference"],
            effective_at=effective_at,
            description="Simulated payment",
            today=today,
        )

        if result["duplicate"]:
            self.stdout.write(self.style.WARNING(f"Reference {result['reference']} already recorded. Ignored."))
            return

        self.stdout.write(self.style.SUCCESS(f"\nCredited KES {result['credited']}"))
        if result["waived_penalties"]:
            self.stdout.write(f"Penalties waived (paid before deadline): {result['waived_penalties']}")
        self.stdout.write("Applied to:")
        for item in result["allocations"]:
            self.stdout.write(f"  {item['month']:%b %Y}  {item['type']:<13} KES {item['amount']}")
        if not result["allocations"]:
            self.stdout.write("  nothing owed; all kept as credit")
        self.stdout.write(f"Wallet credit left: KES {result['wallet_balance']}\n")

        self.stdout.write("MONTHS")
        self.stdout.write(f"  {'Month':<10}{'Due':>10}{'Paid':>10}{'Balance':>10}  Status")
        for row in MonthlyContribution.objects.filter(member=member).order_by("month"):
            self.stdout.write(
                f"  {row.month:%b %Y}  {row.amount_due:>10}{row.amount_paid:>10}"
                f"{row.balance:>10}  {row.status}"
            )

        self.stdout.write("PENALTIES")
        penalties = Penalty.objects.filter(member=member).select_related("contribution")
        for p in penalties:
            state = "WAIVED" if p.waived else ("paid" if p.paid else "owing")
            self.stdout.write(
                f"  {p.contribution.month:%b %Y}  rate {p.rate}%  amount {p.amount}"
                f"  paid {p.amount_paid}  balance {p.balance}  {state}"
            )
        if not penalties:
            self.stdout.write("  none")