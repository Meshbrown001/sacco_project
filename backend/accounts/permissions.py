from rest_framework import permissions


class IsSecretary(permissions.BasePermission):
    """Allows access only to users with the secretary role."""
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == request.user.Role.SECRETARY
        )


class IsTreasurer(permissions.BasePermission):
    """Allows access only to users with the treasurer role."""
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == request.user.Role.TREASURER
        )


class IsChairperson(permissions.BasePermission):
    """Allows access only to users with the chairperson role."""
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == request.user.Role.CHAIRPERSON
        )


class IsPhoneVerified(permissions.BasePermission):
    """
    Blocks members who have not verified their phone number.
    Staff roles and superusers pass through.
    Combine it with a role check, for example:
        permission_classes = [IsAuthenticated, IsPhoneVerified]
    """
    message = "Verify your phone number to continue."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_superuser or user.is_staff_role():
            return True
        return user.phone_verified