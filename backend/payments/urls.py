from django.urls import path

from .views import InitiatePaymentView, MpesaCallbackView, PaymentStatusView

urlpatterns = [
    path("mpesa/stk-push/", InitiatePaymentView.as_view(), name="mpesa-stk-push"),
    path("mpesa/callback/<str:secret>/", MpesaCallbackView.as_view(), name="mpesa-callback"),
    path("status/<int:pk>/", PaymentStatusView.as_view(), name="payment-status"),
]