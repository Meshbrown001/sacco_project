from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    CustomLoginView,
    LogoutView,
    MemberRegisterView,
    MyProfileView,
    PasswordResetCompleteView,
    PasswordResetSendView,
    PasswordResetStartView,
    PasswordResetVerifyView,
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
    path('password-reset/start/', PasswordResetStartView.as_view(), name='password-reset-start'),
    path('password-reset/send/', PasswordResetSendView.as_view(), name='password-reset-send'),
    path('password-reset/verify/', PasswordResetVerifyView.as_view(), name='password-reset-verify'),
    path('password-reset/complete/', PasswordResetCompleteView.as_view(), name='password-reset-complete'),
]