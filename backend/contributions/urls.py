from django.urls import path
from .views import MemberDashboardView, MonthListView, MonthlyListDetailView

urlpatterns = [
    path("dashboard/", MemberDashboardView.as_view(), name="member-dashboard"),
    path("secretary/months/", MonthListView.as_view(), name="secretary-months"),
    path("secretary/month/", MonthlyListDetailView.as_view(), name="secretary-month-detail"),
]