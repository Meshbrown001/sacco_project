"""
The chairperson's actions and the rules that guard them.

Accounts:
  - Staff accounts are created with a fixed role: secretary, treasurer or
    chairperson. Member accounts are never turned into staff accounts.
  - Deactivation needs a reason. A chairperson cannot deactivate their own
    account, and the last active chairperson can never be deactivated.
  - Reactivation is allowed. A reactivated member owes contributions again
    from the month of reactivation; the months away are skipped.

Monthly settings:
  - A new amount applies from next month; the current month keeps its amount.

Special contributions:
  - Correctable while active and before the deadline. The amount can only
    change while nobody has paid.
  - Cancellable only while nobody has paid; otherwise it can only be closed.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from accounts.models import AccountDeactivation
from contributions.models import LevyObligation, SpecialLevy
from contributions.services import create_levy_obligations, ensure_months
from .models import ContributionSettings

User = get_user_model()
ZERO = Decimal("0")

STAFF_ROLES = [User.Role.SECRETARY, User.Role.TREASURER, User.Role.CHAIRPERSON]


class ChairError(Exception):
    """A chairperson action was refused. The message is safe to show."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _log_out_everywhere(user):
    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def create_staff_account(actor, data):
    if data["role"] not in STAFF_ROLES:
        raise ChairError("Staff accounts must be secretary, treasurer or chairperson.")

    return User.objects.create_user(
        username=data["username"],
        password=data["password"],
        first_name=data["first_name"],
        last_name=data["last_name"],
        email=data.get("email", ""),
        role=data["role"],
    )


def deactivate_account(actor, target, reason, today=None):
    today = today or timezone.localdate()
    reason = (reason or "").strip()

    if len(reason) < 5:
        raise ChairError("Give a reason of at least 5 characters.")
    if target.pk == actor.pk:
        raise ChairError("You cannot deactivate your own account.")
    if not target.is_active:
        raise ChairError("This account is already deactivated.")
    if target.role == User.Role.CHAIRPERSON:
        active_chairs = User.objects.filter(role=User.Role.CHAIRPERSON, is_active=True).count()
        if active_chairs <= 1:
            raise ChairError("The SACCO must always have at least one active chairperson.")

    with transaction.atomic():
        target.is_active = False
        target.deactivated_at = timezone.now()
        target.deactivation_reason = reason
        target.deactivated_by = actor
        target.save(update_fields=["is_active", "deactivated_at", "deactivation_reason", "deactivated_by"])

        AccountDeactivation.objects.create(
            user=target,
            started_on=today,
            reason=reason,
            deactivated_by=actor,
        )
        _log_out_everywhere(target)

    return target


def reactivate_account(actor, target, today=None):
    today = today or timezone.localdate()

    if target.is_active:
        raise ChairError("This account is already active.")

    with transaction.atomic():
        target.is_active = True
        target.deactivated_at = None
        target.deactivation_reason = ""
        target.deactivated_by = None
        target.save(update_fields=["is_active", "deactivated_at", "deactivation_reason", "deactivated_by"])

        AccountDeactivation.objects.filter(user=target, ended_on__isnull=True).update(
            ended_on=today,
            reactivated_by=actor,
        )

    return target


# ---------------------------------------------------------------------------
# Monthly settings
# ---------------------------------------------------------------------------

def update_contribution_settings(actor, monthly_amount, penalty_rate):
    """
    Saves the new amount and fine rate. Before saving, every active member's
    current month is created at the old amount, so the change only affects
    months that start after it.
    """
    with transaction.atomic():
        for member in User.objects.filter(role=User.Role.MEMBER, is_active=True):
            ensure_months(member)

        settings_row = ContributionSettings.objects.first()
        if settings_row is None:
            settings_row = ContributionSettings(monthly_amount=monthly_amount, penalty_rate=penalty_rate)
        else:
            settings_row.monthly_amount = monthly_amount
            settings_row.penalty_rate = penalty_rate
        settings_row.save()

    return settings_row


# ---------------------------------------------------------------------------
# Special contributions
# ---------------------------------------------------------------------------

def levy_money_received(levy):
    totals = levy.obligations.aggregate(paid=Sum("amount_paid"), fines=Sum("fine_amount_paid"))
    return (totals["paid"] or ZERO) + (totals["fines"] or ZERO)


def create_levy(actor, data, today=None):
    today = today or timezone.localdate()
    if data["deadline"] < today:
        raise ChairError("The deadline cannot be in the past.")

    with transaction.atomic():
        levy = SpecialLevy.objects.create(created_by=actor, **data)
        create_levy_obligations(levy, today)
    return levy


def update_levy(actor, levy, data, today=None):
    today = today or timezone.localdate()

    if levy.status != SpecialLevy.Status.ACTIVE:
        raise ChairError("Only an active special contribution can be corrected.")
    if today > levy.deadline:
        raise ChairError("The deadline has passed, so this contribution can no longer be corrected.")
    if "deadline" in data and data["deadline"] < today:
        raise ChairError("The deadline cannot be in the past.")

    amount_changed = "amount" in data and data["amount"] != levy.amount
    if amount_changed and levy_money_received(levy) > 0:
        raise ChairError(
            "Members have already paid toward this contribution, so its amount can no longer change."
        )

    with transaction.atomic():
        for field, value in data.items():
            setattr(levy, field, value)
        levy.save()
        if amount_changed:
            levy.obligations.update(amount_due=levy.amount)
        create_levy_obligations(levy, today)  # a later deadline may take in new members
    return levy


def cancel_levy(actor, levy):
    if levy.status != SpecialLevy.Status.ACTIVE:
        raise ChairError("Only an active special contribution can be cancelled.")
    if levy_money_received(levy) > 0:
        raise ChairError("Members have already paid toward this contribution. Close it instead of cancelling.")

    with transaction.atomic():
        levy.obligations.all().delete()  # they hold no money
        levy.status = SpecialLevy.Status.CANCELLED
        levy.closed_at = timezone.now()
        levy.save(update_fields=["status", "closed_at", "updated_at"])
    return levy


def close_levy(actor, levy):
    """Stops new obligations and fines. Amounts already owed stay owed."""
    if levy.status != SpecialLevy.Status.ACTIVE:
        raise ChairError("Only an active special contribution can be closed.")
    levy.status = SpecialLevy.Status.CLOSED
    levy.closed_at = timezone.now()
    levy.save(update_fields=["status", "closed_at", "updated_at"])
    return levy