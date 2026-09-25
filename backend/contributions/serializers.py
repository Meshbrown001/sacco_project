from rest_framework import serializers

from .models import MemberWallet, MonthlyContribution, Penalty


class MonthlyContributionSerializer(serializers.ModelSerializer):
    month_label = serializers.SerializerMethodField()

    class Meta:
        model = MonthlyContribution
        fields = [
            "id", "month", "month_label", "amount_paid",
            "date_paid", "status", "penalty_charged",
        ]

    def get_month_label(self, obj):
        return obj.month.strftime("%B %Y")


class PenaltySerializer(serializers.ModelSerializer):
    month_label = serializers.SerializerMethodField()

    class Meta:
        model = Penalty
        fields = ["id", "amount", "date_charged", "paid", "month_label"]

    def get_month_label(self, obj):
        return obj.contribution.month.strftime("%B %Y")


class WalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = MemberWallet
        fields = ["balance", "updated_at"]