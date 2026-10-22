from decimal import Decimal

from django.db import migrations


def backfill(apps, schema_editor):
    ContributionSettings = apps.get_model("core", "ContributionSettings")
    MonthlyContribution = apps.get_model("contributions", "MonthlyContribution")
    Penalty = apps.get_model("contributions", "Penalty")

    settings_row = ContributionSettings.objects.first()
    current_amount = settings_row.monthly_amount if settings_row else Decimal("0")

    # Paid months: the amount due was whatever the member paid in full.
    # Unpaid months: the best record available is today's amount.
    for row in MonthlyContribution.objects.filter(amount_due=0):
        if row.status == "paid" and row.amount_paid > 0:
            row.amount_due = row.amount_paid
        else:
            row.amount_due = current_amount
        row.save(update_fields=["amount_due"])

    # Existing penalties were charged at the old 10 percent rate.
    for penalty in Penalty.objects.all():
        penalty.rate = Decimal("10.00")
        if penalty.paid:
            penalty.amount_paid = penalty.amount
        penalty.save(update_fields=["rate", "amount_paid"])


def undo(apps, schema_editor):
    pass  # nothing to reverse; the fields drop away with the structure migration


class Migration(migrations.Migration):

    dependencies = [
        ("contributions", "0002_alter_penalty_options_monthlycontribution_amount_due_and_more"),
        ("core", "0002_contributionsettings_penalty_rate_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill, undo),
    ]