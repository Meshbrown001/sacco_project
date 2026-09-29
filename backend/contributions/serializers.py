from rest_framework import serializers

from .models import LevyObligation, MemberWallet, MonthlyContribution, Penalty, WalletEntry


class MonthlyContributionSerializer(serializers.ModelSerializer):
    month_label = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    balance = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = MonthlyContribution
        fields = [
            "id", "month", "month_label",
            "amount_due", "amount_paid", "balance",
            "date_paid", "status", "status_label", "penalty_charged",
        ]

    def get_month_label(self, obj):
        return obj.month.strftime("%B %Y")


class PenaltySerializer(serializers.ModelSerializer):
    month = serializers.DateField(source="contribution.month", read_only=True)
    month_label = serializers.SerializerMethodField()
    balance = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    reason = serializers.CharField(read_only=True)
    state = serializers.SerializerMethodField()

    class Meta:
        model = Penalty
        fields = [
            "id", "month", "month_label", "reason", "rate",
            "amount", "amount_paid", "balance",
            "date_charged", "date_paid",
            "paid", "waived", "waived_reason", "state",
        ]

    def get_month_label(self, obj):
        return obj.contribution.month.strftime("%B %Y")

    def get_state(self, obj):
        if obj.waived:
            return "waived"
        if obj.paid:
            return "paid"
        if obj.amount_paid > 0:
            return "part-paid"
        return "unpaid"


class WalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = MemberWallet
        fields = ["balance", "updated_at"]


class PaymentHistorySerializer(serializers.ModelSerializer):
    """Money the member paid in, newest first."""
    class Meta:
        model = WalletEntry
        fields = ["id", "amount", "reference", "description", "effective_at"]


class MemberLevySerializer(serializers.ModelSerializer):
    """One special contribution as the member sees it on their dashboard."""
    purpose = serializers.CharField(source="levy.purpose", read_only=True)
    description = serializers.CharField(source="levy.description", read_only=True)
    deadline = serializers.DateField(source="levy.deadline", read_only=True)
    fine_label = serializers.CharField(source="levy.fine_label", read_only=True)
    levy_status = serializers.CharField(source="levy.status", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    balance = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    fine_balance = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    total_owed = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = LevyObligation
        fields = [
            "id", "purpose", "description", "deadline", "fine_label", "levy_status",
            "amount_due", "amount_paid", "balance", "date_paid", "status", "status_label",
            "fine_amount", "fine_amount_paid", "fine_balance", "fine_waived", "fine_waived_reason",
            "total_owed",
        ]