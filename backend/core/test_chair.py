"""
Tests for the chairperson's actions. They run in a temporary test database.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import AccountDeactivation, CustomUser
from contributions.models import LevyObligation, MonthlyContribution, SpecialLevy
from contributions.services import ensure_months, record_payment
from core.chair_services import ChairError, deactivate_account, reactivate_account
from core.models import ContributionSettings


class ChairTests(TestCase):

    def setUp(self):
        ContributionSettings.objects.create(monthly_amount=Decimal("1000"))
        self.chair = CustomUser.objects.create_user(
            username="chair1", password="Mwenyekiti#2026", role=CustomUser.Role.CHAIRPERSON,
        )
        self.member = CustomUser.objects.create_user(
            username="mem1", password="Mwanachama#2026", role=CustomUser.Role.MEMBER,
            phone_number="254700000021", national_id="12121212",
        )
        CustomUser.objects.filter(pk=self.member.pk).update(date_joined_sacco=date(2026, 7, 3))
        self.member.refresh_from_db()

        self.client = APIClient()
        self.client.force_authenticate(self.chair)

    # ----- Access --------------------------------------------------------

    def test_only_chairperson_may_use_these_pages(self):
        other = APIClient()
        other.force_authenticate(self.member)
        self.assertEqual(other.get("/api/chair/accounts/").status_code, 403)

    # ----- Staff accounts ------------------------------------------------

    def test_create_staff_account_with_fixed_role(self):
        r = self.client.post("/api/chair/accounts/staff/", {
            "first_name": "Mary", "last_name": "Atieno", "username": "sec2",
            "role": "secretary", "password": "Katibu#Mpya2026", "password2": "Katibu#Mpya2026",
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(CustomUser.objects.get(username="sec2").role, "secretary")

    def test_cannot_create_member_through_staff_form(self):
        r = self.client.post("/api/chair/accounts/staff/", {
            "first_name": "Sam", "last_name": "Otieno", "username": "sam2",
            "role": "member", "password": "Katibu#Mpya2026", "password2": "Katibu#Mpya2026",
        }, format="json")
        self.assertEqual(r.status_code, 400)

    # ----- Deactivation rules ---------------------------------------------

    def test_chairperson_cannot_deactivate_self(self):
        r = self.client.post(f"/api/chair/accounts/{self.chair.pk}/deactivate/",
                             {"reason": "Testing self"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_reason_is_required(self):
        r = self.client.post(f"/api/chair/accounts/{self.member.pk}/deactivate/",
                             {"reason": ""}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_last_chairperson_is_protected(self):
        with self.assertRaises(ChairError):
            deactivate_account(self.member, self.chair, "Trying to remove the only chair")

    def test_deactivation_is_recorded(self):
        r = self.client.post(f"/api/chair/accounts/{self.member.pk}/deactivate/",
                             {"reason": "Missed three meetings"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.member.refresh_from_db()
        self.assertFalse(self.member.is_active)
        self.assertEqual(self.member.deactivated_by, self.chair)
        self.assertEqual(AccountDeactivation.objects.get(user=self.member).reason, "Missed three meetings")

    # ----- Reactivation skips the months away -------------------------------

    def test_reactivated_member_owes_nothing_for_months_away(self):
        deactivate_account(self.chair, self.member, "Suspended", today=date(2026, 8, 15))
        reactivate_account(self.chair, self.member, today=date(2026, 11, 10))
        self.member.refresh_from_db()

        ensure_months(self.member, today=date(2026, 11, 10))
        months = set(MonthlyContribution.objects.filter(member=self.member).values_list("month", flat=True))
        self.assertEqual(months, {date(2026, 7, 1), date(2026, 8, 1), date(2026, 11, 1)})

    # ----- Monthly settings -------------------------------------------------

    def test_settings_update(self):
        r = self.client.put("/api/chair/settings/",
                            {"monthly_amount": "1500", "penalty_rate": "20"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        row = ContributionSettings.objects.first()
        self.assertEqual(row.monthly_amount, Decimal("1500"))
        self.assertEqual(row.penalty_rate, Decimal("20"))

    def test_settings_change_leaves_current_month_alone(self):
        ensure_months(self.member)
        current = MonthlyContribution.objects.filter(member=self.member).order_by("-month").first()
        self.client.put("/api/chair/settings/",
                        {"monthly_amount": "1500", "penalty_rate": "15"}, format="json")
        current.refresh_from_db()
        self.assertEqual(current.amount_due, Decimal("1000.00"))

    # ----- Special contributions ---------------------------------------------

    def new_levy(self):
        deadline = (timezone.localdate() + timedelta(days=30)).isoformat()
        r = self.client.post("/api/chair/levies/", {
            "purpose": "Annual trip", "amount": "2000", "deadline": deadline,
            "fine_type": "percent", "fine_value": "10",
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return SpecialLevy.objects.get(pk=r.json()["id"])

    def test_creating_levy_gives_members_obligations(self):
        levy = self.new_levy()
        self.assertEqual(levy.obligations.count(), 1)

    def test_levy_without_payments_can_be_cancelled(self):
        levy = self.new_levy()
        r = self.client.post(f"/api/chair/levies/{levy.pk}/cancel/")
        self.assertEqual(r.status_code, 200)
        levy.refresh_from_db()
        self.assertEqual(levy.status, "cancelled")
        self.assertEqual(levy.obligations.count(), 0)

    def test_levy_with_payments_can_only_be_closed(self):
        levy = self.new_levy()
        record_payment(self.member, 500, levy_obligation=LevyObligation.objects.get(levy=levy))

        self.assertEqual(self.client.patch(f"/api/chair/levies/{levy.pk}/",
                                           {"amount": "2500"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(f"/api/chair/levies/{levy.pk}/cancel/").status_code, 400)
        self.assertEqual(self.client.post(f"/api/chair/levies/{levy.pk}/close/").status_code, 200)