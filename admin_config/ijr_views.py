from django.db.models import Q
from django.utils.dateparse import parse_date

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status

from api.models import JobRotationNomination
from api.views import CookieJWTAuthentication
from notifications.services import get_ijr_administrators

from .ijr_services import (
    decide_ijr_nomination,
    permanently_delete_ijr_nomination
)


class IJRAdminBaseView(APIView):
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def check_admin_access(self, request):
        if not get_ijr_administrators().filter(pk=request.user.pk).exists():
            return Response(
                {'error': 'Only authorized IJR administrators can access this resource.'},
                status=status.HTTP_403_FORBIDDEN
            )

        return None


class IJRAdminListView(IJRAdminBaseView):
    def get(self, request):
        denied = self.check_admin_access(request)

        if denied is not None:
            return denied

        nominations = (
            JobRotationNomination.objects
            .select_related('employee', 'nominated_by', 'decided_by')
            .all()
        )

        search = request.query_params.get('search', '').strip()
        nomination_status = request.query_params.get('status', '').strip().upper()
        date_from = request.query_params.get('date_from', '').strip()
        date_to = request.query_params.get('date_to', '').strip()

        if search:
            nominations = nominations.filter(
                Q(employee__name__icontains=search)
                | Q(employee__emp_id__icontains=search)
                | Q(nominated_by__name__icontains=search)
                | Q(nominated_by__emp_id__icontains=search)
            )

        if nomination_status and nomination_status != 'ALL':
            valid_statuses = dict(JobRotationNomination.STATUS_CHOICES)

            if nomination_status not in valid_statuses:
                return Response(
                    {'error': 'Invalid nomination status.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            nominations = nominations.filter(status=nomination_status)

        if date_from:
            parsed_date = parse_date(date_from)

            if not parsed_date:
                return Response(
                    {'error': 'Invalid date_from. Use YYYY-MM-DD.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            nominations = nominations.filter(created_at__date__gte=parsed_date)

        if date_to:
            parsed_date = parse_date(date_to)

            if not parsed_date:
                return Response(
                    {'error': 'Invalid date_to. Use YYYY-MM-DD.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            nominations = nominations.filter(created_at__date__lte=parsed_date)

        data = [
            {
                'id': str(nomination.id),
                'employee_emp_id': nomination.employee.emp_id,
                'employee_name': nomination.employee.name,
                'nominated_by_emp_id': nomination.nominated_by.emp_id,
                'nominated_by_name': nomination.nominated_by.name,
                'current_details': nomination.current_details,
                'proposed_details': nomination.proposed_details,
                'reason': nomination.reason,
                'remarks': nomination.remarks,
                'effective_date': nomination.effective_date,
                'status': nomination.status,
                'decision_remarks': nomination.decision_remarks,
                'decided_by_name': (
                    nomination.decided_by.name
                    if nomination.decided_by else None
                ),
                'decided_at': nomination.decided_at,
                'created_at': nomination.created_at,
                'updated_at': nomination.updated_at
            }
            for nomination in nominations
        ]

        return Response({
            'count': len(data),
            'nominations': data
        })


class IJRAdminDetailView(IJRAdminBaseView):
    def get(self, request, nomination_id):
        denied = self.check_admin_access(request)

        if denied is not None:
            return denied

        nomination = (
            JobRotationNomination.objects
            .select_related('employee', 'nominated_by', 'decided_by')
            .prefetch_related('history__performed_by')
            .filter(pk=nomination_id)
            .first()
        )

        if not nomination:
            return Response(
                {'error': 'IJR nomination not found.'},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response({
            'nomination': {
                'id': str(nomination.id),
                'employee_emp_id': nomination.employee.emp_id,
                'employee_name': nomination.employee.name,
                'nominated_by_emp_id': nomination.nominated_by.emp_id,
                'nominated_by_name': nomination.nominated_by.name,
                'current_details': nomination.current_details,
                'proposed_details': nomination.proposed_details,
                'reason': nomination.reason,
                'remarks': nomination.remarks,
                'effective_date': nomination.effective_date,
                'status': nomination.status,
                'decision_remarks': nomination.decision_remarks,
                'decided_by_name': (
                    nomination.decided_by.name
                    if nomination.decided_by else None
                ),
                'decided_at': nomination.decided_at,
                'created_at': nomination.created_at,
                'updated_at': nomination.updated_at
            },
            'history': [
                {
                    'id': record.id,
                    'action': record.action,
                    'previous_status': record.previous_status,
                    'new_status': record.new_status,
                    'remarks': record.remarks,
                    'performed_by_name': (
                        record.performed_by.name
                        if record.performed_by else None
                    ),
                    'created_at': record.created_at
                }
                for record in nomination.history.all()
            ]
        })

    def delete(self, request, nomination_id):
        denied = self.check_admin_access(request)

        if denied is not None:
            return denied

        result = permanently_delete_ijr_nomination(
            nomination_id=nomination_id,
            employee_emp_id=request.data.get('employee_emp_id'),
            confirmation=request.data.get('confirmation')
        )

        return Response(result, status=status.HTTP_200_OK)


class IJRAdminApproveView(IJRAdminBaseView):
    def post(self, request, nomination_id):
        denied = self.check_admin_access(request)

        if denied is not None:
            return denied

        nomination = decide_ijr_nomination(
            nomination_id=nomination_id,
            administrator=request.user,
            action='APPROVED',
            remarks=request.data.get('remarks', '')
        )

        return Response({
            'message': 'IJR nomination approved for implementation.',
            'nomination_id': str(nomination.id),
            'status': nomination.status,
            'decision_remarks': nomination.decision_remarks,
            'decided_at': nomination.decided_at
        })


class IJRAdminRejectView(IJRAdminBaseView):
    def post(self, request, nomination_id):
        denied = self.check_admin_access(request)

        if denied is not None:
            return denied

        nomination = decide_ijr_nomination(
            nomination_id=nomination_id,
            administrator=request.user,
            action='REJECTED',
            remarks=request.data.get('remarks', '')
        )

        return Response({
            'message': 'IJR nomination rejected for implementation.',
            'nomination_id': str(nomination.id),
            'status': nomination.status,
            'decision_remarks': nomination.decision_remarks,
            'decided_at': nomination.decided_at
        })