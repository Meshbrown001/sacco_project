"""
Contribution, penalty and wallet rules for the SACCO.

The rules:
  1. Each month freezes its contribution amount (amount_due) when it falls due.
  2. A month not fully paid by 00:00 on the 1st of the next month (Nairobi
     time) gets one penalty: rate% of that month's full amount_due.
  3. Before fining, the wallet pays whatever it can.
  4. Payments clear the oldest month first, penalty before contribution.
  5. Partial payments are allowed; the rest stays owing.
  6. Money left after all debts stays in the wallet as credit toward
     coming months.
  7. A payment Safaricom completed before a month's deadline cancels that
     month's penalty if the payment covered the month.
"""

from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from core.models import ContributionSettings
from .models import MemberWallet, MonthlyContribution, Penalty, WalletEntry

User = get_user_model()

CENTS = Decimal("0.01")
ZERO = Decimal("0")

# A payment prompt started this close to midnight may still be waiting on
# Safaricom when the sweep runs. The sweep holds off fining that member.
PENDING_GRACE = timedelta(minutes=15)


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def money(value):
    return Decimal(value).quantize(CENTS, rounding=ROUND_HALF_UP)


def first_of_month(d):
    return date(d.year, d.month, 1)


def next_month(month):
    if month.month == 12:
        return date(month.year + 1, 1, 1)
    return date(month.year, month.month + 1, 1)


def previous_month(month):
    if month.month == 1:
        return date(month.year - 1, 12, 1)
    return date(month.year, month.month - 1, 1)


def months_between(start, end):
    """Yield every first-of-month date from start through end, inclusive."""
    month = start
    while month <= end:
        yield month
        month = next_month(month)


def month_deadline(month):
    """00:00 on the 1st of the following month, in the SACCO's time zone."""
    return timezone.make_aware(datetime.combine(next_month(month), time.min))


def current_month_for(today=None):
    return first_of_month(today or timezone.localdate())


# ---------------------------------------------------------------------------
# Small building blocks
# ---------------------------------------------------------------------------

def get_contribution_settings():
    return ContributionSettings.objects.first()


def calculate_penalty(amount_due, rate):
    return money(Decimal(amount_due) * Decimal(rate) / Decimal("100"))


def compute_status(row, current_month):
    if row.is_fully_paid:
        return MonthlyContribution.Status.PAID
    if row.month < current_month:
        return MonthlyContribution.Status.OVERDUE
    if row.amount_paid > 0:
        return MonthlyContribution.Status.PARTIAL
    return MonthlyContribution.Status.UNPAID


def get_wallet_for_update(member):
    """Returns the member's wallet, locked until the transaction ends."""
    wallet, _ = MemberWallet.objects.get_or_create(member=member)
    return MemberWallet.objects.select_for_update().get(pk=wallet.pk)


def _record_entry(wallet, entry_type, source, amount, description="",
                  contribution=None, penalty=None, reference="", effective_at=None):
    return WalletEntry.objects.create(
        wallet=wallet,
        entry_type=entry_type,
        source=source,
        amount=amount,
        balance_after=wallet.balance,
        description=description,
        contribution=contribution,
        penalty=penalty,
        reference=reference,
        effective_at=effective_at or timezone.now(),
    )


def has_pending_payment_before(member, deadline):
    """
    True if the member started an M-Pesa payment shortly before the
    deadline and Safaricom has not answered yet. Returns False until the
    payments app defines MpesaTransaction in Step 5.
    """
    try:
        from payments.models import MpesaTransaction
    except ImportError:
        return False
    return MpesaTransaction.objects.filter(
        member=member,
        status="pending",
        created_at__lt=deadline,
        created_at__gte=deadline - PENDING_GRACE,
    ).exists()


# ---------------------------------------------------------------------------
# Months
# ---------------------------------------------------------------------------

def ensure_months(member, today=None):
    """
    Creates a contribution row for every month from the member's joining
    month through the current month, freezing today's amount on each new
    row, and refreshes every row's status. Returns how many rows turned
    overdue during this call.
    """
    settings_row = get_contribution_settings()
    amount = settings_row.monthly_amount if settings_row else ZERO
    current = current_month_for(today)
    join = first_of_month(member.date_joined_sacco)
    if join > current:
        return 0

    existing = set(
        MonthlyContribution.objects.filter(
            member=member, month__gte=join, month__lte=current,
        ).values_list("month", flat=True)
    )
    missing = [
        MonthlyContribution(
            member=member,
            month=month,
            amount_due=amount,
            status=MonthlyContribution.Status.UNPAID,
        )
        for month in months_between(join, current)
        if month not in existing
    ]
    if missing:
        MonthlyContribution.objects.bulk_create(missing, ignore_conflicts=True)

    newly_overdue = 0
    for row in MonthlyContribution.objects.filter(member=member, month__lte=current):
        changed = []
        if row.amount_due == 0 and amount > 0:
            row.amount_due = amount
            changed.append("amount_due")
        status = compute_status(row, current)
        if status != row.status:
            if status == MonthlyContribution.Status.OVERDUE:
                newly_overdue += 1
            row.status = status
            changed.append("status")
        if changed:
            row.save(update_fields=changed)
    return newly_overdue


# ---------------------------------------------------------------------------
# Paying debts from the wallet
# ---------------------------------------------------------------------------

def apply_wallet(member, today=None):
    """
    Pays debts from the wallet: oldest month first, penalties before the
    contribution. Stops when the wallet runs dry. Money left over stays
    in the wallet. Returns a list describing each payment made.
    """
    allocations = []
    current = current_month_for(today)

    with transaction.atomic():
        wallet = get_wallet_for_update(member)
        if wallet.balance <= 0:
            return allocations

        rows = (
            MonthlyContribution.objects.select_for_update()
            .filter(member=member, month__lte=current)
            .order_by("month")
        )

        for row in rows:
            # Penalties for this month first.
            penalties = (
                Penalty.objects.select_for_update()
                .filter(contribution=row, waived=False, paid=False)
                .order_by("date_charged")
            )
            for penalty in penalties:
                if wallet.balance <= 0:
                    break
                pay = min(penalty.balance, wallet.balance)
                if pay <= 0:
                    continue
                penalty.amount_paid += pay
                fields = ["amount_paid"]
                if penalty.balance == 0:
                    penalty.paid = True
                    penalty.date_paid = timezone.now()
                    fields += ["paid", "date_paid"]
                penalty.save(update_fields=fields)

                wallet.balance -= pay
                _record_entry(
                    wallet, WalletEntry.EntryType.DEBIT, WalletEntry.Source.PENALTY, pay,
                    description=f"Penalty for {row.month:%B %Y}",
                    contribution=row, penalty=penalty,
                )
                allocations.append({"type": "penalty", "month": row.month, "amount": pay})

            if wallet.balance <= 0:
                break

            # Then the contribution itself.
            pay = min(row.balance, wallet.balance)
            if pay > 0:
                row.amount_paid += pay
                fields = ["amount_paid", "status"]
                if row.is_fully_paid:
                    row.date_paid = timezone.now()
                    fields.append("date_paid")
                row.status = compute_status(row, current)
                row.save(update_fields=fields)

                wallet.balance -= pay
                _record_entry(
                    wallet, WalletEntry.EntryType.DEBIT, WalletEntry.Source.CONTRIBUTION, pay,
                    description=f"Contribution for {row.month:%B %Y}",
                    contribution=row,
                )
                allocations.append({"type": "contribution", "month": row.month, "amount": pay})

            if wallet.balance <= 0:
                break

        wallet.save(update_fields=["balance", "updated_at"])

    return allocations


def waive_on_time_penalties(member, available, effective_at):
    """
    The midnight rule. If Safaricom completed a payment before a month's
    deadline, and the money covers everything up to and including that
    month, the penalty charged for that month is cancelled.
    Only untouched penalties qualify.
    """
    waived = []
    candidates = (
        Penalty.objects.select_for_update()
        .filter(member=member, waived=False, amount_paid=0)
        .select_related("contribution")
        .order_by("contribution__month")
    )

    for penalty in candidates:
        month = penalty.contribution.month
        if effective_at >= month_deadline(month):
            continue

        contribution_debt = sum(
            (row.balance for row in MonthlyContribution.objects.filter(
                member=member, month__lte=month)),
            ZERO,
        )
        penalty_debt = sum(
            (p.balance for p in Penalty.objects.filter(
                member=member, waived=False, contribution__month__lte=month,
            ).exclude(pk=penalty.pk)),
            ZERO,
        )

        if available >= contribution_debt + penalty_debt:
            penalty.waived = True
            penalty.waived_reason = (
                f"Payment completed {timezone.localtime(effective_at):%d %b %Y %H:%M}, "
                f"before the {month:%B %Y} deadline."
            )
            penalty.save(update_fields=["waived", "waived_reason"])
            waived.append(penalty)

    return waived


# ---------------------------------------------------------------------------
# Recording a payment
# ---------------------------------------------------------------------------

def record_payment(member, amount, reference="", effective_at=None,
                   source=WalletEntry.Source.MPESA, description="", today=None):
    """
    Credits the wallet, applies the midnight rule, then pays debts.
    The M-Pesa callback calls this in Step 5. A reference already on
    record is ignored, so a repeated callback never pays twice.
    """
    amount = money(amount)
    if amount <= 0:
        raise ValueError("Payment amount must be above zero.")
    effective_at = effective_at or timezone.now()

    with transaction.atomic():
        if reference and WalletEntry.objects.filter(
            reference=reference, entry_type=WalletEntry.EntryType.CREDIT,
        ).exists():
            return {"duplicate": True, "reference": reference}

        ensure_months(member, today)

        wallet = get_wallet_for_update(member)
        wallet.balance += amount
        wallet.save(update_fields=["balance", "updated_at"])
        _record_entry(
            wallet, WalletEntry.EntryType.CREDIT, source, amount,
            description=description or "M-Pesa payment",
            reference=reference, effective_at=effective_at,
        )

        waived = waive_on_time_penalties(member, wallet.balance, effective_at)
        allocations = apply_wallet(member, today)
        wallet.refresh_from_db()

    return {
        "duplicate": False,
        "credited": amount,
        "waived_penalties": [p.pk for p in waived],
        "allocations": allocations,
        "wallet_balance": wallet.balance,
    }


# ---------------------------------------------------------------------------
# The penalty sweep
# ---------------------------------------------------------------------------

def sweep_member(member, settings_row, today=None):
    """
    Brings one member up to date: creates missing months, pays what the
    wallet can cover, then fines each finished month still unpaid.
    """
    current = current_month_for(today)
    last_completed = previous_month(current)
    rate = settings_row.penalty_rate
    charged = 0
    skipped = 0

    with transaction.atomic():
        newly_overdue = ensure_months(member, today)
        apply_wallet(member, today)

        rows = (
            MonthlyContribution.objects.select_for_update()
            .filter(member=member, month__lte=last_completed, penalty_charged=False)
            .order_by("month")
        )
        for row in rows:
            if row.is_fully_paid:
                continue
            if has_pending_payment_before(member, month_deadline(row.month)):
                skipped += 1
                continue

            amount = calculate_penalty(row.amount_due, rate)
            if amount > 0:
                Penalty.objects.create(
                    member=member, contribution=row, rate=rate, amount=amount,
                )
            row.penalty_charged = True
            row.save(update_fields=["penalty_charged"])
            charged += 1

    return {"newly_overdue": newly_overdue, "charged": charged, "skipped": skipped}


def run_penalty_sweep(today=None, username=None):
    """
    Sweeps every active member, or one member when username is given.
    Safe to run as often as needed: each month is fined only once.
    """
    settings_row = get_contribution_settings()
    if settings_row is None:
        return {"error": "No contribution amount is set. Nothing to do."}

    members = User.objects.filter(role=User.Role.MEMBER, is_active=True)
    if username:
        members = members.filter(username=username)

    totals = {"newly_overdue": 0, "charged": 0, "skipped": 0}
    for member in members:
        result = sweep_member(member, settings_row, today)
        for key in totals:
            totals[key] += result[key]

    current = current_month_for(today)
    return {
        "members_checked": members.count(),
        "months_marked_overdue": totals["newly_overdue"],
        "penalties_charged": totals["charged"],
        "skipped_pending_payment": totals["skipped"],
        "penalty_rate": f"{settings_row.penalty_rate}%",
        "penalty_value_each": str(calculate_penalty(settings_row.monthly_amount, settings_row.penalty_rate)),
        "up_to_month": previous_month(current).isoformat(),
    }