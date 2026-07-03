from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from .serializers import MemberRegistrationSerializer, UserSerializer, CustomTokenObtainPairSerializer


class MemberRegisterView(generics.CreateAPIView):
    """
    Public endpoint - anyone can register as a member.
    POST /api/accounts/register/
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = MemberRegistrationSerializer


class CustomLoginView(TokenObtainPairView):
    """
    Shared login endpoint for members AND staff.
    POST /api/accounts/login/
    Returns access + refresh tokens, plus role and username.
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = CustomTokenObtainPairSerializer


class MyProfileView(APIView):
    """
    Returns the logged-in user's own profile info.
    GET /api/accounts/me/
    Requires a valid access token.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)