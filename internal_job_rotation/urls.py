from django.urls import path
from .views import IJREmployeeListView, IJREmployeeDetailView, IJROptionsView, IJRManagerListView, IJRNominationListCreateView, IJRNominationDetailView

urlpatterns = [
    path('employees/', IJREmployeeListView.as_view(), name='ijr-employee-list'),
    path('employees/<str:emp_id>/', IJREmployeeDetailView.as_view(), name='ijr-employee-detail'),
    path('options/', IJROptionsView.as_view(), name='ijr-options'),
    path('managers/', IJRManagerListView.as_view(), name='ijr-manager-list'),
    path('nominations/', IJRNominationListCreateView.as_view(), name='ijr-nomination-list-create'),
    path('nominations/<uuid:nomination_id>/', IJRNominationDetailView.as_view(), name='ijr-nomination-detail'),
]