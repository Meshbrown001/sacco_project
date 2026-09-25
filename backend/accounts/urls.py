from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    CustomLoginView,
    LogoutView,
    MemberRegisterView,
    MyProfileView,
    ResendPhoneOTPView,
    VerifyPhoneView,
)

urlpatterns = [
    path('register/', MemberRegisterView.as_view(), name='member-register'),
    path('login/', CustomLoginView.as_view(), name='login'),
    path('login/refresh/', TokenRefreshView.as_view(), name='login-refresh'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('me/', MyProfileView.as_view(), name='my-profile'),
    path('verify-phone/', VerifyPhoneView.as_view(), name='verify-phone'),
    path('verify-phone/resend/', ResendPhoneOTPView.as_view(), name='verify-phone-resend'),
]