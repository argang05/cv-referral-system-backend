from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from api.views import CookieJWTAuthentication
from api.models import Notification, NotificationRead

class NotificationListView(APIView):
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        notifications = Notification.objects.filter(
            notification_type='NEW_JOB',
            job_posting__status__in=['OPEN', 'CLOSED']
        ).select_related('job_posting').order_by('-created_at')[:100]

        read_ids = set(NotificationRead.objects.filter(
            employee=request.user,
            notification__in=notifications
        ).values_list('notification_id', flat=True))

        results = [{
            'id': str(notification.id),
            'title': notification.title,
            'message': notification.message,
            'notification_type': notification.notification_type,
            'created_at': notification.created_at,
            'is_read': notification.id in read_ids,
            'job_posting': {
                'job_id': str(notification.job_posting.job_id),
                'job_title': notification.job_posting.job_title,
                'status': notification.job_posting.status
            } if notification.job_posting else None
        } for notification in notifications]

        return Response({
            'count': len(results),
            'unread_count': sum(not item['is_read'] for item in results),
            'results': results
        })

class NotificationMarkReadView(APIView):
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, notification_id):
        notification = get_object_or_404(
            Notification,
            id=notification_id,
            notification_type='NEW_JOB'
        )
        NotificationRead.objects.get_or_create(
            notification=notification,
            employee=request.user
        )
        return Response({'message': 'Notification marked as read.'})