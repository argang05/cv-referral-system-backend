from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from api.views import CookieJWTAuthentication
from api.models import Notification, NotificationRead

class NotificationBaseView(APIView):
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get_queryset(self, user):
        if not user.is_active:
            return Notification.objects.none()
        return Notification.objects.filter(
            Q(audience='ALL') | Q(audience='SPECIFIC', recipients__employee=user)
        ).exclude(
            notification_type='NEW_JOB',
            job_posting__status__in=['DRAFT', 'ARCHIVED']
        ).distinct()

class NotificationListView(NotificationBaseView):
    def get(self, request):
        notifications = list(
            self.get_queryset(request.user)
            .select_related('job_posting')
            .order_by('-created_at')[:100]
        )
        read_ids = set(NotificationRead.objects.filter(
            employee=request.user,
            notification__in=notifications
        ).values_list('notification_id', flat=True))

        results = []
        for notification in notifications:
            job = notification.job_posting
            target_url = notification.target_url
            if not target_url and notification.notification_type == 'NEW_JOB' and job:
                target_url = f'/job-vacancies?job_id={job.job_id}'
            results.append({
                'id': str(notification.id),
                'title': notification.title,
                'message': notification.message,
                'notification_type': notification.notification_type,
                'created_at': notification.created_at,
                'is_read': notification.id in read_ids,
                'target_url': target_url,
                'job_posting': {
                    'job_id': str(job.job_id),
                    'job_title': job.job_title,
                    'status': job.status
                } if job else None
            })

        return Response({
            'count': len(results),
            'unread_count': sum(not item['is_read'] for item in results),
            'results': results
        })

class NotificationMarkReadView(NotificationBaseView):
    def post(self, request, notification_id):
        notification = get_object_or_404(self.get_queryset(request.user), id=notification_id)
        NotificationRead.objects.get_or_create(notification=notification, employee=request.user)
        return Response({'message': 'Notification marked as read.'})