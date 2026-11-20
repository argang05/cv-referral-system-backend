from django.db import transaction, IntegrityError
from rest_framework.exceptions import ValidationError

from api.models import JobRotationNomination
from notifications.services import create_ijr_nomination_notification


def get_employee_snapshot(employee):
    manager = employee.manager if employee.manager_id else None

    return {
        'sub_bu': employee.sub_bu or '',
        'reporting_manager_emp_id': (
            employee.reporting_manager_emp_id
            or (manager.emp_id if manager else '')
        ),
        'reporting_manager_name': (
            employee.reporting_manager_name
            or (manager.name if manager else '')
        ),
        'designation': employee.designation or '',
        'band': employee.band or ''
    }


def create_ijr_nomination(validated_data, nominated_by):
    employee = validated_data['employee']
    manager = validated_data['manager']

    current_details = get_employee_snapshot(employee)

    proposed_details = {
        'sub_bu': validated_data['proposed_sub_bu'],
        'reporting_manager_emp_id': manager.emp_id if manager else '',
        'reporting_manager_name': manager.name if manager else '',
        'designation': (
            validated_data.get('proposed_designation')
            or current_details['designation']
        ),
        'band': (
            validated_data.get('proposed_band')
            or current_details['band']
        )
    }

    try:
        with transaction.atomic():
            nomination = JobRotationNomination.objects.create(
                employee=employee,
                nominated_by=nominated_by,
                current_details=current_details,
                proposed_details=proposed_details,
                reason=validated_data['reason'],
                remarks=validated_data.get('remarks', ''),
                effective_date=validated_data.get('effective_date'),
                status='PENDING'
            )

            create_ijr_nomination_notification(
                title='New Internal Job Rotation Nomination',
                message=(
                    f'{nominated_by.name} nominated {employee.name} '
                    f'({employee.emp_id}) for an internal job rotation '
                    f'from {current_details["sub_bu"] or "Unassigned"} '
                    f'to {proposed_details["sub_bu"]}.'
                ),
                target_url='/admin',
                nomination=nomination
            )

            return nomination

    except IntegrityError:
        raise ValidationError({
            'employee_emp_id': (
                'This employee already has an active IJR nomination.'
            )
        })