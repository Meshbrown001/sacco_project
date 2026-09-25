from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings

from .models import MemberWallet


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_wallet_for_member(sender, instance, created, **kwargs):
    """
    Build a wallet the moment a member account is created.
    Only members get wallets. Staff (chairperson, secretary,
    treasurer) do not contribute, so they need no wallet.
    """
    if created and instance.role == instance.Role.MEMBER:
        MemberWallet.objects.create(member=instance)