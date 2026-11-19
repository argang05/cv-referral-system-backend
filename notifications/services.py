from django.db import transaction
from django.db.models import Q
from django.core.exceptions import ValidationError
from django.utils.http import url_has_allowed_host_and_scheme
from api.models import Notification, NotificationRecipient, User

IJR_ADMIN_EMAILS = (
    'abhishek.ganguly@tor.ai',
    'admin2@gmail.com',
    'admin3@gmail.com'
)

def get_ijr_administrators():
    emails = Q()
    for email in IJR_ADMIN_EMAILS:
        emails |= Q(email__iexact=email)
    return User.objects.filter(emails, is_active=True) if emails else User.objects.none()

def validate_target_url(target_url):
    if not target_url:
        return ''
    if not isinstance(target_url, str) or not target_url.startswith('/') or target_url.startswith('//'):
        raise ValidationError('Notification target must be an internal application path.')
    if not url_has_allowed_host_and_scheme(target_url, allowed_hosts=set(), require_https=False):
        raise ValidationError('Invalid notification target URL.')
    return target_url

@transaction.atomic
def create_notification(notification_type, title, message, audience='ALL', recipients=None, target_url='', job_posting=None):
    valid_types = dict(Notification.NOTIFICATION_TYPE_CHOICES)
    if notification_type not in valid_types:
        raise ValidationError('Invalid notification type.')
    if audience not in dict(Notification.AUDIENCE_CHOICES):
        raise ValidationError('Invalid notification audience.')
    if audience == 'ALL' and recipients is not None:
        raise ValidationError('Public notifications cannot have individual recipients.')
    if audience == 'SPECIFIC' and recipients is None:
        raise ValidationError('Private notifications require recipients.')

    target_url = validate_target_url(target_url)
    recipient_ids = []
    if audience == 'SPECIFIC':
        recipient_ids = list(dict.fromkeys(
            recipient.emp_id if isinstance(recipient, User) else str(recipient)
            for recipient in recipients
        ))
        active_ids = list(User.objects.filter(emp_id__in=recipient_ids, is_active=True).values_list('emp_id', flat=True))
        if not active_ids:
            raise ValidationError('No active recipients found.')
        if len(active_ids) != len(recipient_ids):
            raise ValidationError('Some notification recipients are invalid or inactive.')
        recipient_ids = active_ids

    notification = Notification.objects.create(
        notification_type=notification_type,
        audience=audience,
        title=title,
        message=message,
        target_url=target_url,
        job_posting=job_posting
    )
    if recipient_ids:
        NotificationRecipient.objects.bulk_create([
            NotificationRecipient(notification=notification, employee_id=emp_id)
            for emp_id in recipient_ids
        ])
    return notification

def create_ijr_nomination_notification(title, message, target_url=''):
    administrators = list(get_ijr_administrators().values_list('emp_id', flat=True))
    if not administrators:
        raise ValidationError('No active IJR administrators are configured.')
    return create_notification(
        notification_type='IJR_NOMINATED',
        title=title,
        message=message,
        audience='SPECIFIC',
        recipients=administrators,
        target_url=target_url
    )