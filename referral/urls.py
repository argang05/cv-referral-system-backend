from django.urls import path
from .views import SubmitReferralView, MyReferralsView, UpdateReferralView,DeleteReferralView

urlpatterns = [
    path('', SubmitReferralView.as_view(), name='submit-referral'),
    path('my/', MyReferralsView.as_view(), name='my-referrals'),
    path("<int:referral_id>/update/", UpdateReferralView.as_view()),
    path("<int:referral_id>/delete/", DeleteReferralView.as_view()),
]