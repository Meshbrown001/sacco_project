from django.db import models
from django.core.exceptions import ValidationError


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
    M-Pesa payment details the chairperson can edit. The secret
    Daraja passkey is NOT stored here; it lives in the .env file.
    Only one row may exist.
    """
    business_shortcode = models.CharField(max_length=20)
    account_reference = models.CharField(max_length=50)
    display_label = models.CharField(max_length=100, default="SACCO M-Pesa")

    def save(self, *args, **kwargs):
        if not self.pk and PaymentSettings.objects.exists():
            raise ValidationError("Payment settings already exist. Only one is allowed.")
        super().save(*args, **kwargs)

    def __str__(self):
        return self.display_label


class ContributionSettings(models.Model):
    """
    The single current monthly contribution amount. Every month
    reads from this value; the chairperson resets it. Only one
    row may exist.
    """
    monthly_amount = models.DecimalField(max_digits=10, decimal_places=2)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.pk and ContributionSettings.objects.exists():
            raise ValidationError("Contribution settings already exist. Only one is allowed.")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Monthly contribution: {self.monthly_amount}"