from django.urls import path
from .views import HREvaluationView

urlpatterns = [
    path('', HREvaluationView.as_view()),
]
