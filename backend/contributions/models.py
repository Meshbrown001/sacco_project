from decimal import Decimal

from django.conf import settings
from django.db import models


def format_percent(value):
    """10.00 -> '10', 12.50 -> '12.5', never scientific notation like '1E+1'."""
    text = f"{Decimal(value):f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


class MemberWallet(models.Model):
    """
    One balance per member. M-Pesa payments credit it, and the system
    pays debts from it: penalties, contributions and special contributions.
    Money left after all debts clear stays here as credit.
    """
    member = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wallet",
    )
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.member.username} wallet: {self.balance}"


class MonthlyContribution(models.Model):
    """
    One row per member per month. The month is stored as a date pinned
    to the first of that month, so 2026-06-01 means June 2026.

    amount_due freezes the contribution amount when the month falls due,
    so a later change by the chairperson never alters past debts.

    Status:
      unpaid  - current month, nothing paid yet
      partial - current month, part paid
      paid    - fully paid (any month)
      overdue - a finished month not fully paid; amount_paid shows
                any part payment
    """
    class Status(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PARTIAL = "partial", "Partially paid"
        PAID = "paid", "Paid"
        OVERDUE = "overdue", "Overdue"

    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="contributions",
    )
    month = models.DateField(help_text="First day of the contribution month, e.g. 2026-06-01")
    amount_due = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    date_paid = models.DateTimeField(
        null=True, blank=True,
        help_text="When the month became fully paid.",
    )
    penalty_charged = models.BooleanField(default=False)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.UNPAID,
    )

    class Meta:
        unique_together = ("member", "month")
        ordering = ["-month"]

    @property
    def balance(self):
        """Amount still owing for this month's contribution."""
        return max(self.amount_due - self.amount_paid, Decimal("0"))

    @property
    def is_fully_paid(self):
        return self.amount_due > 0 and self.amount_paid >= self.amount_due

    def __str__(self):
        return f"{self.member.username} - {self.month:%B %Y} - {self.status}"


class Penalty(models.Model):
    """
    A late fee for one unpaid month, charged once when the month ends.
    The rate and the amount freeze at the moment of charging, so later
    changes by the chairperson never alter an existing penalty.
    A waived penalty stays on record for audit but is never owed.
    """
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="penalties",
    )
    contribution = models.ForeignKey(
        MonthlyContribution,
        on_delete=models.CASCADE,
        related_name="penalties",
    )
    rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Percentage of the month's contribution, e.g. 15.00",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    date_charged = models.DateTimeField(auto_now_add=True)
    date_paid = models.DateTimeField(null=True, blank=True)
    paid = models.BooleanField(default=False)
    waived = models.BooleanField(default=False)
    waived_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["contribution__month", "date_charged"]

    @property
    def balance(self):
        """Amount still owing on this penalty. A waived penalty owes nothing."""
        if self.waived:
            return Decimal("0")
        return max(self.amount - self.amount_paid, Decimal("0"))

    @property
    def reason(self):
        return f"Fine: {format_percent(self.rate)}% of the {self.contribution.month:%B %Y} contribution"

    def __str__(self):
        state = "waived" if self.waived else ("paid" if self.paid else "unpaid")
        return f"{self.member.username} penalty {self.amount} ({state})"


class SpecialLevy(models.Model):
    """
    A one-off contribution the chairperson raises for a specific reason,
    such as a trip. Every active member owes it, including members who
    join before the deadline. Anyone not fully paid by the end of the
    deadline day is fined once, by a percentage or a fixed amount.

    Status:
      active    - open for payment
      closed    - finished; kept on record
      cancelled - withdrawn before anyone paid; kept on record
    """
    class FineType(models.TextChoices):
        PERCENT = "percent", "Percentage of the amount"
        FIXED = "fixed", "Fixed amount (KES)"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        CLOSED = "closed", "Closed"
        CANCELLED = "cancelled", "Cancelled"

    purpose = models.CharField(max_length=255, help_text="The reason, e.g. Annual trip to Mombasa")
    description = models.TextField(blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    deadline = models.DateField(help_text="Last day to pay without a fine.")
    fine_type = models.CharField(
        max_length=10,
        choices=FineType.choices,
        default=FineType.PERCENT,
    )
    fine_value = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="A percentage such as 15.00, or shillings such as 200.00",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    fines_charged = models.BooleanField(
        default=False,
        help_text="Set once the fines have been charged after the deadline.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="levies_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def fine_for(self, amount_due):
        """The fine a member pays for missing the deadline on amount_due."""
        if self.fine_type == self.FineType.FIXED:
            return self.fine_value
        return (Decimal(amount_due) * self.fine_value / Decimal("100")).quantize(Decimal("0.01"))

    @property
    def fine_label(self):
        if self.fine_type == self.FineType.FIXED:
            return f"KES {self.fine_value:,.2f}"
        return f"{format_percent(self.fine_value)}% of the amount"

    def __str__(self):
        return f"{self.purpose} - {self.amount} (due {self.deadline})"


class LevyObligation(models.Model):
    """
    What one member owes toward one special contribution. The amount is
    frozen when the obligation is created, so later corrections to the
    contribution do not silently change debts already partly paid.
    """
    class Status(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PARTIAL = "partial", "Partially paid"
        PAID = "paid", "Paid"
        OVERDUE = "overdue", "Overdue"

    levy = models.ForeignKey(
        SpecialLevy,
        on_delete=models.CASCADE,
        related_name="obligations",
    )
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="levy_obligations",
    )
    amount_due = models.DecimalField(max_digits=10, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    date_paid = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.UNPAID,
    )
    fine_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    fine_amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    fine_charged_at = models.DateTimeField(null=True, blank=True)
    fine_waived = models.BooleanField(default=False)
    fine_waived_reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("levy", "member")
        ordering = ["levy__deadline", "member__username"]

    @property
    def balance(self):
        return max(self.amount_due - self.amount_paid, Decimal("0"))

    @property
    def fine_balance(self):
        if self.fine_waived:
            return Decimal("0")
        return max(self.fine_amount - self.fine_amount_paid, Decimal("0"))

    @property
    def total_owed(self):
        return self.balance + self.fine_balance

    @property
    def is_fully_paid(self):
        return self.amount_due > 0 and self.amount_paid >= self.amount_due

    def __str__(self):
        return f"{self.member.username} - {self.levy.purpose} - {self.status}"


class WalletEntry(models.Model):
    """
    A permanent record of every movement in or out of a wallet.
    Credits come from M-Pesa. Debits pay a penalty, a contribution, a
    special contribution or its fine. The wallet balance must always
    equal the sum of its entries.

    effective_at is when the money actually moved. For M-Pesa it is the
    completion time Safaricom reports, which decides whether a payment
    beat a deadline.
    """
    class EntryType(models.TextChoices):
        CREDIT = "credit", "Credit"
        DEBIT = "debit", "Debit"

    class Source(models.TextChoices):
        MPESA = "mpesa", "M-Pesa payment"
        PENALTY = "penalty", "Penalty payment"
        CONTRIBUTION = "contribution", "Contribution payment"
        LEVY = "levy", "Special contribution"
        LEVY_FINE = "levy_fine", "Special contribution fine"
        ADJUSTMENT = "adjustment", "Manual adjustment"

    wallet = models.ForeignKey(
        MemberWallet,
        on_delete=models.CASCADE,
        related_name="entries",
    )
    entry_type = models.CharField(max_length=10, choices=EntryType.choices)
    source = models.CharField(max_length=20, choices=Source.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.CharField(max_length=255, blank=True)
    contribution = models.ForeignKey(
        MonthlyContribution,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="wallet_entries",
    )
    penalty = models.ForeignKey(
        Penalty,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="wallet_entries",
    )
    levy_obligation = models.ForeignKey(
        LevyObligation,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="wallet_entries",
    )
    reference = models.CharField(
        max_length=50, blank=True,
        help_text="M-Pesa receipt number for credits from M-Pesa.",
    )
    effective_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_at", "-id"]
        indexes = [models.Index(fields=["wallet", "effective_at"])]

    def __str__(self):
        return f"{self.wallet.member.username} {self.entry_type} {self.amount} ({self.source})"