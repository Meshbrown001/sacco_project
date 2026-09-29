from django.urls import path

from .chair_views import (
    AccountDeactivateView,
    AccountListView,
    AccountReactivateView,
    LevyCancelView,
    LevyCloseView,
    LevyDetailView,
    LevyListCreateView,
    SettingsView,
    StaffCreateView,
)

urlpatterns = [
    path("accounts/", AccountListView.as_view(), name="chair-accounts"),
    path("accounts/staff/", StaffCreateView.as_view(), name="chair-staff-create"),
    path("accounts/<int:pk>/deactivate/", AccountDeactivateView.as_view(), name="chair-deactivate"),
    path("accounts/<int:pk>/reactivate/", AccountReactivateView.as_view(), name="chair-reactivate"),
    path("settings/", SettingsView.as_view(), name="chair-settings"),
    path("levies/", LevyListCreateView.as_view(), name="chair-levies"),
    path("levies/<int:pk>/", LevyDetailView.as_view(), name="chair-levy-detail"),
    path("levies/<int:pk>/cancel/", LevyCancelView.as_view(), name="chair-levy-cancel"),
    path("levies/<int:pk>/close/", LevyCloseView.as_view(), name="chair-levy-close"),
]