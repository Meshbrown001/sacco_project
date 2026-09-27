from django.contrib import admin

from .models import MpesaTransaction


@admin.register(MpesaTransaction)
class MpesaTransactionAdmin(admin.ModelAdmin):
    list_display = ("id", "member", "amount", "phone_number", "status", "mpesa_receipt", "credited", "created_at")
    list_filter = ("status", "credited")
    search_fields = ("member__username", "phone_number", "mpesa_receipt", "checkout_request_id")
    readonly_fields = [field.name for field in MpesaTransaction._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False