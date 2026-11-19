from django.urls import path

from .views import NotificationListView, NotificationMarkReadView

urlpatterns = [

    path('', NotificationListView.as_view(), name='notifications_list'),

    path('<uuid:notification_id>/read/', NotificationMarkReadView.as_view(), name='notifications_mark_read')

]