from django.contrib import admin
from .models import MemberWallet, MonthlyContribution, Penalty, SpecialLevy

admin.site.register(MemberWallet)
admin.site.register(MonthlyContribution)
admin.site.register(Penalty)
admin.site.register(SpecialLevy)