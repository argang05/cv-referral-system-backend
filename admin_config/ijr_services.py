from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError, NotFound

from api.models import (
    JobRotationNomination,
    JobRotationHistory,
    Notification
)

from notifications.services import create_ijr_decision_notification


@transaction.atomic
def decide_ijr_nomination(nomination_id, administrator, action, remarks=''):
    if action not in ('APPROVED', 'REJECTED'):
        raise ValidationError({
            'action': 'Invalid IJR administrative action.'
        })

    if not isinstance(remarks, str):
        raise ValidationError({
            'remarks': 'Remarks must be text.'
        })

    remarks = remarks.strip()

    if action == 'REJECTED' and not remarks:
        raise ValidationError({
            'remarks': 'A rejection reason is required.'
        })

    nomination = (
        JobRotationNomination.objects
        .select_for_update()
        .select_related('employee', 'nominated_by')
        .filter(pk=nomination_id)
        .first()
    )

    if not nomination:
        raise NotFound('IJR nomination not found.')

    if nomination.status != 'PENDING':
        raise ValidationError({
            'status': 'Only pending IJR nominations can be approved or rejected.'
        })

    previous_status = nomination.status

    nomination.status = action
    nomination.decided_by = administrator
    nomination.decided_at = timezone.now()
    nomination.decision_remarks = remarks

    nomination.save(update_fields=[
        'status',
        'decided_by',
        'decided_at',
        'decision_remarks',
        'updated_at'
    ])

    JobRotationHistory.objects.create(
        nomination=nomination,
        action=action,
        performed_by=administrator,
        previous_status=previous_status,
        new_status=action,
        remarks=remarks
    )

    create_ijr_decision_notification(
        nomination=nomination,
        administrator=administrator
    )

    return nomination


@transaction.atomic
def permanently_delete_ijr_nomination(
    nomination_id,
    employee_emp_id,
    confirmation
):
    nomination = (
        JobRotationNomination.objects
        .select_for_update()
        .select_related('employee')
        .filter(pk=nomination_id)
        .first()
    )

    if not nomination:
        raise NotFound('IJR nomination not found.')

    if (
        not isinstance(employee_emp_id, str)
        or employee_emp_id != nomination.employee.emp_id
    ):
        raise ValidationError({
            'employee_emp_id': 'Employee ID does not match the nomination.'
        })

    if confirmation != 'DELETE':
        raise ValidationError({
            'confirmation': 'Type DELETE exactly to confirm permanent deletion.'
        })

    # Identify older IJR notifications that were created before
    # the nomination foreign key was introduced.
    legacy_notification_ids = list(
        Notification.objects.filter(
            job_rotation_nomination__isnull=True,
            notification_type__in=[
                'IJR_NOMINATED',
                'IJR_APPROVED',
                'IJR_REJECTED',
                'IJR_IMPLEMENTED'
            ],
            target_url__in=[
                f'/admin/ijr/{nomination.id}',
                f'/admin/ijr/{nomination.id}/'
            ]
        ).values_list('pk', flat=True)
    )

    # Deletes the nomination, its linked notifications,
    # notification recipients, read records, and IJR history.
    nomination.delete()

    if legacy_notification_ids:
        Notification.objects.filter(
            pk__in=legacy_notification_ids
        ).delete()

    return {
        'message': 'IJR nomination permanently deleted successfully.',
        'employee_emp_id': employee_emp_id
    }