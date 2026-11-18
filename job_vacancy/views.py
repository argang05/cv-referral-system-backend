import re
import uuid
import logging
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from api.views import CookieJWTAuthentication
from api.models import JobVacancy, JobApplication, JobPostingHistory, Notification
from api.utils import upload_to_supabase
from .serializers import JobVacancySerializer, JobPostingDetailSerializer, JobApplicationSerializer, EmployeeJobVacancySerializer

logger = logging.getLogger(__name__)

def sanitize_filename(filename):
    return re.sub(r'[^A-Za-z0-9_\-\.]', '', filename.replace(' ', '_'))

def is_ijp_admin(user):
    return user.role in ['ADMIN', 'HR'] or bool(user.is_hr)

def admin_required(request):
    if not is_ijp_admin(request.user):
        return Response({'error': 'Only HR/Admin employees can manage job postings.'}, status=403)
    return None

def record_job_history(job, action, actor=None, changes=None, previous_status=None, new_status=None):
    return JobPostingHistory.objects.create(
        job=job,
        action=action,
        performed_by=actor,
        changes=changes or {},
        previous_status=previous_status,
        new_status=new_status if new_status is not None else job.status
    )

def get_locked_job(job_id, with_department=False):
    queryset = JobVacancy.objects.select_for_update(of=('self',))
    if with_department:
        queryset = queryset.select_related('department')
    return get_object_or_404(queryset, job_id=job_id)

def validate_job_fields(job):
    errors = {}
    required = {
        'job_title': job.job_title,
        'job_desc_document_url': job.job_desc_document_url,
        'location': job.location,
        'department': job.department_id,
        'employment_type': job.employment_type,
        'education_summary': job.education_summary,
        'key_skills': job.key_skills
    }

    for field, value in required.items():
        if value is None or (isinstance(value, str) and not value.strip()):
            errors[field] = 'This field is required.'

    if job.min_experience is None:
        errors['min_experience'] = 'Minimum experience is required.'

    if job.min_experience is not None and job.max_experience is not None:
        if job.max_experience < job.min_experience:
            errors['max_experience'] = 'Maximum experience cannot be less than minimum experience.'

    return errors

def validate_publish(job):
    errors = validate_job_fields(job)

    if job.department_id:
        reviewers = job.department.reviewers
        if not isinstance(reviewers, list) or not any(
            isinstance(reviewer, dict) and str(reviewer.get('email') or '').strip()
            for reviewer in reviewers
        ):
            errors['department'] = 'The selected SBU has no valid assigned reviewers.'

    return errors

class IJPAuthenticatedView(APIView):
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]

class JobVacancyListCreateView(IJPAuthenticatedView):
    def get(self, request):
        is_admin = is_ijp_admin(request.user)
        jobs = JobVacancy.objects.select_related('department', 'posted_by').order_by('-created_at')

        if not is_admin:
            jobs = jobs.filter(status__in=['OPEN', 'CLOSED'])

        state = request.query_params.get('status')
        department = request.query_params.get('department')
        employment_type = request.query_params.get('employment_type')
        location = request.query_params.get('location')
        search = request.query_params.get('search')

        if state:
            jobs = jobs.filter(status=state.upper())
        if department:
            jobs = jobs.filter(department_id=department)
        if employment_type:
            jobs = jobs.filter(employment_type=employment_type.upper())
        if location:
            jobs = jobs.filter(location__icontains=location)
        if search:
            jobs = jobs.filter(Q(job_title__icontains=search) | Q(job_description__icontains=search))

        serializer_class = JobVacancySerializer if is_admin else EmployeeJobVacancySerializer
        return Response(serializer_class(jobs, many=True).data)

    @transaction.atomic
    def post(self, request):
        denied = admin_required(request)
        if denied is not None:
            return denied

        data = request.data.copy()
        publish = data.pop('publish', False)

        if isinstance(publish, list):
            publish = publish[0] if publish else False

        if publish not in [True, False]:
            return Response({'publish': 'Must be a boolean value.'}, status=400)

        data.setdefault('job_title', '')
        data.setdefault('job_description', '')
        data.setdefault('work_experience', '')

        serializer = JobVacancySerializer(data=data)
        serializer.is_valid(raise_exception=True)

        job = JobVacancy(**serializer.validated_data)
        errors = validate_publish(job) if publish else validate_job_fields(job)

        if errors:
            return Response(errors, status=400)

        job = serializer.save(
            status='OPEN' if publish else 'DRAFT',
            posted_by=request.user,
            published_at=timezone.now() if publish else None
        )

        record_job_history(
            job, 'CREATED', request.user,
            previous_status=None, new_status=job.status
        )

        if publish:
            record_job_history(
                job, 'PUBLISHED', request.user,
                previous_status='DRAFT', new_status='OPEN'
            )

            Notification.objects.create(
                notification_type='NEW_JOB',
                job_posting=job,
                title=f'New Job Opening: {job.job_title}',
                message=f'A new {job.employment_type.lower().replace("_", " ")} opportunity is available in {job.department.name}.'
            )

        return Response(JobVacancySerializer(job).data, status=201)

class JobVacancyDetailView(IJPAuthenticatedView):
    def get(self, request, job_id):
        job = get_object_or_404(
            JobVacancy.objects.select_related('department', 'posted_by'),
            job_id=job_id
        )

        if not is_ijp_admin(request.user) and job.status not in ['OPEN', 'CLOSED']:
            return Response({'error': 'Job posting not available.'}, status=404)

        serializer_class = JobPostingDetailSerializer if is_ijp_admin(request.user) else EmployeeJobVacancySerializer
        return Response(serializer_class(job).data)

class JobVacancyUpdateView(IJPAuthenticatedView):
    @transaction.atomic
    def put(self, request, job_id):
        denied = admin_required(request)
        if denied is not None:
            return denied

        job = get_locked_job(job_id, with_department=True)

        if job.status == 'ARCHIVED':
            return Response({'error': 'Archived postings cannot be edited.'}, status=400)

        protected = {
            'status', 'posted_by', 'published_at', 'closed_at',
            'archived_at', 'job_id', 'id'
        }

        if any(field in request.data for field in protected):
            return Response({
                'error': 'Posting lifecycle and audit fields cannot be updated directly.'
            }, status=400)

        previous = {
            field: getattr(job, field)
            for field in request.data.keys()
            if hasattr(job, field)
        }

        serializer = JobVacancySerializer(job, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        for field, value in serializer.validated_data.items():
            setattr(job, field, value)

        errors = validate_publish(job) if job.status == 'OPEN' else validate_job_fields(job)

        if errors:
            return Response(errors, status=400)

        job = serializer.save()

        changes = {}

        for field, old_value in previous.items():
            new_value = getattr(job, field)

            if old_value != new_value:
                changes[field] = {
                    'old': str(old_value) if old_value is not None else None,
                    'new': str(new_value) if new_value is not None else None
                }

        if changes:
            record_job_history(
                job, 'UPDATED', request.user, changes,
                previous_status=job.status, new_status=job.status
            )

        return Response({
            'message': 'Job updated successfully',
            'job': JobVacancySerializer(job).data
        })

class JobVacancyPublishView(IJPAuthenticatedView):
    @transaction.atomic
    def post(self, request, job_id):
        denied = admin_required(request)
        if denied is not None:
            return denied

        job = get_locked_job(job_id, with_department=True)

        if job.status != 'DRAFT':
            return Response({'error': 'Only draft postings can be published.'}, status=400)

        errors = validate_publish(job)

        if errors:
            return Response(errors, status=400)

        previous_status = job.status
        job.status = 'OPEN'
        job.published_at = timezone.now()
        job.closed_at = None
        job.save(update_fields=['status', 'published_at', 'closed_at', 'updated_at'])

        record_job_history(
            job, 'PUBLISHED', request.user,
            previous_status=previous_status, new_status=job.status
        )

        Notification.objects.create(
            notification_type='NEW_JOB',
            job_posting=job,
            title=f'New Job Opening: {job.job_title}',
            message=f'A new {job.employment_type.lower().replace("_", " ")} opportunity is available in {job.department.name}.'
        )

        return Response({
            'message': 'Job published successfully',
            'job': JobVacancySerializer(job).data
        })

class JobVacancyCloseView(IJPAuthenticatedView):
    @transaction.atomic
    def post(self, request, job_id):
        denied = admin_required(request)
        if denied is not None:
            return denied

        job = get_locked_job(job_id)

        if job.status != 'OPEN':
            return Response({'error': 'Only open postings can be closed.'}, status=400)

        previous_status = job.status
        job.status = 'CLOSED'
        job.closed_at = timezone.now()
        job.save(update_fields=['status', 'closed_at', 'updated_at'])

        record_job_history(
            job, 'CLOSED', request.user,
            previous_status=previous_status, new_status=job.status
        )

        return Response({
            'message': 'Job closed successfully',
            'job': JobVacancySerializer(job).data
        })

class JobVacancyReopenView(IJPAuthenticatedView):
    @transaction.atomic
    def post(self, request, job_id):
        denied = admin_required(request)
        if denied is not None:
            return denied

        job = get_locked_job(job_id, with_department=True)

        if job.status != 'CLOSED':
            return Response({'error': 'Only closed postings can be reopened.'}, status=400)

        errors = validate_publish(job)

        if errors:
            return Response(errors, status=400)

        previous_status = job.status
        job.status = 'OPEN'
        job.closed_at = None
        job.save(update_fields=['status', 'closed_at', 'updated_at'])

        record_job_history(
            job, 'REOPENED', request.user,
            previous_status=previous_status, new_status=job.status
        )

        return Response({
            'message': 'Job reopened successfully',
            'job': JobVacancySerializer(job).data
        })

class JobVacancyArchiveView(IJPAuthenticatedView):
    @transaction.atomic
    def post(self, request, job_id):
        denied = admin_required(request)
        if denied is not None:
            return denied

        job = get_locked_job(job_id)

        if job.status not in ['CLOSED', 'DRAFT']:
            return Response({'error': 'Close the job before archiving it.'}, status=400)

        previous_status = job.status
        job.status = 'ARCHIVED'
        job.archived_at = timezone.now()
        job.save(update_fields=['status', 'archived_at', 'updated_at'])

        record_job_history(
            job, 'ARCHIVED', request.user,
            previous_status=previous_status, new_status=job.status
        )

        return Response({
            'message': 'Job archived successfully',
            'job': JobVacancySerializer(job).data
        })

class JobVacancyDeleteView(IJPAuthenticatedView):
    def delete(self, request, job_id):
        denied = admin_required(request)
        if denied is not None:
            return denied

        return Response({
            'error': 'Permanent deletion is disabled. Close and archive the posting instead.'
        }, status=400)

class JobApplicationCreateView(IJPAuthenticatedView):
    def post(self, request, job_id):
        return Response({
            'error': 'Direct applications are disabled. Please use the IJP referral form.'
        }, status=400)

class JobApplicantListView(IJPAuthenticatedView):
    def get(self, request, job_id):
        denied = admin_required(request)
        if denied is not None:
            return denied

        job = get_object_or_404(JobVacancy, job_id=job_id)
        applications = JobApplication.objects.filter(job=job)
        return Response(JobApplicationSerializer(applications, many=True).data)

class JobApplicationUpdateView(IJPAuthenticatedView):
    def put(self, request, applicant_id):
        denied = admin_required(request)
        if denied is not None:
            return denied

        application = get_object_or_404(JobApplication, applicant_id=applicant_id)
        serializer = JobApplicationSerializer(application, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response({
            'message': 'Application updated successfully',
            'application': serializer.data
        })

class JobApplicationDeleteView(IJPAuthenticatedView):
    def delete(self, request, applicant_id):
        denied = admin_required(request)
        if denied is not None:
            return denied

        return Response({
            'error': 'Legacy application deletion is disabled to preserve historical records.'
        }, status=400)

class UploadJobDescriptionView(IJPAuthenticatedView):
    def post(self, request):
        denied = admin_required(request)
        if denied is not None:
            return denied

        try:
            file_obj = request.FILES.get('file')

            if not file_obj:
                return Response({'error': 'No file provided.'}, status=400)

            if not file_obj.name.lower().endswith(('.pdf', '.doc', '.docx')):
                return Response({
                    'error': 'Only PDF, DOC and DOCX job descriptions are accepted.'
                }, status=400)

            if file_obj.size > 3 * 1024 * 1024:
                return Response({
                    'error': 'Job description file cannot exceed 3 MB.'
                }, status=400)

            file_name = f"job_descriptions/{uuid.uuid4().hex}_{sanitize_filename(file_obj.name)}"
            uploaded_url = upload_to_supabase(file_obj, file_name)

            if not uploaded_url:
                return Response({
                    'error': 'Job description upload failed.'
                }, status=500)

            return Response({
                'message': 'File uploaded successfully',
                'file_url': uploaded_url
            }, status=200)

        except Exception:
            logger.exception('Job description upload failed')
            return Response({'error': 'Job description upload failed.'}, status=500)

class UploadApplicantCVView(IJPAuthenticatedView):
    def post(self, request):
        denied = admin_required(request)
        if denied is not None:
            return denied

        try:
            file_obj = request.FILES.get('file')
            applicant_name = request.data.get('name')

            if not file_obj or not applicant_name:
                return Response({
                    'error': 'File and applicant name are required.'
                }, status=400)

            if file_obj.size > 5 * 1024 * 1024:
                return Response({'error': 'CV size cannot exceed 5MB.'}, status=400)

            if not file_obj.name.lower().endswith(('.pdf', '.doc', '.docx')):
                return Response({
                    'error': 'Only PDF, DOC, and DOCX files are accepted.'
                }, status=400)

            file_name = f"applicant_cvs/{uuid.uuid4().hex}_{sanitize_filename(applicant_name)}_{sanitize_filename(file_obj.name)}"
            uploaded_url = upload_to_supabase(file_obj, file_name)

            return Response({
                'message': 'CV uploaded successfully',
                'cv_url': uploaded_url
            }, status=200)

        except Exception:
            logger.exception('Applicant CV upload failed')
            return Response({'error': 'CV upload failed.'}, status=500)