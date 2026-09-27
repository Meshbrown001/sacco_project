"""
Payment flow:
  1. initiate_payment  - records the request, then sends the PIN prompt.
  2. handle_callback   - Safaricom reports the result; success credits the wallet.
  3. refresh_status    - if the callback is late, asks Safaricom directly.

A payment credits the wallet exactly once, whichever of 2 or 3 confirms it first.
If 3 wins, the wallet entry gets a placeholder reference (CHK-...), and a late
callback from 2 replaces it with the real M-Pesa receipt.
"""

import hmac
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from contributions.models import WalletEntry
from contributions.services import record_payment
from core.models import PaymentSettings
from .daraja import DarajaError, stk_push, stk_query
from .models import MpesaTransaction

logger = logging.getLogger(__name__)

PENDING_LOCK = timedelta(minutes=2)     # one open prompt per member at a time
QUERY_AFTER = timedelta(seconds=30)     # wait this long for the callback first
QUERY_EVERY = timedelta(seconds=15)     # then ask Safaricom at most this often
GIVE_UP_AFTER = timedelta(minutes=5)    # after this, a silent prompt counts as timed out

Status = MpesaTransaction.Status

RESULT_STATUS = {
    0: Status.SUCCESS,
    1032: Status.CANCELLED,
    1037: Status.TIMEOUT,
    1019: Status.TIMEOUT,
}

FRIENDLY_MESSAGES = {
    0: "Payment received. Thank you.",
    1: "Your M-Pesa balance was too low for this payment.",
    1032: "You cancelled the payment on your phone.",
    1037: "Your phone could not be reached. Check that it is on and try again.",
    1019: "The prompt expired before you entered your PIN.",
    2001: "The M-Pesa PIN entered was wrong.",
}


class PaymentError(Exception):
    """A payment could not start. The message is safe to show the member."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def callback_url():
    base = settings.MPESA_CALLBACK_BASE_URL.rstrip("/")
    secret = settings.MPESA_CALLBACK_SECRET
    if not base or not secret:
        raise PaymentError("M-Pesa callback settings are missing.", status=503)
    return f"{base}/api/payments/mpesa/callback/{secret}/"


def secret_matches(given):
    expected = settings.MPESA_CALLBACK_SECRET or ""
    return bool(expected) and hmac.compare_digest(given or "", expected)


def status_message(tx):
    if tx.status == Status.PENDING:
        return "Check your phone and enter your M-Pesa PIN."
    if tx.result_code in FRIENDLY_MESSAGES:
        return FRIENDLY_MESSAGES[tx.result_code]
    if tx.status == Status.TIMEOUT:
        return "M-Pesa did not confirm the payment in time. If money left your account, contact the SACCO office."
    return tx.result_desc or "The payment did not go through."


def placeholder_reference(checkout_request_id):
    """The wallet reference used when a payment is confirmed before its receipt arrives."""
    return f"CHK-{checkout_request_id}"


# ---------------------------------------------------------------------------
# 1. Starting a payment
# ---------------------------------------------------------------------------

def initiate_payment(member, amount, phone_number):
    payment_settings = PaymentSettings.objects.first()
    if payment_settings is None:
        raise PaymentError("M-Pesa payments are not set up yet. Contact the SACCO office.", status=503)

    open_prompt = MpesaTransaction.objects.filter(
        member=member,
        status=Status.PENDING,
        created_at__gte=timezone.now() - PENDING_LOCK,
    ).exists()
    if open_prompt:
        raise PaymentError(
            "A payment is already waiting for your PIN. Complete it, or try again in two minutes.",
            status=409,
        )

    url = callback_url()
    tx = MpesaTransaction.objects.create(
        member=member,
        phone_number=phone_number,
        amount=Decimal(amount),
    )

    try:
        data = stk_push(payment_settings, phone_number, amount, url)
    except DarajaError as exc:
        tx.status = Status.FAILED
        tx.result_desc = str(exc)[:255]
        tx.save(update_fields=["status", "result_desc", "updated_at"])
        logger.warning("STK push failed for tx %s: %s %s", tx.pk, exc, exc.details)
        raise PaymentError(f"M-Pesa could not send the prompt: {exc}", status=502)

    tx.merchant_request_id = data.get("MerchantRequestID", "")
    tx.checkout_request_id = data.get("CheckoutRequestID")
    tx.save(update_fields=["merchant_request_id", "checkout_request_id", "updated_at"])
    logger.info("STK push sent: tx %s, member %s, KES %s", tx.pk, member.username, amount)
    return tx, data.get("CustomerMessage", "")


# ---------------------------------------------------------------------------
# Crediting (shared by the callback and the status query)
# ---------------------------------------------------------------------------

def _credit_once(tx, amount, receipt, completed_at):
    """Credits the wallet unless this transaction already did. Caller holds a lock on tx."""
    if tx.credited:
        return
    reference = receipt or placeholder_reference(tx.checkout_request_id)
    record_payment(
        tx.member,
        amount,
        reference=reference,
        effective_at=completed_at or timezone.now(),
        description=f"M-Pesa payment from +{tx.phone_number}",
    )
    tx.credited = True


def _attach_receipt(tx, receipt, completed_at):
    """
    Puts the real receipt, and Safaricom's completion time, on a wallet
    entry that a status check credited earlier with a placeholder.
    """
    if not receipt:
        return
    updates = {"reference": receipt}
    if completed_at:
        updates["effective_at"] = completed_at
    changed = WalletEntry.objects.filter(
        reference=placeholder_reference(tx.checkout_request_id),
    ).update(**updates)
    if changed:
        logger.info("Late receipt %s attached to tx %s", receipt, tx.pk)


def _parse_metadata(items):
    return {item.get("Name"): item.get("Value") for item in (items or [])}


def _parse_mpesa_date(value):
    try:
        return timezone.make_aware(datetime.strptime(str(int(value)), "%Y%m%d%H%M%S"))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 2. Safaricom's callback
# ---------------------------------------------------------------------------

def handle_callback(payload):
    callback = (payload or {}).get("Body", {}).get("stkCallback", {})
    checkout_id = callback.get("CheckoutRequestID")
    if not checkout_id:
        logger.warning("Callback without CheckoutRequestID: %s", payload)
        return False

    with transaction.atomic():
        tx = (
            MpesaTransaction.objects.select_for_update()
            .filter(checkout_request_id=checkout_id)
            .first()
        )
        if tx is None:
            logger.warning("Callback for unknown CheckoutRequestID %s", checkout_id)
            return False

        tx.raw_callback = payload
        code = int(callback.get("ResultCode", -1))
        tx.result_code = code
        tx.result_desc = (callback.get("ResultDesc") or "")[:255]

        if code == 0:
            meta = _parse_metadata(callback.get("CallbackMetadata", {}).get("Item"))
            amount = Decimal(str(meta.get("Amount", tx.amount)))
            receipt = str(meta.get("MpesaReceiptNumber", "") or "")
            completed_at = _parse_mpesa_date(meta.get("TransactionDate"))

            tx.mpesa_receipt = receipt or tx.mpesa_receipt
            tx.transaction_date = completed_at or tx.transaction_date
            tx.status = Status.SUCCESS

            already_credited = tx.credited
            _credit_once(tx, amount, receipt, completed_at)
            if already_credited:
                _attach_receipt(tx, receipt, completed_at)
        elif tx.status != Status.SUCCESS:
            tx.status = RESULT_STATUS.get(code, Status.FAILED)

        tx.save()

    logger.info("Callback processed: tx %s -> %s (code %s)", tx.pk, tx.status, code)
    return True


# ---------------------------------------------------------------------------
# 3. Checking a late result
# ---------------------------------------------------------------------------

def refresh_status(tx):
    """
    Called while the member's page waits. If the callback is late,
    asks Safaricom directly, at most every QUERY_EVERY seconds.
    """
    if tx.status != Status.PENDING or not tx.checkout_request_id:
        return tx

    now = timezone.now()
    age = now - tx.created_at
    if age < QUERY_AFTER:
        return tx
    if tx.last_queried_at and now - tx.last_queried_at < QUERY_EVERY:
        return tx

    data = {}
    payment_settings = PaymentSettings.objects.first()
    if payment_settings:
        try:
            _, data = stk_query(payment_settings, tx.checkout_request_id)
        except DarajaError as exc:
            logger.warning("STK query failed for tx %s: %s", tx.pk, exc)

    with transaction.atomic():
        tx = MpesaTransaction.objects.select_for_update().get(pk=tx.pk)
        if tx.status != Status.PENDING:
            return tx

        tx.last_queried_at = now
        raw_code = data.get("ResultCode")
        if raw_code is not None and str(raw_code).lstrip("-").isdigit():
            code = int(raw_code)
            tx.result_code = code
            tx.result_desc = (data.get("ResultDesc") or "")[:255]
            if code == 0:
                tx.status = Status.SUCCESS
                _credit_once(tx, tx.amount, "", now)
            else:
                tx.status = RESULT_STATUS.get(code, Status.FAILED)
        elif age > GIVE_UP_AFTER:
            tx.status = Status.TIMEOUT
            tx.result_desc = "No answer from M-Pesa."

        tx.save()
    return tx