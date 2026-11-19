from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('api.urls')),
    path('api/referrals/', include('referral.urls')),
    path('api/reviews/', include('review.urls')),
    path('api/hr-evaluation/', include('hr_evaluation.urls')),
    path('api/admin-config/', include('admin_config.urls')),
    path('api/job-vacancy/', include('job_vacancy.urls')),
    path('api/notifications/', include('notifications.urls')),
]