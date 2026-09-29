from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class CustomUser(AbstractUser):
    """
    Custom user model for the SACCO system.
    Extends Django's built-in user with a role field that determines
    what each user can access: regular member, secretary, treasurer,
    or chairperson.

    Officials hold two accounts: a staff account for their official
    page, and a member account for paying contributions like everyone
    else. A staff account's role is set when it is created and never
    changes; ending a term means deactivating the staff account.
    """

    class Role(models.TextChoices):
        MEMBER = 'member', 'Member'
        SECRETARY = 'secretary', 'Secretary'
        TREASURER = 'treasurer', 'Treasurer'
        CHAIRPERSON = 'chairperson', 'Chairperson'

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.MEMBER,
    )

    # Extra fields useful for a SACCO member
    phone_number = models.CharField(max_length=15, unique=True, null=True, blank=True)
    phone_verified = models.BooleanField(default=False)
    national_id = models.CharField(max_length=20, unique=True, null=True, blank=True)
    date_joined_sacco = models.DateField(auto_now_add=True)

    # The current deactivation, if any. is_active, inherited from Django,
    # controls login. The full history lives in AccountDeactivation.
    deactivated_at = models.DateTimeField(null=True, blank=True)
    deactivation_reason = models.CharField(max_length=255, blank=True)
    deactivated_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='+',
    )

    def is_member(self):
        return self.role == self.Role.MEMBER

    def is_secretary(self):
        return self.role == self.Role.SECRETARY

    def is_treasurer(self):
        return self.role == self.Role.TREASURER

    def is_chairperson(self):
        return self.role == self.Role.CHAIRPERSON

    def is_staff_role(self):
        return self.role in [self.Role.SECRETARY, self.Role.TREASURER, self.Role.CHAIRPERSON]

    def __str__(self):
        return f"{self.username} ({self.role})"


class OTPCode(models.Model):
    """
    One-time codes sent by SMS or email. The same table serves phone
    verification and password reset, told apart by `purpose`.
    Only a hash of each code is stored.
    """

    class Purpose(models.TextChoices):
        PHONE_VERIFICATION = 'phone_verification', 'Phone verification'
        PASSWORD_RESET = 'password_reset', 'Password reset'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='otp_codes',
    )
    purpose = models.CharField(max_length=30, choices=Purpose.choices)
    code_hash = models.CharField(max_length=255)
    attempts = models.PositiveSmallIntegerField(default=0)
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', 'purpose', 'is_used'])]

    def __str__(self):
        return f"{self.get_purpose_display()} code for {self.user}"


class AccountDeactivation(models.Model):
    """
    One period during which an account was deactivated, kept for good.
    ended_on stays empty while the account is still deactivated.

    For a member, the months strictly after the deactivation month and
    strictly before the reactivation month are skipped: no contribution
    is owed for them, and no fine charged.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='deactivations',
    )
    started_on = models.DateField()
    ended_on = models.DateField(null=True, blank=True)
    reason = models.CharField(max_length=255)
    deactivated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='+',
    )
    reactivated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-started_on', '-id']

    def __str__(self):
        end = self.ended_on or "still deactivated"
        return f"{self.user.username}: {self.started_on} to {end}"