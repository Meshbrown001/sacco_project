from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Sacco(models.Model):
    """
    The single registered SACCO. The save guard enforces the
    'register once' rule: only one Sacco row may ever exist.
    """
    name = models.CharField(max_length=150)
    registration_number = models.CharField(max_length=50, unique=True)
    date_registered = models.DateField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.pk and Sacco.objects.exists():
            raise ValidationError("A SACCO is already registered. Only one is allowed.")
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class PaymentSettings(models.Model):
    """
    M-Pesa payment details the chairperson can edit. The Daraja
    consumer key, consumer secret and passkey are NOT stored here;
    they live in the .env file. Only one row may exist.

    Paybill: business_shortcode is the paybill number.
    Till:    business_shortcode is the store (head office) number,
             and till_number is the till members pay into.
    """
    class ShortcodeType(models.TextChoices):
        PAYBILL = "paybill", "Paybill"
        TILL = "till", "Till (Buy Goods)"

    shortcode_type = models.CharField(
        max_length=10,
        choices=ShortcodeType.choices,
        default=ShortcodeType.PAYBILL,
    )
    business_shortcode = models.CharField(max_length=20)
    till_number = models.CharField(max_length=20, blank=True)
    account_reference = models.CharField(max_length=50)
    display_label = models.CharField(max_length=100, default="SACCO M-Pesa")

    def clean(self):
        if self.shortcode_type == self.ShortcodeType.TILL and not self.till_number:
            raise ValidationError({"till_number": "A till number is required for Buy Goods."})

    def save(self, *args, **kwargs):
        if not self.pk and PaymentSettings.objects.exists():
            raise ValidationError("Payment settings already exist. Only one is allowed.")
        super().save(*args, **kwargs)

    def __str__(self):
        return self.display_label


class ContributionSettings(models.Model):
    """
    The current monthly contribution amount and penalty rate, both set
    by the chairperson. Each month copies the amount into its own
    amount_due when it falls due, and each penalty freezes the rate
    when charged, so changes here affect only future months.
    Only one row may exist.
    """
    monthly_amount = models.DecimalField(max_digits=10, decimal_places=2)
    penalty_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("15.00"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
        help_text="Late penalty as a percentage of the monthly amount, e.g. 15.00",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.pk and ContributionSettings.objects.exists():
            raise ValidationError("Contribution settings already exist. Only one is allowed.")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Monthly contribution: {self.monthly_amount}, penalty {self.penalty_rate}%"