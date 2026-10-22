from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from core.models import ContributionSettings
from contributions.services import money, send_arrears_prompts
from payments.models import MpesaTransaction

User = get_user_model()
SYSTEM = MpesaTransaction.InitiatedBy.SYSTEM
TODAY = date(2026, 6, 15)


def nairobi(hour):
    """An aware datetime at the given hour on TODAY, Nairobi time."""
    return timezone.make_aware(datetime(2026, 6, 15, hour, 0))


class ArrearsPromptTests(TestCase):
    def setUp(self):
        ContributionSettings.objects.create(
            monthly_amount=Decimal("500"),
            penalty_rate=Decimal("15"),
            auto_prompt_enabled=True,
            auto_prompt_threshold=Decimal("2000"),
            auto_prompt_max_per_day=5,
        )

    def make_member(self, username, joined, phone="254700000001"):
        return User.objects.create_user(
            username=username, password="Pw123456!x",
            role=User.Role.MEMBER, date_joined_sacco=joined, phone_number=phone,
        )

    def add_system_tx(self, member, hour, result_code=None):
        tx = MpesaTransaction.objects.create(
            member=member, phone_number=member.phone_number,
            amount=Decimal("100"), initiated_by=SYSTEM, result_code=result_code,
        )
        MpesaTransaction.objects.filter(pk=tx.pk).update(created_at=nairobi(hour))
        return tx

    @patch("contributions.services.timezone.now", return_value=nairobi(10))
    @patch("payments.services.initiate_payment", return_value=(None, ""))
    def test_in_arrears_prompted_for_full_debt(self, mock_init, _now):
        member = self.make_member("ar1", date(2026, 1, 1))  # Jan..Jun = 6 x 500 = 3000
        result = send_arrears_prompts(today=TODAY)
        self.assertEqual(result["prompts_sent"], 1)
        args, kwargs = mock_init.call_args
        self.assertEqual(args[0], member)
        self.assertEqual(args[1], money(Decimal("3000")))
        self.assertEqual(kwargs["initiated_by"], SYSTEM)

    @patch("contributions.services.timezone.now", return_value=nairobi(10))
    @patch("payments.services.initiate_payment", return_value=(None, ""))
    def test_below_threshold_not_prompted(self, mock_init, _now):
        self.make_member("ar2", date(2026, 5, 1))  # May..Jun = 1000 < 2000
        result = send_arrears_prompts(today=TODAY)
        self.assertEqual(result["prompts_sent"], 0)
        mock_init.assert_not_called()

    @patch("contributions.services.timezone.now", return_value=nairobi(10))
    @patch("payments.services.initiate_payment", return_value=(None, ""))
    def test_disabled_sends_nothing(self, mock_init, _now):
        ContributionSettings.objects.update(auto_prompt_enabled=False)
        self.make_member("ar3", date(2026, 1, 1))
        result = send_arrears_prompts(today=TODAY)
        self.assertIn("skipped", result)
        mock_init.assert_not_called()

    @patch("contributions.services.timezone.now", return_value=nairobi(3))  # 3am Nairobi
    @patch("payments.services.initiate_payment", return_value=(None, ""))
    def test_outside_quiet_hours_sends_nothing(self, mock_init, _now):
        self.make_member("ar4", date(2026, 1, 1))
        result = send_arrears_prompts(today=TODAY)
        self.assertIn("skipped", result)
        mock_init.assert_not_called()

    @patch("contributions.services.timezone.now", return_value=nairobi(3))
    @patch("payments.services.initiate_payment", return_value=(None, ""))
    def test_force_ignores_quiet_hours(self, mock_init, _now):
        self.make_member("ar4b", date(2026, 1, 1))
        result = send_arrears_prompts(today=TODAY, force=True)
        self.assertEqual(result["prompts_sent"], 1)

    @patch("contributions.services.timezone.now", return_value=nairobi(10))
    @patch("payments.services.initiate_payment", return_value=(None, ""))
    def test_daily_cap_stops_more_prompts(self, mock_init, _now):
        member = self.make_member("ar5", date(2026, 1, 1))
        for h in range(5):            # the cap is 5, and 5 already went today
            self.add_system_tx(member, hour=1 + h)
        result = send_arrears_prompts(today=TODAY)
        self.assertEqual(result["prompts_sent"], 0)
        mock_init.assert_not_called()

    @patch("contributions.services.timezone.now", return_value=nairobi(10))
    @patch("payments.services.initiate_payment", return_value=(None, ""))
    def test_four_hour_gap_blocks_a_close_prompt(self, mock_init, _now):
        member = self.make_member("ar6", date(2026, 1, 1))
        self.add_system_tx(member, hour=9)   # one hour ago, inside the gap
        result = send_arrears_prompts(today=TODAY)
        self.assertEqual(result["prompts_sent"], 0)
        mock_init.assert_not_called()

    @patch("contributions.services.timezone.now", return_value=nairobi(10))
    @patch("payments.services.initiate_payment", return_value=(None, ""))
    def test_half_debt_after_insufficient_funds(self, mock_init, _now):
        member = self.make_member("ar7", date(2026, 1, 1))     # debt 3000
        self.add_system_tx(member, hour=5, result_code=1)      # earlier, no money
        send_arrears_prompts(today=TODAY)
        args, kwargs = mock_init.call_args
        self.assertEqual(args[1], money(Decimal("1500")))      # half of 3000