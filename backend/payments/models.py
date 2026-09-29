from django.conf import settings
from django.db import models


class MpesaTransaction(models.Model):
    """
    One M-Pesa Express (STK push) request and its outcome.

    The row is created before the prompt goes out, so a record exists
    even if Safaricom never answers. Money reaches the member's wallet
    only when Safaricom confirms success, and only once: `credited`
    guards against a callback and a status query both paying.

    levy_obligation records what the member chose to pay for: a special
    contribution, or, when empty, the monthly contributions.
    """
    class Status(models.TextChoices):
        PENDING = "pending", "Waiting for PIN"
        SUCCESS = "success", "Successful"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled by member"
        TIMEOUT = "timeout", "Timed out"

    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="mpesa_transactions",
    )
    levy_obligation = models.ForeignKey(
        "contributions.LevyObligation",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="mpesa_transactions",
        help_text="The special contribution this pays. Empty means monthly contributions.",
    )
    phone_number = models.CharField(max_length=12, help_text="Paying phone, 2547XXXXXXXX")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    merchant_request_id = models.CharField(max_length=100, blank=True)
    checkout_request_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    mpesa_receipt = models.CharField(max_length=30, blank=True)
    result_code = models.IntegerField(null=True, blank=True)
    result_desc = models.CharField(max_length=255, blank=True)
    transaction_date = models.DateTimeField(
        null=True, blank=True,
        help_text="When Safaricom completed the payment.",
    )
    credited = models.BooleanField(default=False)
    last_queried_at = models.DateTimeField(null=True, blank=True)
    raw_callback = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def paying_for(self):
        if self.levy_obligation_id and self.levy_obligation:
            return self.levy_obligation.levy.purpose
        return "Monthly contributions"

    def __str__(self):
        return f"{self.member.username} KES {self.amount} {self.status}"