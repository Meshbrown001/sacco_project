from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction

from .models import Sacco, PaymentSettings, ContributionSettings

User = get_user_model()


class StaffAccountSerializer(serializers.Serializer):
    """One staff login passed in during registration."""
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField(required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, validators=[validate_password])


class SaccoRegistrationSerializer(serializers.Serializer):
    """
    One-time setup. Creates, in a single transaction:
      - the Sacco
      - its PaymentSettings
      - its ContributionSettings (starting monthly amount)
      - three staff users (chairperson, secretary, treasurer)
    """
    # Sacco
    name = serializers.CharField(max_length=150)
    registration_number = serializers.CharField(max_length=50)

    # Payment settings
    business_shortcode = serializers.CharField(max_length=20)
    account_reference = serializers.CharField(max_length=50)
    display_label = serializers.CharField(max_length=100, required=False, default="SACCO M-Pesa")

    # Contribution amount
    monthly_amount = serializers.DecimalField(max_digits=10, decimal_places=2)

    # Staff
    chairperson = StaffAccountSerializer()
    secretary = StaffAccountSerializer()
    treasurer = StaffAccountSerializer()

    def validate(self, attrs):
        if Sacco.objects.exists():
            raise serializers.ValidationError(
                "A SACCO is already registered. Registration is closed."
            )

        # Usernames must be unique among the three staff and against existing users
        staff = [attrs["chairperson"], attrs["secretary"], attrs["treasurer"]]
        usernames = [s["username"] for s in staff]
        if len(usernames) != len(set(usernames)):
            raise serializers.ValidationError("The three staff usernames must be different.")
        taken = User.objects.filter(username__in=usernames).values_list("username", flat=True)
        if taken:
            raise serializers.ValidationError(f"Username already taken: {', '.join(taken)}")

        return attrs

    def _create_staff(self, data, role):
        user = User(
            username=data["username"],
            email=data.get("email", ""),
            role=role,
        )
        user.set_password(data["password"])
        user.save()
        return user

    @transaction.atomic
    def create(self, validated_data):
        sacco = Sacco.objects.create(
            name=validated_data["name"],
            registration_number=validated_data["registration_number"],
        )
        PaymentSettings.objects.create(
            business_shortcode=validated_data["business_shortcode"],
            account_reference=validated_data["account_reference"],
            display_label=validated_data.get("display_label", "SACCO M-Pesa"),
        )
        ContributionSettings.objects.create(
            monthly_amount=validated_data["monthly_amount"],
        )

        chairperson = self._create_staff(validated_data["chairperson"], User.Role.CHAIRPERSON)
        secretary = self._create_staff(validated_data["secretary"], User.Role.SECRETARY)
        treasurer = self._create_staff(validated_data["treasurer"], User.Role.TREASURER)

        return {
            "sacco": sacco,
            "staff_created": [chairperson.username, secretary.username, treasurer.username],
        }