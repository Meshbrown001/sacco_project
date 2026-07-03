from django.urls import path
from .views import SaccoRegistrationView

urlpatterns = [
    path('register-sacco/', SaccoRegistrationView.as_view(), name='register-sacco'),
]