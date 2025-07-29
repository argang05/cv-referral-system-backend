from django.contrib import admin
from .models import User, SBU, Referral, Review, HREvaluation, AdminConfig


# Register your models here.
admin.site.register(User)
admin.site.register(SBU)
admin.site.register(Referral)
admin.site.register(Review)
admin.site.register(HREvaluation)
admin.site.register(AdminConfig)