from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import MemberRegisterView, CustomLoginView, MyProfileView

urlpatterns = [
    path('register/', MemberRegisterView.as_view(), name='member-register'),
    path('login/', CustomLoginView.as_view(), name='login'),
    path('login/refresh/', TokenRefreshView.as_view(), name='login-refresh'),
    path('me/', MyProfileView.as_view(), name='my-profile'),
]