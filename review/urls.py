# review/urls.py
from django.urls import path
from .views import CVsForReview, SubmitReviewView, UpdateReviewView

urlpatterns = [
    path('', CVsForReview.as_view(), name='cvs-for-review'),
    path('<int:referral_id>/submit/', SubmitReviewView.as_view(), name='submit-review'),
    path('<int:referral_id>/update/', UpdateReviewView.as_view(), name='update-review'),
]
