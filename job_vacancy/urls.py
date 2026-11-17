from django.urls import path
from . import views
from .notification_views import NotificationListView, NotificationMarkReadView

urlpatterns = [
    path('', views.JobVacancyListCreateView.as_view(), name='job_list_create'),
    path('upload-job-desc/', views.UploadJobDescriptionView.as_view(), name='upload_job_desc'),
    path('upload-applicant-cv/', views.UploadApplicantCVView.as_view(), name='upload_applicant_cv'),
    path('application/<uuid:applicant_id>/update/', views.JobApplicationUpdateView.as_view(), name='application_update'),
    path('application/<uuid:applicant_id>/delete/', views.JobApplicationDeleteView.as_view(), name='application_delete'),
    path('<uuid:job_id>/', views.JobVacancyDetailView.as_view(), name='job_detail'),
    path('<uuid:job_id>/update/', views.JobVacancyUpdateView.as_view(), name='job_update'),
    path('<uuid:job_id>/delete/', views.JobVacancyDeleteView.as_view(), name='job_delete'),
    path('<uuid:job_id>/publish/', views.JobVacancyPublishView.as_view(), name='job_publish'),
    path('<uuid:job_id>/close/', views.JobVacancyCloseView.as_view(), name='job_close'),
    path('<uuid:job_id>/reopen/', views.JobVacancyReopenView.as_view(), name='job_reopen'),
    path('<uuid:job_id>/archive/', views.JobVacancyArchiveView.as_view(), name='job_archive'),
    path('<uuid:job_id>/apply/', views.JobApplicationCreateView.as_view(), name='job_apply'),
    path('<uuid:job_id>/applicants/', views.JobApplicantListView.as_view(), name='job_applicants'),
    path('notifications/', NotificationListView.as_view(), name='ijp_notifications'),
    path('notifications/<uuid:notification_id>/read/', NotificationMarkReadView.as_view(), name='ijp_notification_read'),
]