from django.urls import path
from . import views

urlpatterns = [
    # 🧾 Job CRUD
    path('', views.JobVacancyListCreateView.as_view(), name='job_list_create'),
    path('<uuid:job_id>/', views.JobVacancyDetailView.as_view(), name='job_detail'),
    path('<uuid:job_id>/update/', views.JobVacancyUpdateView.as_view(), name='job_update'),
    path('<uuid:job_id>/delete/', views.JobVacancyDeleteView.as_view(), name='job_delete'),

    # 👥 Applications CRUD
    path('<uuid:job_id>/apply/', views.JobApplicationCreateView.as_view(), name='job_apply'),
    path('<uuid:job_id>/applicants/', views.JobApplicantListView.as_view(), name='job_applicants'),
    path('application/<uuid:applicant_id>/update/', views.JobApplicationUpdateView.as_view(), name='application_update'),
    path('application/<uuid:applicant_id>/delete/', views.JobApplicationDeleteView.as_view(), name='application_delete'),

    # 📤 File Upload Endpoints
    path('upload-job-desc/', views.UploadJobDescriptionView.as_view(), name='upload_job_desc'),
    path('upload-applicant-cv/', views.UploadApplicantCVView.as_view(), name='upload_applicant_cv'),
]