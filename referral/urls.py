from django.urls import path
from .views import SubmitReferralView, SubmitIJPReferralView, MyReferralsView, UpdateReferralView, DeleteReferralView, AcademicDetailsListView, ReferralAcademicDetailsView, ReferralEmployeeListView

urlpatterns = [
    path('', SubmitReferralView.as_view(), name='submit-referral'),
    path('ijp/', SubmitIJPReferralView.as_view(), name='submit-ijp-referral'),
    path('employees/', ReferralEmployeeListView.as_view(), name='referral-employees'),
    path('my/', MyReferralsView.as_view(), name='my-referrals'),
    path('<int:referral_id>/update/', UpdateReferralView.as_view()),
    path('<int:referral_id>/delete/', DeleteReferralView.as_view()),
    path('academic-details/', AcademicDetailsListView.as_view(), name='academic-details-list'),
    path('academic-details/<int:referral_id>/', ReferralAcademicDetailsView.as_view(), name='referral-academic-details'),
]