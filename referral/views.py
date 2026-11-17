from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q
from django.utils.timezone import now
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.parsers import JSONParser
from api.models import Referral, User, SBU, Review, HREvaluation, JobVacancy, Department
from api.utils import send_dynamic_email, get_role_and_departments
from .serializers import ReferralSerializer, AcademicDetailsSerializer
from rest_framework.permissions import IsAuthenticated

from api.views import CookieJWTAuthentication

from django.utils import timezone

def get_academic_status(candidate_type):
    return 'PENDING' if candidate_type.endswith('_FRESHER') else 'NOT_REQUIRED'

def get_hr_user(emp_id):
    if not emp_id:
        return None
    try:
        user = User.objects.get(emp_id=emp_id)
    except User.DoesNotExist:
        return None
    sub_bu = str(getattr(user, 'sub_bu', '') or '').strip().casefold()
    hr_keywords = ['human resource', 'human resources', 'human resourse', 'human resourses', 'human resource management', 'human resources management']
    is_hr_by_sub_bu = sub_bu == 'hr' or any(keyword in sub_bu for keyword in hr_keywords)
    _, _, is_hr_by_role = get_role_and_departments(user.email)
    return user if (is_hr_by_sub_bu or is_hr_by_role) else None

def academic_details_response(referral):
    updated_by = referral.academic_details_updated_by
    return {
        'referral_id': referral.id,
        'candidate_name': referral.candidate_name,
        'candidate_email': referral.candidate_email,
        'candidate_phone': referral.candidate_phone,
        'candidate_type': referral.candidate_type,
        'cv_url': referral.cv_url,
        'submitted_at': referral.submitted_at,
        'current_status': referral.current_status,
        'referrer': {'emp_id': referral.referrer.emp_id, 'name': referral.referrer.name, 'email': referral.referrer.email},
        'referral_reason_type': referral.referral_reason_type,
        'additional_comment': referral.additional_comment,
        'academic_details_status': referral.academic_details_status,
        'is_academic_locked': referral.academic_details_status == 'COMPLETED',
        'academic_details': {'tenth_percentage': referral.tenth_percentage, 'twelfth_percentage': referral.twelfth_percentage, 'graduation_cgpa': referral.graduation_cgpa},
        'academic_details_updated_at': referral.academic_details_updated_at,
        'academic_details_updated_by': {'emp_id': updated_by.emp_id, 'name': updated_by.name} if updated_by else None,
        'sbus': [{'name': sbu.name, 'email': sbu.email} for sbu in referral.sbus.all()],
        'job_posting': {'job_id': str(referral.job_posting.job_id), 'job_title': referral.job_posting.job_title} if referral.job_posting else None
    }

class SubmitReferralView(APIView):
    parser_classes = [JSONParser]
    def post(self, request):
        data = request.data
        emp_id = data.get('emp_id')
        candidate_name = data.get('candidate_name')
        candidate_type = data.get('candidate_type')
        referral_reason_type = data.get('referral_reason_type')
        sbu_emails = data.get('sbu_emails', [])
        cv_url = data.get('cv_url')
        additional_comment = data.get('additional_comment', '')
        candidate_email = (data.get('candidate_email') or '').strip()
        candidate_phone = (data.get('candidate_phone') or '').strip()
        if not all([emp_id, candidate_name, candidate_type, referral_reason_type, sbu_emails, cv_url]):
            return Response({'error': 'Missing required fields.'}, status=400)
        if candidate_type not in dict(Referral.CANDIDATE_TYPE_CHOICES):
            return Response({'error': 'Invalid candidate type.'}, status=400)
        if referral_reason_type not in dict(Referral.REFERRAL_REASON_CHOICES):
            return Response({'error': 'Invalid referral reason.'}, status=400)
        if not isinstance(sbu_emails, list) or not all(isinstance(email, str) for email in sbu_emails):
            return Response({'error': 'sbu_emails must be a list of email addresses.'}, status=400)
        if candidate_email:
            try:
                validate_email(candidate_email)
            except ValidationError:
                return Response({'error': 'Invalid candidate email address.'}, status=400)
        if len(candidate_phone) > 20:
            return Response({'error': 'Candidate phone number is too long.'}, status=400)
        try:
            user = User.objects.get(emp_id=emp_id)
        except User.DoesNotExist:
            return Response({'error': 'User not found.'}, status=404)
        matched_sbus = list(SBU.objects.filter(email__in=sbu_emails))
        if not matched_sbus:
            return Response({'error': 'No matching SBUs found.'}, status=400)
        academic_status = get_academic_status(candidate_type)
        with transaction.atomic():
            referral = Referral.objects.create(referrer=user, candidate_name=candidate_name, candidate_email=candidate_email or None, candidate_phone=candidate_phone or None, candidate_type=candidate_type, referral_reason_type=referral_reason_type, cv_url=cv_url, current_status='PENDING_REVIEW', academic_details_status=academic_status, additional_comment=additional_comment)
            referral.sbus.set(matched_sbus)
        if referral.is_experienced:
            send_dynamic_email(purpose='CV_TO_SBU', to_emails=['argang05@gmail.com'], context_data={'candidate_name': referral.candidate_name, 'portal_link': f'{settings.FRONTEND_BASE_URL}/review-cv'})
        return Response({'message': 'Referral submitted successfully.', 'referral_id': referral.id, 'academic_details_status': referral.academic_details_status, 'requires_academic_details': referral.is_fresher}, status=201)


class SubmitIJPReferralView(APIView):
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def post(self, request):
        data = request.data
        job_id = data.get('job_id')
        candidate_name = str(data.get('candidate_name') or '').strip()
        candidate_type = data.get('candidate_type')
        cv_url = data.get('cv_url')
        additional_comment = data.get('additional_comment', '')
        candidate_email = str(data.get('candidate_email') or '').strip()
        candidate_phone = str(data.get('candidate_phone') or '').strip()

        if not all([job_id, candidate_name, candidate_type, cv_url]):
            return Response({'error': 'Job ID, candidate name, candidate type and CV are required.'}, status=400)

        if candidate_type not in dict(Referral.CANDIDATE_TYPE_CHOICES):
            return Response({'error': 'Invalid candidate type.'}, status=400)

        if candidate_email:
            try:
                validate_email(candidate_email)
            except ValidationError:
                return Response({'error': 'Invalid candidate email address.'}, status=400)

        if len(candidate_phone) > 20:
            return Response({'error': 'Candidate phone number is too long.'}, status=400)

        with transaction.atomic():
            try:
                job = JobVacancy.objects.select_for_update(
                    of=('self',)
                ).select_related('department').get(job_id=job_id)
            except (JobVacancy.DoesNotExist, ValidationError, ValueError):
                return Response({'error': 'Job posting not found.'}, status=404)

            if job.status != 'OPEN':
                return Response({'error': 'This job posting is not open for referrals.'}, status=400)

            if job.closing_date and job.closing_date < timezone.localdate():
                return Response({'error': 'The referral closing date has passed.'}, status=400)

            if job.employment_type == 'INTERNSHIP' and not candidate_type.startswith('INTERN_'):
                return Response({'error': 'This posting accepts internship candidates only.'}, status=400)

            if job.employment_type == 'FULL_TIME' and not candidate_type.startswith('FULL_TIME_'):
                return Response({'error': 'This posting accepts full-time candidates only.'}, status=400)

            if not job.department_id:
                return Response({'error': 'This posting has no assigned SBU.'}, status=400)

            reviewers = job.department.reviewers

            if not isinstance(reviewers, list):
                return Response({'error': 'No reviewers are configured for this SBU.'}, status=400)

            reviewer_emails = {
                str(reviewer.get('email') or '').strip().lower()
                for reviewer in reviewers
                if isinstance(reviewer, dict) and reviewer.get('email')
            }

            if not reviewer_emails:
                return Response({'error': 'No valid reviewer emails found.'}, status=400)

            matched_sbus = [
                sbu for sbu in SBU.objects.all()
                if sbu.email and sbu.email.strip().lower() in reviewer_emails
            ]

            if not matched_sbus:
                return Response({'error': 'No registered SBU reviewers matched this posting.'}, status=400)

            referral = Referral.objects.create(
                referrer=request.user,
                job_posting=job,
                candidate_name=candidate_name,
                candidate_email=candidate_email or None,
                candidate_phone=candidate_phone or None,
                candidate_type=candidate_type,
                referral_reason_type='DIRECT_ROLE_FIT',
                cv_url=cv_url,
                current_status='PENDING_REVIEW',
                academic_details_status=get_academic_status(candidate_type),
                additional_comment=additional_comment
            )

            referral.sbus.set(matched_sbus)

        if referral.is_experienced:
            try:
                send_dynamic_email(
                    purpose='CV_TO_SBU',
                    to_emails=['argang05@gmail.com'],
                    context_data={
                        'candidate_name': referral.candidate_name,
                        'portal_link': f'{settings.FRONTEND_BASE_URL}/review-cv'
                    }
                )
            except Exception as exc:
                print(f'IJP referral created, but email notification failed: {exc}')

        return Response({
            'message': 'IJP referral submitted successfully.',
            'referral_id': referral.id,
            'job_posting': {
                'job_id': str(job.job_id),
                'job_title': job.job_title,
                'department': job.department.name,
                'location': job.location,
                'employment_type': job.employment_type
            },
            'academic_details_status': referral.academic_details_status,
            'requires_academic_details': referral.is_fresher
        }, status=201)


class MyReferralsView(APIView):
    permission_classes = [AllowAny]
    def get(self, request):
        emp_id = request.query_params.get('emp_id')
        if not emp_id:
            return Response({'error': 'Missing emp_id'}, status=400)
        try:
            user = User.objects.get(emp_id=emp_id)
        except User.DoesNotExist:
            return Response({'error': 'User not found'}, status=404)
        referrals = Referral.objects.filter(referrer=user).select_related('referrer', 'academic_details_updated_by', 'job_posting', 'job_posting__department').prefetch_related('sbus').order_by('-submitted_at')
        data = []
        for r in referrals:
            latest_review = Review.objects.filter(referral=r).select_related('reviewer').order_by('-id').first()
            latest_eval = HREvaluation.objects.filter(referral=r, evaluation_status='COMPLETED').select_related('updated_by', 'finalized_by').order_by('-finalized_at', '-id').first()
            is_fresher = r.candidate_type in ['INTERN_FRESHER', 'FULL_TIME_FRESHER']
            is_academic_locked = is_fresher and r.academic_details_status == 'COMPLETED'
            if latest_eval:
                workflow_stage = 'COMPLETED'
            elif r.current_status == 'REJECTED':
                workflow_stage = 'SBU_REJECTED'
            elif latest_review and latest_review.decision == 'CONSIDERED':
                workflow_stage = 'HR_EVALUATION'
            elif is_fresher and not is_academic_locked:
                workflow_stage = 'ACADEMIC_DETAILS'
            else:
                workflow_stage = 'SBU_REVIEW'
            data.append({
                'id': r.id,
                'candidate_name': r.candidate_name,
                'candidate_type': r.candidate_type,
                'candidate_email': r.candidate_email,
                'candidate_phone': r.candidate_phone,
                'referral_reason_type': r.referral_reason_type,
                'submitted_at': r.submitted_at,
                'current_status': r.current_status,
                'workflow_stage': workflow_stage,
                'cv_url': r.cv_url,
                'sbus': [{'name': s.name, 'email': s.email} for s in r.sbus.all()],
                'additional_comment': r.additional_comment,
                'rejection_stage': r.rejection_stage,
                'rejection_reason': r.rejection_reason,
                'academic_details_status': r.academic_details_status,
                'is_academic_locked': is_academic_locked,
                'academic_details': {'tenth_percentage': r.tenth_percentage, 'twelfth_percentage': r.twelfth_percentage, 'graduation_cgpa': r.graduation_cgpa} if is_academic_locked else None,
                'tenth_percentage': r.tenth_percentage if is_academic_locked else None,
                'twelfth_percentage': r.twelfth_percentage if is_academic_locked else None,
                'graduation_cgpa': r.graduation_cgpa if is_academic_locked else None,
                'academic_details_updated_at': r.academic_details_updated_at if is_academic_locked else None,
                'academic_details_updated_by': {'emp_id': r.academic_details_updated_by.emp_id, 'name': r.academic_details_updated_by.name} if is_academic_locked and r.academic_details_updated_by else None,
                'referrer': {'emp_id': r.referrer.emp_id, 'name': r.referrer.name, 'email': r.referrer.email},
                'considered_at': latest_review.reviewed_at if latest_review else None,
                'final_at': latest_eval.finalized_at if latest_eval else None,
                'review': {'decision': latest_review.decision, 'comment': latest_review.comment, 'reviewed_at': latest_review.reviewed_at, 'reviewed_by': latest_review.reviewer.name if latest_review.reviewer else 'Unknown Reviewer'} if latest_review else None,
                'hr_evaluation': {'stage': latest_eval.stage, 'status': latest_eval.status, 'comment': latest_eval.comment, 'updated_at': latest_eval.updated_at, 'updated_by': latest_eval.updated_by.name if latest_eval.updated_by else 'Unknown HR Employee', 'evaluation_status': latest_eval.evaluation_status, 'finalized_at': latest_eval.finalized_at, 'finalized_by': {'emp_id': latest_eval.finalized_by.emp_id, 'name': latest_eval.finalized_by.name, 'email': latest_eval.finalized_by.email} if latest_eval.finalized_by else None, 'offer_released': latest_eval.offer_released, 'offer_outcome': latest_eval.offer_outcome, 'joining_date': latest_eval.joining_date, 'is_locked': latest_eval.is_locked} if latest_eval else None,
                'offer_released': latest_eval.offer_released if latest_eval else False,
                'offer_outcome': latest_eval.offer_outcome if latest_eval else None,
                'joining_date': latest_eval.joining_date if latest_eval else None,
                'is_hr_finalized': bool(latest_eval),
                'job_posting': {'job_id': str(r.job_posting.job_id), 'job_title': r.job_posting.job_title, 'department': r.job_posting.department.name if r.job_posting.department else None, 'location': r.job_posting.location, 'employment_type': r.job_posting.employment_type, 'status': r.job_posting.status} if r.job_posting else None
            })
        return Response(data, status=200)

class UpdateReferralView(APIView):
    parser_classes = [JSONParser]
    permission_classes = [AllowAny]
    def put(self, request, referral_id):
        try:
            referral = Referral.objects.get(id=referral_id)
        except Referral.DoesNotExist:
            return Response({'error': 'Referral not found.'}, status=404)
        emp_id = request.data.get('emp_id')
        if str(referral.referrer.emp_id) != str(emp_id):
            return Response({'error': 'Unauthorized'}, status=403)
        referral.candidate_name = request.data.get('candidate_name', referral.candidate_name)
        if 'candidate_email' in request.data:
            candidate_email = (request.data.get('candidate_email') or '').strip()
            if candidate_email:
                try:
                    validate_email(candidate_email)
                except ValidationError:
                    return Response({'error': 'Invalid candidate email address.'}, status=400)
            referral.candidate_email = candidate_email or None
        if 'candidate_phone' in request.data:
            candidate_phone = (request.data.get('candidate_phone') or '').strip()
            if len(candidate_phone) > 20:
                return Response({'error': 'Candidate phone number is too long.'}, status=400)
            referral.candidate_phone = candidate_phone or None
        new_candidate_type = request.data.get('candidate_type', referral.candidate_type)
        if new_candidate_type not in dict(Referral.CANDIDATE_TYPE_CHOICES):
            return Response({'error': 'Invalid candidate type.'}, status=400)
        if new_candidate_type != referral.candidate_type:
            if referral.academic_details_status == 'COMPLETED':
                return Response({'error': 'Candidate type cannot be changed because academic details have been permanently finalized.'}, status=403)
            if Review.objects.filter(referral=referral).exists() or HREvaluation.objects.filter(referral=referral).exists():
                return Response({'error': 'Candidate type cannot be changed after evaluation has started.'}, status=400)
            if referral.job_posting:
                expected_prefix = 'INTERN_' if referral.job_posting.employment_type == 'INTERNSHIP' else 'FULL_TIME_'
                if not new_candidate_type.startswith(expected_prefix):
                    return Response({'error': 'Candidate type must match the linked job posting employment type.'}, status=400)
            referral.candidate_type = new_candidate_type
            referral.academic_details_status = get_academic_status(new_candidate_type)
            referral.tenth_percentage = None
            referral.twelfth_percentage = None
            referral.graduation_cgpa = None
            referral.academic_details_updated_at = None
            referral.academic_details_updated_by = None
        new_reason = request.data.get('referral_reason_type', referral.referral_reason_type)
        if new_reason not in dict(Referral.REFERRAL_REASON_CHOICES):
            return Response({'error': 'Invalid referral reason.'}, status=400)
        referral.referral_reason_type = new_reason
        referral.additional_comment = request.data.get('additional_comment', referral.additional_comment)
        cv_url = request.data.get('cv_url')
        if cv_url:
            referral.cv_url = cv_url
        referral.save()
        if referral.is_experienced or referral.academic_details_status == 'COMPLETED':
            send_dynamic_email(purpose='CV_UPDATED_SBU', to_emails=['abgang05@gmail.com'], context_data={'candidate_name': referral.candidate_name, 'portal_link': f'{settings.FRONTEND_BASE_URL}/review-cv'})
        return Response({'message': 'Referral updated successfully.', 'academic_details_status': referral.academic_details_status}, status=200)

class DeleteReferralView(APIView):
    permission_classes = [AllowAny]
    def delete(self, request, referral_id):
        try:
            referral = Referral.objects.get(id=referral_id)
        except Referral.DoesNotExist:
            return Response({'error': 'Referral not found.'}, status=404)
        emp_id = request.query_params.get('emp_id')
        if str(referral.referrer.emp_id) != str(emp_id):
            return Response({'error': 'Unauthorized'}, status=403)
        candidate_name = referral.candidate_name
        review_ready = referral.is_experienced or referral.academic_details_status == 'COMPLETED'
        referral.delete()
        if review_ready:
            send_dynamic_email(purpose='CV_DELETED_SBU', to_emails=['abgang05@gmail.com'], context_data={'candidate_name': candidate_name})
        return Response(status=204)

class AcademicDetailsListView(APIView):
    parser_classes = [JSONParser]
    permission_classes = [AllowAny]
    def get(self, request):
        emp_id = request.query_params.get('emp_id')
        hr_user = get_hr_user(emp_id)
        if not hr_user:
            return Response({'error': 'HR access required.'}, status=403)
        academic_status = request.query_params.get('status', 'ACTIVE').upper()
        allowed_statuses = ['PENDING', 'DRAFT', 'COMPLETED', 'ACTIVE', 'ALL']
        if academic_status not in allowed_statuses:
            return Response({'error': 'Invalid academic status filter.'}, status=400)
        referrals = Referral.objects.filter(candidate_type__in=['INTERN_FRESHER', 'FULL_TIME_FRESHER']).select_related('referrer', 'academic_details_updated_by').prefetch_related('sbus')
        if academic_status == 'ACTIVE':
            referrals = referrals.filter(academic_details_status__in=['PENDING', 'DRAFT'])
        elif academic_status != 'ALL':
            referrals = referrals.filter(academic_details_status=academic_status)
        referrals = referrals.order_by('-submitted_at')
        return Response({'count': referrals.count(), 'results': [academic_details_response(referral) for referral in referrals]}, status=200)

class ReferralAcademicDetailsView(APIView):
    parser_classes = [JSONParser]
    permission_classes = [AllowAny]
    def get(self, request, referral_id):
        emp_id = request.query_params.get('emp_id')
        hr_user = get_hr_user(emp_id)
        if not hr_user:
            return Response({'error': 'HR access required.'}, status=403)
        try:
            referral = Referral.objects.select_related('referrer', 'academic_details_updated_by', 'job_posting').prefetch_related('sbus').get(id=referral_id)
        except Referral.DoesNotExist:
            return Response({'error': 'Referral not found.'}, status=404)
        if not referral.is_fresher:
            return Response({'error': 'Academic details are not required for experienced candidates.'}, status=400)
        return Response(academic_details_response(referral), status=200)
    def patch(self, request, referral_id):
        emp_id = request.data.get('emp_id')
        hr_user = get_hr_user(emp_id)
        if not hr_user:
            return Response({'error': 'HR access required.'}, status=403)
        action = request.data.get('action')
        if action not in ['SAVE_DRAFT', 'FINALIZE']:
            return Response({'error': 'Invalid action. Use SAVE_DRAFT or FINALIZE.'}, status=400)
        should_send_email = False
        candidate_name = None
        with transaction.atomic():
            try:
                referral = Referral.objects.select_for_update().get(id=referral_id)
            except Referral.DoesNotExist:
                return Response({'error': 'Referral not found.'}, status=404)
            if not referral.is_fresher:
                return Response({'error': 'Academic details are only applicable to freshers.'}, status=400)
            if referral.academic_details_status == 'COMPLETED':
                return Response({'error': 'Academic details have been finalized and permanently locked. Further modifications are not permitted.'}, status=403)
            if referral.current_status != 'PENDING_REVIEW':
                return Response({'error': 'Academic details cannot be modified after the referral status changes.'}, status=400)
            if Review.objects.filter(referral=referral).exists():
                return Response({'error': 'Academic details cannot be modified after SBU review begins.'}, status=400)
            if HREvaluation.objects.filter(referral=referral).exists():
                return Response({'error': 'Academic details cannot be modified after HR evaluation begins.'}, status=400)
            serializer = AcademicDetailsSerializer(instance=referral, data=request.data, partial=True, context={'action': action})
            if not serializer.is_valid():
                return Response(serializer.errors, status=400)
            new_status = 'DRAFT' if action == 'SAVE_DRAFT' else 'COMPLETED'
            serializer.save(academic_details_status=new_status, academic_details_updated_at=now(), academic_details_updated_by=hr_user)
            should_send_email = action == 'FINALIZE'
            candidate_name = referral.candidate_name
        if should_send_email:
            try:
                send_dynamic_email(purpose='CV_TO_SBU', to_emails=['argang05@gmail.com'], context_data={'candidate_name': candidate_name, 'portal_link': f'{settings.FRONTEND_BASE_URL}/review-cv'})
            except Exception as exc:
                print(f'Academic details finalized, but notification failed: {exc}')
        referral.refresh_from_db()
        message = 'Academic details saved as draft successfully.' if action == 'SAVE_DRAFT' else 'Academic details finalized and permanently locked successfully.'
        return Response({'message': message, 'referral_id': referral.id, 'academic_details_status': referral.academic_details_status, 'is_academic_locked': referral.academic_details_status == 'COMPLETED', 'academic_details': {'tenth_percentage': referral.tenth_percentage, 'twelfth_percentage': referral.twelfth_percentage, 'graduation_cgpa': referral.graduation_cgpa}, 'updated_at': referral.academic_details_updated_at, 'updated_by': {'emp_id': hr_user.emp_id, 'name': hr_user.name}}, status=200)