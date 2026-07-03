from rest_framework import generics, permissions, status
from rest_framework.response import Response

from .serializers import SaccoRegistrationSerializer


class SaccoRegistrationView(generics.CreateAPIView):
    """
    One-time SACCO setup.
    POST /api/core/register-sacco/
    Open to unauthenticated callers, but guarded so it works
    only once: after a SACCO exists, it refuses all further calls.
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = SaccoRegistrationSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        return Response(
            {
                "message": "SACCO registered successfully.",
                "sacco": result["sacco"].name,
                "registration_number": result["sacco"].registration_number,
                "staff_created": result["staff_created"],
            },
            status=status.HTTP_201_CREATED,
        )