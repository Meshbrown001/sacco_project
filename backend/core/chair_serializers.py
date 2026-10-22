from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Sum
from rest_framework import serializers

from contributions.models import LevyObligation, SpecialLevy
from .chair_services import STAFF_ROLES
from .models import ContributionSettings

User = get_user_model()
ZERO = Decimal("0")


def local_phone(phone):
    if not phone:
        return ""
    return "0" + phone[3:] if phone.startswith("254") else phone


# ----- Accounts ------------------------------------------------------------

class AccountSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()
    role_label = serializers.CharField(source="get_role_display", read_only=True)
    deactivated_by_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "username", "full_name", "email", "phone", "role", "role_label",
            "is_active", "date_joined_sacco", "last_login",
            "deactivated_at", "deactivation_reason", "deactivated_by_name",
        ]

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username

    def get_phone(self, obj):
        return local_phone(obj.phone_number)

    def get_deactivated_by_name(self, obj):
        who = obj.deactivated_by
        return (who.get_full_name() or who.username) if who else ""


class StaffCreateSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField(required=False, allow_blank=True)
    role = serializers.ChoiceField(
        choices=STAFF_ROLES,
        error_messages={"invalid_choice": "Choose secretary, treasurer or chairperson."},
    )
    password = serializers.CharField(write_only=True)
    password2 = serializers.CharField(write_only=True)

    def validate_username(self, value):
        value = value.strip()
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("That username is already taken.")
        return value

    def validate(self, attrs):
        if attrs["password"] != attrs["password2"]:
            raise serializers.ValidationError({"password2": "Passwords do not match."})
        candidate = User(
            username=attrs["username"],
            first_name=attrs["first_name"],
            last_name=attrs["last_name"],
            email=attrs.get("email", ""),
        )
        try:
            validate_password(attrs["password"], user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)})
        attrs.pop("password2")
        return attrs


class DeactivateSerializer(serializers.Serializer):
    reason = serializers.CharField(
        min_length=5,
        max_length=255,
        error_messages={
            "blank": "Give a reason for deactivating this account.",
            "min_length": "Give a reason of at least 5 characters.",
        },
    )


# ----- Monthly settings ----------------------------------------------------

class ContributionSettingsSerializer(serializers.ModelSerializer):
    monthly_amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("1"))
    penalty_rate = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=ZERO, max_value=Decimal("100"),
    )
    auto_prompt_enabled = serializers.BooleanField(required=False)
    auto_prompt_threshold = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=ZERO, required=False,
    )
    auto_prompt_max_per_day = serializers.IntegerField(
        min_value=1, max_value=10, required=False,
    )

    class Meta:
        model = ContributionSettings
        fields = [
            "monthly_amount", "penalty_rate",
            "auto_prompt_enabled", "auto_prompt_threshold", "auto_prompt_max_per_day",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]

# ----- Special contributions -----------------------------------------------

class LevySerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    fine_label = serializers.CharField(read_only=True)
    created_by_name = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()

    class Meta:
        model = SpecialLevy
        fields = [
            "id", "purpose", "description", "amount", "deadline",
            "fine_type", "fine_value", "fine_label",
            "status", "status_label", "created_at", "created_by_name", "closed_at",
            "summary",
        ]
        read_only_fields = ["status", "created_at", "closed_at"]

    def get_created_by_name(self, obj):
        who = obj.created_by
        return (who.get_full_name() or who.username) if who else ""

    def get_summary(self, obj):
        obligations = obj.obligations.all()
        totals = obligations.aggregate(
            due=Sum("amount_due"), paid=Sum("amount_paid"),
            fines=Sum("fine_amount"), fines_paid=Sum("fine_amount_paid"),
        )
        due = totals["due"] or ZERO
        paid = totals["paid"] or ZERO
        return {
            "members": obligations.count(),
            "fully_paid": obligations.filter(status=LevyObligation.Status.PAID).count(),
            "expected": str(due),
            "collected": str(paid),
            "outstanding": str(due - paid),
            "fines_charged": str(totals["fines"] or ZERO),
            "fines_collected": str(totals["fines_paid"] or ZERO),
        }

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("The amount must be above zero.")
        return value

    def validate_purpose(self, value):
        value = value.strip()
        if len(value) < 3:
            raise serializers.ValidationError("Give the reason for this contribution.")
        return value

    def validate(self, attrs):
        fine_type = attrs.get("fine_type", getattr(self.instance, "fine_type", SpecialLevy.FineType.PERCENT))
        fine_value = attrs.get("fine_value", getattr(self.instance, "fine_value", ZERO))
        if fine_value < 0:
            raise serializers.ValidationError({"fine_value": "The fine cannot be negative."})
        if fine_type == SpecialLevy.FineType.PERCENT and fine_value > 100:
            raise serializers.ValidationError({"fine_value": "A percentage fine cannot exceed 100."})
        return attrs


class LevyObligationRowSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    username = serializers.CharField(source="member.username", read_only=True)
    phone = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    balance = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    fine_balance = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = LevyObligation
        fields = [
            "id", "name", "username", "phone",
            "amount_due", "amount_paid", "balance", "date_paid", "status", "status_label",
            "fine_amount", "fine_amount_paid", "fine_balance", "fine_waived", "fine_waived_reason",
        ]

    def get_name(self, obj):
        return obj.member.get_full_name() or obj.member.username

    def get_phone(self, obj):
        return local_phone(obj.member.phone_number)