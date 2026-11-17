from django.urls import path
from .views import (
    DepartmentListView,
    DepartmentCreateView,
    DepartmentUpdateView,
    SBUListCreateView,
    SBUDetailView,
    EmailTemplateListView,
    EmailTemplateDetailView,
    SBUListView,
    CompletedReferralsListView,
    CompletedReferralDetailView
)

urlpatterns = [
    path("departments/", DepartmentListView.as_view()),
    path("departments/create/", DepartmentCreateView.as_view()),
    path("departments/<uuid:department_id>/update/", DepartmentUpdateView.as_view()),
    path("sbus/", SBUListCreateView.as_view()),
    path("sbus/<str:email>/", SBUDetailView.as_view(), name="sbu-detail"),
    path("email-templates/", EmailTemplateListView.as_view(), name="email-template-list"),
    path("email-templates/<str:purpose>/", EmailTemplateDetailView.as_view(), name="email-template-detail"),
    path("sbus-list/", SBUListView.as_view()),
    path("completed-referrals/", CompletedReferralsListView.as_view(), name="completed-referrals-list"),
    path("completed-referrals/<int:referral_id>/", CompletedReferralDetailView.as_view(), name="completed-referral-detail"),
]