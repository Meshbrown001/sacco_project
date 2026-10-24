from django.urls import path
from .views import (
    MemberDashboardView,
    MonthListView,
    MonthlyListDetailView,
    SecretaryLevyListView,
    SecretaryLevyDetailView,
)

urlpatterns = [
    path("dashboard/", MemberDashboardView.as_view(), name="member-dashboard"),
    path("secretary/months/", MonthListView.as_view(), name="secretary-months"),
    path("secretary/month/", MonthlyListDetailView.as_view(), name="secretary-month-detail"),
    path("secretary/levies/", SecretaryLevyListView.as_view(), name="secretary-levies"),
    path("secretary/levies/<int:pk>/", SecretaryLevyDetailView.as_view(), name="secretary-levy-detail"),
]