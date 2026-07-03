
# Create your models here.
from django.contrib.auth.models import AbstractUser
from django.db import models


class CustomUser(AbstractUser):
    """
    Custom user model for the SACCO system.
    Extends Django's built-in user with a role field that determines
    what each user can access: regular member, secretary, treasurer,
    or chairperson.
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
    national_id = models.CharField(max_length=20, unique=True, null=True, blank=True)
    date_joined_sacco = models.DateField(auto_now_add=True)

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