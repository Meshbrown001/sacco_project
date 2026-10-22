from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsChairperson
from contributions.models import SpecialLevy
from .chair_serializers import (
    AccountSerializer,
    ContributionSettingsSerializer,
    DeactivateSerializer,
    LevyObligationRowSerializer,
    LevySerializer,
    StaffCreateSerializer,
)
from .chair_services import (
    ChairError,
    STAFF_ROLES,
    cancel_levy,
    close_levy,
    create_levy,
    create_staff_account,
    deactivate_account,
    reactivate_account,
    update_contribution_settings,
    update_levy,
)
from .models import ContributionSettings

User = get_user_model()


def refused(exc):
    return Response({"detail": str(exc)}, status=exc.status)


# ----- Accounts ------------------------------------------------------------

class AccountListView(APIView):
    """
    GET /api/chair/accounts/?group=staff|members&search=text
    """
    permission_classes = [IsChairperson]

    def get(self, request):
        group = request.query_params.get("group", "members")
        accounts = User.objects.all()
        if group == "staff":
            accounts = accounts.filter(role__in=STAFF_ROLES)
        else:
            accounts = accounts.filter(role=User.Role.MEMBER)

        search = request.query_params.get("search", "").strip()
        if search:
            accounts = accounts.filter(
                Q(username__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(phone_number__icontains=search.lstrip("0"))
            )

        accounts = accounts.select_related("deactivated_by").order_by("-is_active", "first_name", "username")
        return Response({
            "group": group,
            "current_user_id": request.user.id,
            "accounts": AccountSerializer(accounts, many=True).data,
        })


class StaffCreateView(APIView):
    """POST /api/chair/accounts/staff/"""
    permission_classes = [IsChairperson]

    def post(self, request):
        serializer = StaffCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = create_staff_account(request.user, serializer.validated_data)
        except ChairError as exc:
            return refused(exc)
        return Response(AccountSerializer(user).data, status=status.HTTP_201_CREATED)


class AccountDeactivateView(APIView):
    """POST /api/chair/accounts/<id>/deactivate/  Body: {"reason": "..."}"""
    permission_classes = [IsChairperson]

    def post(self, request, pk):
        target = get_object_or_404(User, pk=pk)
        serializer = DeactivateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            deactivate_account(request.user, target, serializer.validated_data["reason"])
        except ChairError as exc:
            return refused(exc)
        target.refresh_from_db()
        return Response(AccountSerializer(target).data)


class AccountReactivateView(APIView):
    """POST /api/chair/accounts/<id>/reactivate/"""
    permission_classes = [IsChairperson]

    def post(self, request, pk):
        target = get_object_or_404(User, pk=pk)
        try:
            reactivate_account(request.user, target)
        except ChairError as exc:
            return refused(exc)
        target.refresh_from_db()
        return Response(AccountSerializer(target).data)


# ----- Monthly settings ----------------------------------------------------

class SettingsView(APIView):
    """GET or PUT /api/chair/settings/"""
    permission_classes = [IsChairperson]

    def get(self, request):
        row = ContributionSettings.objects.first()
        if row is None:
            return Response({
                "monthly_amount": None,
                "penalty_rate": "15.00",
                "auto_prompt_enabled": True,
                "auto_prompt_threshold": "3000.00",
                "auto_prompt_max_per_day": 3,
                "updated_at": None,
            })
        return Response(ContributionSettingsSerializer(row).data)

    def put(self, request):
        serializer = ContributionSettingsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        row = update_contribution_settings(
            request.user,
            data["monthly_amount"],
            data["penalty_rate"],
            auto_prompt_enabled=data.get("auto_prompt_enabled"),
            auto_prompt_threshold=data.get("auto_prompt_threshold"),
            auto_prompt_max_per_day=data.get("auto_prompt_max_per_day"),
        )
        return Response(ContributionSettingsSerializer(row).data)
# ----- Special contributions -----------------------------------------------

class LevyListCreateView(APIView):
    """GET or POST /api/chair/levies/"""
    permission_classes = [IsChairperson]

    def get(self, request):
        levies = SpecialLevy.objects.select_related("created_by").order_by("-created_at")
        return Response({"levies": LevySerializer(levies, many=True).data})

    def post(self, request):
        serializer = LevySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            levy = create_levy(request.user, serializer.validated_data)
        except ChairError as exc:
            return refused(exc)
        return Response(LevySerializer(levy).data, status=status.HTTP_201_CREATED)


class LevyDetailView(APIView):
    """
    GET   /api/chair/levies/<id>/  - the contribution and every member's status
    PATCH /api/chair/levies/<id>/  - correct it before the deadline
    """
    permission_classes = [IsChairperson]

    def get(self, request, pk):
        levy = get_object_or_404(SpecialLevy, pk=pk)
        obligations = levy.obligations.select_related("member").order_by("member__first_name", "member__username")
        return Response({
            "levy": LevySerializer(levy).data,
            "members": LevyObligationRowSerializer(obligations, many=True).data,
        })

    def patch(self, request, pk):
        levy = get_object_or_404(SpecialLevy, pk=pk)
        serializer = LevySerializer(levy, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            levy = update_levy(request.user, levy, serializer.validated_data)
        except ChairError as exc:
            return refused(exc)
        return Response(LevySerializer(levy).data)


class LevyCancelView(APIView):
    """POST /api/chair/levies/<id>/cancel/"""
    permission_classes = [IsChairperson]

    def post(self, request, pk):
        levy = get_object_or_404(SpecialLevy, pk=pk)
        try:
            cancel_levy(request.user, levy)
        except ChairError as exc:
            return refused(exc)
        return Response(LevySerializer(levy).data)


class LevyCloseView(APIView):
    """POST /api/chair/levies/<id>/close/"""
    permission_classes = [IsChairperson]

    def post(self, request, pk):
        levy = get_object_or_404(SpecialLevy, pk=pk)
        try:
            close_levy(request.user, levy)
        except ChairError as exc:
            return refused(exc)
        return Response(LevySerializer(levy).data)