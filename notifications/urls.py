from django.urls import path

from .views import NotificationListView, NotificationMarkReadView, NotificationMarkAllReadView

urlpatterns = [

    path('', NotificationListView.as_view(), name='notifications_list'),

    path('mark-all-read/', NotificationMarkAllReadView.as_view(), name='notifications_mark_all_read'),

    path('<uuid:notification_id>/read/', NotificationMarkReadView.as_view(), name='notifications_mark_read')

]