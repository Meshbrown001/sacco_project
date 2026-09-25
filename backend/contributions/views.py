from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Sum

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions

from core.models import ContributionSettings
from accounts.permissions import IsSecretary
from .models import MemberWallet, MonthlyContribution, Penalty
from .serializers import (
    MonthlyContributionSerializer,
    PenaltySerializer,
    WalletSerializer,
)

User = get_user_model()


class MemberDashboardView(APIView):
    """
    Returns the logged-in member's own dashboard: wallet balance,
    their monthly contributions, overdue months, unpaid penalties,
    and the total they owe. Reads the member from the token, so a
    member can only ever see their own data.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        member = request.user

        # Only members have wallets and contributions.
        if member.role != member.Role.MEMBER:
            return Response(
                {"detail": "This dashboard is for members only."},
                status=403,
            )

        wallet, _ = MemberWallet.objects.get_or_create(member=member)

        contributions = MonthlyContribution.objects.filter(member=member)
        overdue = contributions.filter(status=MonthlyContribution.Status.OVERDUE)
        penalties = Penalty.objects.filter(member=member)
        unpaid_penalties = penalties.filter(paid=False)

        # Current contribution amount, used for every overdue month.
        settings_row = ContributionSettings.objects.first()
        current_amount = settings_row.monthly_amount if settings_row else Decimal("0")

        overdue_count = overdue.count()
        contribution_debt = current_amount * overdue_count
        penalty_debt = sum((p.amount for p in unpaid_penalties), Decimal("0"))
        total_owed = contribution_debt + penalty_debt

        return Response({
            "username": member.username,
            "wallet": WalletSerializer(wallet).data,
            "current_monthly_amount": str(current_amount),
            "contributions": MonthlyContributionSerializer(contributions, many=True).data,
            "overdue_months": MonthlyContributionSerializer(overdue, many=True).data,
            "penalties": PenaltySerializer(penalties, many=True).data,
            "debt_summary": {
                "overdue_months_count": overdue_count,
                "contribution_debt": str(contribution_debt),
                "penalty_debt": str(penalty_debt),
                "total_owed": str(total_owed),
            },
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

        # Every member, so unpaid members still appear on the list.
        members = User.objects.filter(role=User.Role.MEMBER).order_by("username")

        # The contribution rows that exist for this month, keyed by member id.
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
                # No row means this member has done nothing for this month.
                member_list.append({
                    "member": full_name,
                    "amount_paid": "0.00",
                    "date_paid": None,
                    "status": "unpaid",
                })

        # The month total is the sum of what was actually paid.
        total = (
            rows.filter(status=MonthlyContribution.Status.PAID)
            .aggregate(total=Sum("amount_paid"))["total"]
            or 0
        )

        # Penalties charged for this month, so the secretary can follow up.
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