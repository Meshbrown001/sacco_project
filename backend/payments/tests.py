"""
Tests for the payments app. They run in a temporary test database,
never touch real records, and never contact Safaricom: the status query
is replaced by a stand-in that answers "success".
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from accounts.models import CustomUser
from contributions.models import LevyObligation, SpecialLevy, WalletEntry
from contributions.services import create_levy_obligations
from core.models import ContributionSettings, PaymentSettings
from payments.models import MpesaTransaction
from payments.services import handle_callback, refresh_status

CHECKOUT_ID = "ws_CO_TEST_LATE"
QUERY_SUCCESS = (200, {"ResultCode": "0", "ResultDesc": "The service request is processed successfully."})


def success_callback(receipt="TEST123ABC", completed="20260926100005"):
    """The message Safaricom sends when a payment succeeds."""
    return {
        "Body": {
            "stkCallback": {
                "MerchantRequestID": "test-merchant",
                "CheckoutRequestID": CHECKOUT_ID,
                "ResultCode": 0,
                "ResultDesc": "The service request is processed successfully.",
                "CallbackMetadata": {
                    "Item": [
                        {"Name": "Amount", "Value": 1.0},
                        {"Name": "MpesaReceiptNumber", "Value": receipt},
                        {"Name": "TransactionDate", "Value": int(completed)},
                        {"Name": "PhoneNumber", "Value": 254700000001},
                    ]
                },
            }
        }
    }


class LateReceiptTests(TestCase):

    def setUp(self):
        ContributionSettings.objects.create(monthly_amount=Decimal("1000"))
        PaymentSettings.objects.create(business_shortcode="174379", account_reference="Test")
        self.member = CustomUser.objects.create_user(
            username="late_member",
            password="Test#Pass2026",
            role=CustomUser.Role.MEMBER,
            phone_number="254700000001",
            national_id="99999991",
        )
        self.tx = MpesaTransaction.objects.create(
            member=self.member,
            phone_number="254700000001",
            amount=Decimal("1"),
            checkout_request_id=CHECKOUT_ID,
        )
        # Pretend the prompt went out a minute ago, so the status check may run.
        MpesaTransaction.objects.filter(pk=self.tx.pk).update(
            created_at=timezone.now() - timedelta(minutes=1)
        )
        self.tx.refresh_from_db()

    def credits(self):
        return WalletEntry.objects.filter(
            wallet__member=self.member,
            entry_type=WalletEntry.EntryType.CREDIT,
        )

    @patch("payments.services.stk_query", return_value=QUERY_SUCCESS)
    def test_late_callback_replaces_placeholder(self, _query):
        # The status check confirms first, with no receipt.
        refresh_status(self.tx)
        self.tx.refresh_from_db()
        self.assertTrue(self.tx.credited)
        self.assertTrue(self.credits().get().reference.startswith("CHK-"))

        # Then the callback arrives late, carrying the receipt.
        handle_callback(success_callback())

        entry = self.credits().get()
        self.assertEqual(entry.reference, "TEST123ABC")
        self.assertEqual(timezone.localtime(entry.effective_at).strftime("%Y%m%d%H%M%S"), "20260926100005")
        self.assertEqual(self.credits().count(), 1, "The wallet must be credited only once.")

    def test_callback_first_uses_receipt_directly(self):
        handle_callback(success_callback())
        self.assertEqual(self.credits().get().reference, "TEST123ABC")

    def test_repeated_callback_does_not_double_credit(self):
        handle_callback(success_callback())
        handle_callback(success_callback())
        self.assertEqual(self.credits().count(), 1)


class TargetedPaymentTests(TestCase):
    """A payment for a special contribution reaches that contribution."""

    def setUp(self):
        ContributionSettings.objects.create(monthly_amount=Decimal("1000"))
        self.member = CustomUser.objects.create_user(
            username="levy_member",
            password="Test#Pass2026",
            role=CustomUser.Role.MEMBER,
            phone_number="254700000031",
            national_id="31313131",
        )
        levy = SpecialLevy.objects.create(
            purpose="Annual trip",
            amount=Decimal("2000"),
            deadline=timezone.localdate() + timedelta(days=30),
        )
        create_levy_obligations(levy)
        self.obligation = LevyObligation.objects.get(levy=levy, member=self.member)
        MpesaTransaction.objects.create(
            member=self.member,
            levy_obligation=self.obligation,
            phone_number="254700000031",
            amount=Decimal("1"),
            checkout_request_id=CHECKOUT_ID,
        )

    def test_callback_pays_the_chosen_special_contribution(self):
        handle_callback(success_callback())
        self.obligation.refresh_from_db()
        self.assertEqual(self.obligation.amount_paid, Decimal("1.00"))