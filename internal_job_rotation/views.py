from django.db.models import Q
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from api.models import User, JobRotationNomination
from api.views import CookieJWTAuthentication
from notifications.services import get_ijr_administrators
from .serializers import IJREmployeeSerializer, IJREmployeeDetailSerializer, IJRManagerSerializer, IJRNominationCreateSerializer, IJRNominationSerializer
from .services import create_ijr_nomination

class IJRBaseView(APIView):
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def is_hr(self, user):
        return bool(user.is_hr)

    def is_ijr_admin(self, user):
        return get_ijr_administrators().filter(pk=user.pk).exists()

    def check_ijr_access(self, request, allow_admin=False):
        if self.is_hr(request.user) or (allow_admin and self.is_ijr_admin(request.user)):
            return None
        return Response({'error': 'You do not have permission to access Internal Job Rotation.'}, status=status.HTTP_403_FORBIDDEN)

class IJREmployeeListView(IJRBaseView):
    def get(self, request):
        denied = self.check_ijr_access(request)
        if denied is not None:
            return denied
        search = request.query_params.get('search', '').strip()
        employees = User.objects.filter(is_active=True)
        if search:
            employees = employees.filter(Q(name__icontains=search) | Q(emp_id__icontains=search) | Q(email__icontains=search))
        employees = employees.order_by('name', 'emp_id')
        return Response({'count': employees.count(), 'employees': IJREmployeeSerializer(employees, many=True).data})

class IJREmployeeDetailView(IJRBaseView):
    def get(self, request, emp_id):
        denied = self.check_ijr_access(request)
        if denied is not None:
            return denied
        employee = User.objects.filter(emp_id=emp_id, is_active=True).first()
        if not employee:
            return Response({'error': 'Active employee not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'employee': IJREmployeeDetailSerializer(employee).data})

class IJROptionsView(IJRBaseView):
    def get(self, request):
        denied = self.check_ijr_access(request)
        if denied is not None:
            return denied
        sbus = User.objects.filter(is_active=True).exclude(sub_bu__isnull=True).exclude(sub_bu__exact='').values_list('sub_bu', flat=True).distinct()
        return Response({'sbus': sorted(sbus, key=str.casefold)})

class IJRManagerListView(IJRBaseView):
    def get(self, request):
        denied = self.check_ijr_access(request)
        if denied is not None:
            return denied
        sub_bu = request.query_params.get('sub_bu', '').strip()
        if not sub_bu:
            return Response({'error': 'sub_bu is required.'}, status=status.HTTP_400_BAD_REQUEST)
        managers = User.objects.filter(is_active=True, sub_bu__iexact=sub_bu).order_by('name', 'emp_id')
        return Response({'count': managers.count(), 'managers': IJRManagerSerializer(managers, many=True).data})

class IJRNominationListCreateView(IJRBaseView):
    def get(self, request):
        denied = self.check_ijr_access(request, allow_admin=True)
        if denied is not None:
            return denied
        nominations = JobRotationNomination.objects.select_related('employee', 'nominated_by').all()
        return Response({'count': nominations.count(), 'nominations': IJRNominationSerializer(nominations, many=True).data})

    def post(self, request):
        denied = self.check_ijr_access(request)
        if denied is not None:
            return denied
        serializer = IJRNominationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        nomination = create_ijr_nomination(serializer.validated_data, request.user)
        return Response({'message': 'IJR nomination submitted successfully.', 'nomination': IJRNominationSerializer(nomination).data}, status=status.HTTP_201_CREATED)

class IJRNominationDetailView(IJRBaseView):
    def get(self, request, nomination_id):
        denied = self.check_ijr_access(request, allow_admin=True)
        if denied is not None:
            return denied
        nomination = JobRotationNomination.objects.select_related('employee', 'nominated_by').filter(pk=nomination_id).first()
        if not nomination:
            return Response({'error': 'IJR nomination not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'nomination': IJRNominationSerializer(nomination).data})