from rest_framework import serializers

from .models import MemberWallet, MonthlyContribution, Penalty, WalletEntry


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