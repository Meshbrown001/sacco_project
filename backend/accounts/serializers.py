import re

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


def normalize_kenyan_phone(raw):
    """
    Converts common Kenyan phone formats to 2547XXXXXXXX or 2541XXXXXXXX,
    the format M-Pesa STK Push requires.
    Accepts 0712345678, 712345678, +254712345678 and 254712345678.
    """
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("254"):
        digits = digits[3:]
    elif digits.startswith("0"):
        digits = digits[1:]
    if not re.fullmatch(r"[17]\d{8}", digits):
        raise serializers.ValidationError(
            "Enter a valid Kenyan phone number, for example 0712345678."
        )
    return "254" + digits


class MemberRegistrationSerializer(serializers.ModelSerializer):
    """
    Used for members registering themselves.
    Role is forced to 'member' regardless of what's sent in,
    so nobody can self-register as staff.
    """
    password = serializers.CharField(write_only=True, style={"input_type": "password"})
    password2 = serializers.CharField(write_only=True, style={"input_type": "password"})

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name',
            'phone_number', 'national_id', 'phone_verified',
            'password', 'password2',
        ]
        extra_kwargs = {
            'email': {'required': True, 'allow_blank': False},
            'first_name': {'required': True, 'allow_blank': False},
            'last_name': {'required': True, 'allow_blank': False},
            'phone_verified': {'read_only': True},
        }

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A member with this email already exists.")
        return value

    def validate_phone_number(self, value):
        normalized = normalize_kenyan_phone(value)
        if User.objects.filter(phone_number=normalized).exists():
            raise serializers.ValidationError("A member with this phone number already exists.")
        return normalized

    def validate_national_id(self, value):
        value = value.strip()
        if not re.fullmatch(r"\d{7,8}", value):
            raise serializers.ValidationError("National ID must contain 7 or 8 digits.")
        if User.objects.filter(national_id=value).exists():
            raise serializers.ValidationError("A member with this national ID already exists.")
        return value

    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({"password2": "Passwords do not match."})

        # Build an unsaved user so Django can compare the password
        # against the username, email and names.
        candidate = User(
            username=attrs.get('username'),
            email=attrs.get('email'),
            first_name=attrs.get('first_name'),
            last_name=attrs.get('last_name'),
        )
        try:
            validate_password(attrs['password'], user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)})
        return attrs

    def create(self, validated_data):
        validated_data.pop('password2')
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.role = User.Role.MEMBER  # force role, ignore any client input
        user.set_password(password)
        user.save()
        return user


class UserSerializer(serializers.ModelSerializer):
    """
    Safe representation of a user, returned after login or when
    fetching profile info. Never exposes password.
    """
    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name',
            'phone_number', 'national_id', 'role', 'date_joined_sacco',
            'phone_verified',
        ]
        read_only_fields = fields


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Extends the default JWT login serializer to include the user's
    role and basic info directly in the login response, so the
    frontend can redirect to the correct dashboard immediately.
    """
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['role'] = user.role
        token['username'] = user.username
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data['role'] = self.user.role
        data['username'] = self.user.username
        data['user_id'] = self.user.id
        data['phone_verified'] = self.user.phone_verified
        return data


class OTPCodeSerializer(serializers.Serializer):
    """Validates a 6-digit SMS code. Used by phone verification."""
    code = serializers.RegexField(
        r"^\d{6}$",
        error_messages={"invalid": "Enter the 6-digit code."},
    )


# ---------------------------------------------------------------------------
# Forgot password
# The user never supplies a phone number or email here: the code goes only
# to a contact already registered on the account.
# ---------------------------------------------------------------------------

class PasswordResetStartSerializer(serializers.Serializer):
    """Step 1: the username of the account to reset."""
    username = serializers.CharField()


class PasswordResetSendSerializer(serializers.Serializer):
    """Step 2: which registered contact receives the code."""
    username = serializers.CharField()
    channel = serializers.ChoiceField(
        choices=["sms", "email"],
        error_messages={"invalid_choice": "Choose SMS or email."},
    )


class PasswordResetVerifySerializer(serializers.Serializer):
    """Step 3: the 6-digit code the user received."""
    username = serializers.CharField()
    code = serializers.RegexField(
        r"^\d{6}$",
        error_messages={"invalid": "Enter the 6-digit code."},
    )


class PasswordResetCompleteSerializer(serializers.Serializer):
    """Step 4: the new password, typed twice."""
    username = serializers.CharField()
    reset_token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, style={"input_type": "password"})
    new_password2 = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate(self, attrs):
        if attrs["new_password"] != attrs["new_password2"]:
            raise serializers.ValidationError({"new_password2": "Passwords do not match."})
        return attrs