from django.urls import path
from . import views
from .views import *


urlpatterns = [
    path('hello/', HelloWorldView.as_view(), name='hello-world'),
    path('upload-cv/', UploadCVView.as_view(), name='upload-cv'),
    path('register/', RegisterView.as_view()),
    path('login/', LoginView.as_view()),
    path('logout/', LogoutView.as_view()),
    path("bulk-register/", BulkUserRegisterView.as_view(), name="bulk_register"),
    path("bulk-register/", BulkUserRegisterView.as_view(), name="bulk_register"),
    path('me/', MeView.as_view(), name='me'),
    path('departments/', DepartmentListView.as_view(), name='departments'),
    path('update-profile/', UpdateUserProfile.as_view(), name='update-profile'),
    path('get-user-by-empid/', GetUserByEmpIDView.as_view(), name='get-user-by-empid'),
]