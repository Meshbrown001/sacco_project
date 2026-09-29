from rest_framework import serializers

from accounts.serializers import normalize_kenyan_phone
from .models import MpesaTransaction
from .services import status_message


class InitiatePaymentSerializer(serializers.Serializer):
    """
    Checks what a member submits. levy_obligation_id chooses a special
    contribution; leaving it out pays the monthly contributions.
    """
    amount = serializers.IntegerField(
        min_value=1,
        max_value=250000,
        error_messages={
            "invalid": "Enter a whole number of shillings.",
            "min_value": "The amount must be at least KES 1.",
            "max_value": "M-Pesa allows at most KES 250,000 per payment.",
        },
    )
    phone_number = serializers.CharField()
    levy_obligation_id = serializers.IntegerField(required=False, allow_null=True)

    def validate_phone_number(self, value):
        return normalize_kenyan_phone(value)


class TransactionSerializer(serializers.ModelSerializer):
    """What the dashboard sees about a payment."""
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    message = serializers.SerializerMethodField()
    paying_for = serializers.CharField(read_only=True)

    class Meta:
        model = MpesaTransaction
        fields = [
            "id", "amount", "phone_number", "status", "status_label",
            "message", "paying_for", "mpesa_receipt", "transaction_date", "created_at",
        ]

    def get_message(self, obj):
        return status_message(obj)