from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Sum

from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsSecretary
from .models import MemberWallet, MonthlyContribution, Penalty, WalletEntry
from .serializers import (
    MonthlyContributionSerializer,
    PaymentHistorySerializer,
    PenaltySerializer,
    WalletSerializer,
)
from .services import (
    current_month_for,
    ensure_months,
    get_contribution_settings,
    sweep_member,
)

User = get_user_model()
ZERO = Decimal("0")


class MemberDashboardView(APIView):
    """
    Returns the logged-in member's own dashboard. Reads the member from
    the token, so a member can only ever see their own data.

    Before answering, it brings the member's record up to date: creates
    the current month, applies wallet credit, and charges any penalty
    now due. A penalty therefore shows from 00:00 on the 1st.
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
        overdue = [c for c in contributions if c.status == MonthlyContribution.Status.OVERDUE]
        current_row = next((c for c in contributions if c.month == current), None)

        # Debt, month by month, oldest first: the order payments clear it.
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
        total_owed = contribution_debt + penalty_debt

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
            "debt_summary": {
                "overdue_months_count": len(overdue),
                "overdue_contribution_debt": str(overdue_contribution_debt),
                "current_month_due": str(current_month_due),
                "contribution_debt": str(contribution_debt),
                "penalty_debt": str(penalty_debt),
                "total_owed": str(total_owed),
                "wallet_credit": str(wallet.balance),
            },
            "recent_payments": PaymentHistorySerializer(payments, many=True).data,
        })


class MonthListView(APIView):
    """
    Returns the distinct months that have any contribution activity,
    newest first, so the secretary can pick one. Secretary only.
    """
    permission_classes = [IsSecretary]

    def get(self, request):
        months = (
            MonthlyContribution.objects
            .values_list("month", flat=True)
            .distinct()
            .order_by("-month")
        )
        data = [
            {"month": m.isoformat(), "label": m.strftime("%B %Y")}
            for m in months
        ]
        return Response({"months": data})


class MonthlyListDetailView(APIView):
    """
    Returns one month's full list: every member, what they paid that
    month, when, their status, plus the month total and the penalties
    charged for that month. Secretary only.

    The month is passed as YYYY-MM-01 in the URL query, e.g.
    /api/contributions/secretary/month/?month=2026-06-01
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

        members = User.objects.filter(role=User.Role.MEMBER).order_by("username")

        rows = MonthlyContribution.objects.filter(month=month).select_related("member")
        row_by_member = {r.member_id: r for r in rows}

        member_list = []
        for member in members:
            row = row_by_member.get(member.id)
            full_name = (member.get_full_name() or member.username)
            if row:
                member_list.append({
                    "member": full_name,
                    "amount_paid": str(row.amount_paid),
                    "date_paid": row.date_paid.isoformat() if row.date_paid else None,
                    "status": row.status,
                })
            else:
                member_list.append({
                    "member": full_name,
                    "amount_paid": "0.00",
                    "date_paid": None,
                    "status": "unpaid",
                })

        total = (
            rows.filter(status=MonthlyContribution.Status.PAID)
            .aggregate(total=Sum("amount_paid"))["total"]
            or 0
        )

        penalties = Penalty.objects.filter(contribution__month=month).select_related("member")
        penalty_list = [
            {
                "member": (p.member.get_full_name() or p.member.username),
                "amount": str(p.amount),
                "paid": p.paid,
                "date_charged": p.date_charged.isoformat(),
            }
            for p in penalties
        ]

        return Response({
            "month": month.isoformat(),
            "label": month.strftime("%B %Y"),
            "members": member_list,
            "month_total": str(total),
            "penalties": penalty_list,
        })