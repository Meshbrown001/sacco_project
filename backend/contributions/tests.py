"""
Tests for special contributions (levies). They run in a temporary test
database and never touch real records or M-Pesa.
"""

from datetime import date, datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from accounts.models import CustomUser
from contributions.models import LevyObligation, MemberWallet, SpecialLevy
from contributions.services import (
    charge_levy_fines,
    create_levy_obligations,
    ensure_levy_obligations,
    record_payment,
)
from core.models import ContributionSettings

OCT_10 = date(2026, 10, 10)     # before the deadline
NOV_1 = date(2026, 11, 1)       # the day after the deadline


def aware(year, month, day, hour=12, minute=0):
    return timezone.make_aware(datetime(year, month, day, hour, minute))


class LevyTests(TestCase):

    def setUp(self):
        ContributionSettings.objects.create(monthly_amount=Decimal("1000"))
        self.alice = self.make_member("alice", "254700000011", "11111111", date(2026, 9, 1))
        self.bob = self.make_member("bob", "254700000012", "22222222", date(2026, 9, 1))
        self.levy = SpecialLevy.objects.create(
            purpose="Annual trip",
            amount=Decimal("2000"),
            deadline=date(2026, 10, 31),
            fine_type=SpecialLevy.FineType.PERCENT,
            fine_value=Decimal("10"),
        )

    def make_member(self, username, phone, national_id, joined, active=True):
        user = CustomUser.objects.create_user(
            username=username,
            password="Test#Pass2026",
            role=CustomUser.Role.MEMBER,
            phone_number=phone,
            national_id=national_id,
            is_active=active,
        )
        CustomUser.objects.filter(pk=user.pk).update(date_joined_sacco=joined)
        user.refresh_from_db()
        return user

    def obligation(self, member):
        return LevyObligation.objects.get(levy=self.levy, member=member)

    # ----- Who owes it ---------------------------------------------------

    def test_active_members_owe_it_inactive_do_not(self):
        self.make_member("carol", "254700000013", "33333333", date(2026, 9, 1), active=False)
        created = create_levy_obligations(self.levy, today=OCT_10)
        self.assertEqual(created, 2)
        self.assertFalse(LevyObligation.objects.filter(member__username="carol").exists())

    def test_member_joining_before_deadline_owes_it(self):
        dave = self.make_member("dave", "254700000014", "44444444", date(2026, 10, 20))
        self.assertEqual(ensure_levy_obligations(dave, today=date(2026, 10, 20)), 1)

    def test_member_joining_after_deadline_does_not(self):
        erin = self.make_member("erin", "254700000015", "55555555", date(2026, 11, 2))
        self.assertEqual(ensure_levy_obligations(erin, today=date(2026, 11, 2)), 0)

    # ----- Fines ---------------------------------------------------------

    def test_percentage_fine_after_deadline(self):
        create_levy_obligations(self.levy, today=OCT_10)
        charged, _ = charge_levy_fines(self.alice, today=NOV_1)
        ob = self.obligation(self.alice)
        self.assertEqual(charged, 1)
        self.assertEqual(ob.fine_amount, Decimal("200.00"))
        self.assertEqual(ob.status, LevyObligation.Status.OVERDUE)

    def test_fixed_fine_after_deadline(self):
        self.levy.fine_type = SpecialLevy.FineType.FIXED
        self.levy.fine_value = Decimal("150")
        self.levy.save()
        create_levy_obligations(self.levy, today=OCT_10)
        charge_levy_fines(self.alice, today=NOV_1)
        self.assertEqual(self.obligation(self.alice).fine_amount, Decimal("150.00"))

    def test_no_fine_before_deadline_or_when_paid(self):
        create_levy_obligations(self.levy, today=OCT_10)
        charged, _ = charge_levy_fines(self.alice, today=OCT_10)
        self.assertEqual(charged, 0)

        record_payment(self.bob, 2000, effective_at=aware(2026, 10, 15),
                       today=date(2026, 10, 15), levy_obligation=self.obligation(self.bob))
        charged, _ = charge_levy_fines(self.bob, today=NOV_1)
        self.assertEqual(charged, 0)
        self.assertEqual(self.obligation(self.bob).status, LevyObligation.Status.PAID)

    def test_fine_charged_only_once(self):
        create_levy_obligations(self.levy, today=OCT_10)
        charge_levy_fines(self.alice, today=NOV_1)
        charged, _ = charge_levy_fines(self.alice, today=date(2026, 11, 2))
        self.assertEqual(charged, 0)

    # ----- Paying it -----------------------------------------------------

    def test_late_payment_pays_fine_first(self):
        create_levy_obligations(self.levy, today=OCT_10)
        charge_levy_fines(self.alice, today=NOV_1)

        record_payment(self.alice, 1000, effective_at=aware(2026, 11, 1),
                       today=NOV_1, levy_obligation=self.obligation(self.alice))

        ob = self.obligation(self.alice)
        self.assertEqual(ob.fine_amount_paid, Decimal("200.00"))
        self.assertEqual(ob.amount_paid, Decimal("800.00"))
        self.assertEqual(ob.balance, Decimal("1200.00"))

    def test_payment_completed_before_deadline_cancels_fine(self):
        create_levy_obligations(self.levy, today=OCT_10)
        charge_levy_fines(self.alice, today=NOV_1)

        record_payment(self.alice, 2000, effective_at=aware(2026, 10, 31, 23, 58),
                       today=NOV_1, levy_obligation=self.obligation(self.alice))

        ob = self.obligation(self.alice)
        self.assertTrue(ob.fine_waived)
        self.assertEqual(ob.status, LevyObligation.Status.PAID)
        self.assertEqual(ob.fine_balance, Decimal("0"))

    def test_leftover_goes_to_monthly_debts(self):
        create_levy_obligations(self.levy, today=OCT_10)

        result = record_payment(self.alice, 2500, effective_at=aware(2026, 10, 10),
                                today=OCT_10, levy_obligation=self.obligation(self.alice))

        self.assertEqual(self.obligation(self.alice).status, LevyObligation.Status.PAID)
        monthly = [a for a in result["allocations"] if a["type"] == "contribution"]
        self.assertEqual(sum(a["amount"] for a in monthly), Decimal("500.00"))
        self.assertEqual(MemberWallet.objects.get(member=self.alice).balance, Decimal("0.00"))