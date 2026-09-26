import logging

from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import MpesaTransaction
from .serializers import InitiatePaymentSerializer, TransactionSerializer
from .services import (
    PaymentError,
    handle_callback,
    initiate_payment,
    refresh_status,
    secret_matches,
)

logger = logging.getLogger(__name__)


class InitiatePaymentView(APIView):
    """
    Sends an M-Pesa PIN prompt for the logged-in member.
    POST /api/payments/mpesa/stk-push/
    Body: {"amount": 1000, "phone_number": "0712345678"}
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        member = request.user
        if member.role != member.Role.MEMBER:
            return Response({"detail": "Only members can make contributions."}, status=403)

        serializer = InitiatePaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            tx, customer_message = initiate_payment(
                member,
                serializer.validated_data["amount"],
                serializer.validated_data["phone_number"],
            )
        except PaymentError as exc:
            return Response({"detail": str(exc)}, status=exc.status)

        return Response(
            {
                "transaction": TransactionSerializer(tx).data,
                "customer_message": customer_message,
            },
            status=status.HTTP_201_CREATED,
        )


class PaymentStatusView(APIView):
    """
    The dashboard polls this while waiting for the PIN.
    GET /api/payments/status/<id>/
    A member can only see their own payments.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        tx = get_object_or_404(MpesaTransaction, pk=pk, member=request.user)
        tx = refresh_status(tx)
        return Response(TransactionSerializer(tx).data)


class MpesaCallbackView(APIView):
    """
    Safaricom posts payment results here.
    POST /api/payments/mpesa/callback/<secret>/
    No login: the secret in the address proves the caller knows it.
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request, secret):
        if not secret_matches(secret):
            logger.warning("Callback with a wrong secret from %s", request.META.get("REMOTE_ADDR"))
            return Response({"ResultCode": 1, "ResultDesc": "Rejected"}, status=403)

        try:
            handle_callback(request.data)
        except Exception:
            # Log it, but still tell Safaricom we received it. The status
            # query path will retry crediting while the member waits.
            logger.exception("Error while processing an M-Pesa callback")

        return Response({"ResultCode": 0, "ResultDesc": "Accepted"})