from django.contrib import admin
from .models import Sacco, PaymentSettings, ContributionSettings

admin.site.register(Sacco)
admin.site.register(PaymentSettings)
admin.site.register(ContributionSettings)