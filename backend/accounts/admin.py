# Register your models here.
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser


class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ['username', 'email', 'role', 'phone_number', 'is_staff_role']
    list_filter = UserAdmin.list_filter + ('role',)
    search_fields = ('username', 'email', 'phone_number', 'national_id')
    ordering = ('username',)
    fieldsets = UserAdmin.fieldsets + (
        ('SACCO Info', {'fields': ('role', 'phone_number', 'national_id')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('SACCO Info', {'fields': ('role', 'phone_number', 'national_id')}),
    )


admin.site.register(CustomUser, CustomUserAdmin)