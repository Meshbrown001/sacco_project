from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model

from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsSecretary
from .models import (
    LevyObligation,
    MemberWallet,
    MonthlyContribution,
    Penalty,
    SpecialLevy,
    WalletEntry,
)
from .serializers import (
    MemberLevySerializer,
    MonthlyContributionSerializer,
    PaymentHistorySerializer,
    PenaltySerializer,
    WalletSerializer,
)
from .services import (
    compute_status,
    current_month_for,
    ensure_months,
    get_contribution_settings,
    next_month,
    sweep_member,
)

User = get_user_model()
ZERO = Decimal("0")


def local_phone(phone):
    """254712345678 -> 0712345678, the way the SACCO writes numbers."""
    if not phone:
        return ""
    return "0" + phone[3:] if phone.startswith("254") else phone


# ---------------------------------------------------------------------------
# Member dashboard
# ---------------------------------------------------------------------------

class MemberDashboardView(APIView):
    """
    Returns the logged-in member's own dashboard. Reads the member from
    the token, so a member can only ever see their own data.

    Before answering, it brings the member's record up to date: creates
    the current month and any special contribution obligations, applies
    wallet credit, and charges any penalty or fine now due.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        member = request.user

        if member.role != member.Role.MEMBER:
            return Response(
                {"detail": "This dashboard is for members only.", "role": member.role},
                status=403,
            )

        settings_row = get_contribution_settings()
        if settings_row:
            sweep_member(member, settings_row)
        else:
            ensure_months(member)

        current = current_month_for()
        wallet, _ = MemberWallet.objects.get_or_create(member=member)

        contributions = list(MonthlyContribution.objects.filter(member=member).order_by("-month"))
        penalties = list(
            Penalty.objects.filter(member=member)
            .select_related("contribution")
            .order_by("contribution__month", "date_charged")
        )
        levy_obligations = list(
            LevyObligation.objects.filter(member=member)
            .exclude(levy__status=SpecialLevy.Status.CANCELLED)
            .select_related("levy")
            .order_by("levy__deadline")
        )
        overdue = [c for c in contributions if c.status == MonthlyContribution.Status.OVERDUE]
        current_row = next((c for c in contributions if c.month == current), None)

        penalty_by_month = {}
        for p in penalties:
            penalty_by_month[p.contribution.month] = (
                penalty_by_month.get(p.contribution.month, ZERO) + p.balance
            )

        breakdown = []
        for row in sorted(contributions, key=lambda c: c.month):
            penalty_balance = penalty_by_month.get(row.month, ZERO)
            if row.balance > 0 or penalty_balance > 0:
                breakdown.append({
                    "month": row.month.isoformat(),
                    "month_label": row.month.strftime("%B %Y"),
                    "is_current": row.month == current,
                    "contribution_balance": str(row.balance),
                    "penalty_balance": str(penalty_balance),
                    "total": str(row.balance + penalty_balance),
                })

        overdue_contribution_debt = sum((c.balance for c in overdue), ZERO)
        current_month_due = current_row.balance if current_row else ZERO
        contribution_debt = overdue_contribution_debt + current_month_due
        penalty_debt = sum((p.balance for p in penalties), ZERO)
        monthly_owed = contribution_debt + penalty_debt
        special_debt = sum((ob.total_owed for ob in levy_obligations), ZERO)
        total_owed = monthly_owed + special_debt

        payments = (
            WalletEntry.objects.filter(
                wallet=wallet,
                entry_type=WalletEntry.EntryType.CREDIT,
            )
            .order_by("-effective_at")[:10]
        )

        return Response({
            "username": member.username,
            "full_name": member.get_full_name() or member.username,
            "phone_number": member.phone_number,
            "wallet": WalletSerializer(wallet).data,
            "current_monthly_amount": str(settings_row.monthly_amount if settings_row else ZERO),
            "penalty_rate": str(settings_row.penalty_rate if settings_row else ZERO),
            "current_month": (
                MonthlyContributionSerializer(current_row).data if current_row else None
            ),
            "contributions": MonthlyContributionSerializer(contributions, many=True).data,
            "overdue_months": MonthlyContributionSerializer(overdue, many=True).data,
            "penalties": PenaltySerializer(penalties, many=True).data,
            "debt_breakdown": breakdown,
            "special_contributions": MemberLevySerializer(levy_obligations, many=True).data,
            "debt_summary": {
                "overdue_months_count": len(overdue),
                "overdue_contribution_debt": str(overdue_contribution_debt),
                "current_month_due": str(current_month_due),
                "contribution_debt": str(contribution_debt),
                "penalty_debt": str(penalty_debt),
                "monthly_owed": str(monthly_owed),
                "special_contributions_debt": str(special_debt),
                "total_owed": str(total_owed),
                "wallet_credit": str(wallet.balance),
            },
            "recent_payments": PaymentHistorySerializer(payments, many=True).data,
        })


# ---------------------------------------------------------------------------
# Secretary: choosing a month
# ---------------------------------------------------------------------------

class MonthListView(APIView):
    """
    The years and months the secretary can pick from, newest first.
    The current month always appears, even before anyone pays.
    GET /api/contributions/secretary/months/
    Secretary only.
    """
    permission_classes = [IsSecretary]

    def get(self, request):
        current = current_month_for()
        months = set(
            MonthlyContribution.objects.values_list("month", flat=True).distinct()
        )
        months.add(current)

        years = {}
        for month in sorted(months, reverse=True):
            years.setdefault(month.year, []).append({
                "month": month.isoformat(),
                "name": month.strftime("%B"),
                "label": month.strftime("%B %Y"),
            })

        return Response({
            "current": current.isoformat(),
            "years": [
                {"year": year, "months": items}
                for year, items in sorted(years.items(), reverse=True)
            ],
        })


# ---------------------------------------------------------------------------
# Secretary: one month's list
# ---------------------------------------------------------------------------

def _penalty_state(penalty):
    if penalty.waived:
        return "waived"
    if penalty.paid:
        return "paid"
    if penalty.amount_paid > 0:
        return "part-paid"
    return "unpaid"


class MonthlyListDetailView(APIView):
    """
    One month's list: every member who had joined by the end of that
    month, what the month required, what they paid, the penalty charged
    for that month and what was paid toward it, plus the month's totals.

    GET /api/contributions/secretary/month/?month=2026-09-01
    Secretary only.
    """
    permission_classes = [IsSecretary]

    def get(self, request):
        month_str = request.query_params.get("month")
        if not month_str:
            return Response({"detail": "A month query parameter is required."}, status=400)

        try:
            year, mon, _ = month_str.split("-")
            month = date(int(year), int(mon), 1)
        except (ValueError, AttributeError):
            return Response({"detail": "Month must be in YYYY-MM-01 format."}, status=400)

        current = current_month_for()
        if month > current:
            return Response({"detail": "That month has not started yet."}, status=400)

        last_day = next_month(month) - timedelta(days=1)
        settings_row = get_contribution_settings()
        default_due = settings_row.monthly_amount if settings_row else ZERO

        rows = {
            r.member_id: r
            for r in MonthlyContribution.objects.filter(month=month).select_related("member")
        }
        penalties = {}
        for p in Penalty.objects.filter(contribution__month=month).select_related("contribution"):
            penalties.setdefault(p.member_id, []).append(p)

        # Members who had joined by the end of the month. Inactive members
        # appear only if they have a record for this month.
        candidates = User.objects.filter(
            role=User.Role.MEMBER,
            date_joined_sacco__lte=last_day,
        ).order_by("first_name", "last_name", "username")

        members = []
        totals = {
            "expected": ZERO, "collected": ZERO, "outstanding": ZERO,
            "penalties_charged": ZERO, "penalties_collected": ZERO,
        }
        counts = {"paid": 0, "partial": 0, "unpaid": 0, "overdue": 0, "waived": 0}

        for member in candidates:
            row = rows.get(member.id)
            if row is None and not member.is_active:
                continue

            if row:
                amount_due = row.amount_due
                amount_paid = row.amount_paid
                balance = row.balance
                status = compute_status(row, current)
                date_paid = row.date_paid.isoformat() if row.date_paid else None
            else:
                # No record yet: the member has done nothing for this month.
                amount_due = default_due
                amount_paid = ZERO
                balance = default_due
                status = (
                    MonthlyContribution.Status.OVERDUE if month < current
                    else MonthlyContribution.Status.UNPAID
                )
                date_paid = None

            penalty_data = None
            penalty_paid = ZERO
            member_penalties = penalties.get(member.id, [])
            if member_penalties:
                p = member_penalties[0]
                penalty_paid = sum((x.amount_paid for x in member_penalties), ZERO)
                state = _penalty_state(p)
                if state == "waived":
                    counts["waived"] += 1
                else:
                    totals["penalties_charged"] += sum((x.amount for x in member_penalties), ZERO)
                    totals["penalties_collected"] += penalty_paid
                penalty_data = {
                    "rate": str(p.rate),
                    "amount": str(sum((x.amount for x in member_penalties), ZERO)),
                    "amount_paid": str(penalty_paid),
                    "balance": str(sum((x.balance for x in member_penalties), ZERO)),
                    "state": state,
                    "reason": p.reason,
                    "waived_reason": p.waived_reason,
                }

            counts[status] = counts.get(status, 0) + 1
            totals["expected"] += amount_due
            totals["collected"] += amount_paid
            totals["outstanding"] += balance

            members.append({
                "member_id": member.id,
                "name": member.get_full_name() or member.username,
                "username": member.username,
                "phone": local_phone(member.phone_number),
                "amount_due": str(amount_due),
                "amount_paid": str(amount_paid),
                "balance": str(balance),
                "status": status,
                "fully_paid": status == MonthlyContribution.Status.PAID,
                "date_paid": date_paid,
                "penalty": penalty_data,
                "total_paid": str(amount_paid + penalty_paid),
            })

        return Response({
            "month": month.isoformat(),
            "label": month.strftime("%B %Y"),
            "is_current": month == current,
            "members": members,
            "summary": {
                "members_count": len(members),
                "fully_paid_count": counts["paid"],
                "partial_count": counts["partial"],
                "unpaid_count": counts["unpaid"] + counts["overdue"],
                "waived_penalties_count": counts["waived"],
                "expected": str(totals["expected"]),
                "collected": str(totals["collected"]),
                "outstanding": str(totals["outstanding"]),
                "penalties_charged": str(totals["penalties_charged"]),
                "penalties_collected": str(totals["penalties_collected"]),
                "total_collected": str(totals["collected"] + totals["penalties_collected"]),
            },
        })



from django.shortcuts import get_object_or_404
from accounts.permissions import IsSecretary
from .models import SpecialLevy
# (APIView and Response are already imported at the top of this file.)


class SecretaryLevyListView(APIView):
    """GET /api/contributions/secretary/levies/ - all special contributions, newest first."""
    permission_classes = [IsSecretary]

    def get(self, request):
        from core.chair_serializers import LevySerializer
        levies = SpecialLevy.objects.select_related("created_by").order_by("-created_at")
        return Response({"levies": LevySerializer(levies, many=True).data})


class SecretaryLevyDetailView(APIView):
    """GET /api/contributions/secretary/levies/<id>/ - one contribution and every member's record."""
    permission_classes = [IsSecretary]

    def get(self, request, pk):
        from core.chair_serializers import LevySerializer, LevyObligationRowSerializer
        levy = get_object_or_404(SpecialLevy, pk=pk)
        obligations = levy.obligations.select_related("member").order_by(
            "member__first_name", "member__username"
        )
        return Response({
            "levy": LevySerializer(levy).data,
            "members": LevyObligationRowSerializer(obligations, many=True).data,
        })    