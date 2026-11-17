from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from api.models import (
    Department, SBU, EmailTemplate, User, Referral,
    Review, HREvaluation, HREvaluationHistory
)
from api.serializers import DepartmentSerializer, SBUSerializer, EmailTemplateSerializer
from django.db import transaction, connection
from django.db.models import Prefetch, Q
from django.core.exceptions import PermissionDenied
from django.db.models.deletion import ProtectedError, RestrictedError
import json
from rest_framework.permissions import BasePermission

from api.views import CookieJWTAuthentication

ADMIN_EMAILS = {

    "abhishek.ganguly@tor.ai",

    "admin2@gmail.com",

    "admin3@gmail.com"

}

# ==========================================================
# EXISTING DEPARTMENT MANAGEMENT
# ==========================================================

class DepartmentListView(APIView):
    def get(self, request):
        departments = Department.objects.all()
        serializer = DepartmentSerializer(departments, many=True)
        return Response(serializer.data)

class DepartmentCreateView(APIView):
    def post(self, request):
        serializer = DepartmentSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)

class DepartmentUpdateView(APIView):
    def put(self, request, department_id):
        try:
            department = Department.objects.get(id=department_id)
        except Department.DoesNotExist:
            return Response({"error": "Department not found"}, status=404)

        new_reviewers = request.data.get("reviewers", [])
        old_reviewers = department.reviewers or []
        department.reviewers = new_reviewers
        department.save()

        new_emails = {r["email"] for r in new_reviewers if "email" in r}
        old_emails = {r["email"] for r in old_reviewers if "email" in r}

        for reviewer in new_reviewers:
            email = reviewer.get("email")
            name = reviewer.get("name")
            if not email:
                continue

            sbu, created = SBU.objects.get_or_create(
                email=email,
                defaults={
                    "name": name or email.split("@")[0],
                    "departments": [department.name]
                }
            )
            if not created and department.name not in sbu.departments:
                sbu.departments.append(department.name)
                sbu.save()

        removed_emails = old_emails - new_emails
        for email in removed_emails:
            try:
                sbu = SBU.objects.get(email=email)
                if department.name in sbu.departments:
                    sbu.departments.remove(department.name)
                    sbu.save()
            except SBU.DoesNotExist:
                continue

        return Response({"message": "Reviewers and SBUs synced"}, status=status.HTTP_200_OK)

# ==========================================================
# EXISTING SBU MANAGEMENT
# ==========================================================

class SBUListCreateView(APIView):
    def get(self, request):
        sbus = SBU.objects.all()
        serializer = SBUSerializer(sbus, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = SBUSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)

class SBUDetailView(APIView):
    def put(self, request, email):
        try:
            sbu = SBU.objects.filter(email__iexact=email).first()
            if not sbu:
                return Response({"error": "SBU not found"}, status=404)
        except Exception:
            return Response({"error": "Error fetching SBU"}, status=500)

        new_email = request.data.get("email", sbu.email)
        new_name = request.data.get("name", sbu.name)
        incoming_departments = request.data.get("departments", None)
        replace_flag = request.data.get("replace_departments", False)

        if new_email.lower() != sbu.email.lower():
            if SBU.objects.filter(email__iexact=new_email).exclude(pk=sbu.pk).exists():
                return Response({"error": "Email already exists."}, status=400)

        try:
            with transaction.atomic():
                if new_email != sbu.email:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "UPDATE api_sbu SET email = %s WHERE id = %s",
                            [new_email, str(sbu.id)]
                        )
                    sbu = SBU.objects.get(pk=sbu.pk)

                sbu.name = new_name

                if incoming_departments is not None:
                    if replace_flag:
                        sbu.departments = incoming_departments
                    else:
                        existing = sbu.departments or []
                        if not isinstance(existing, list):
                            try:
                                existing = json.loads(existing)
                            except (TypeError, ValueError):
                                existing = []
                        merged = list(dict.fromkeys([*existing, *incoming_departments]))
                        sbu.departments = merged

                sbu.save()

            return Response({"message": "SBU updated"}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=500)

    def delete(self, request, email):
        department_id = request.query_params.get("department_id")
        if not department_id:
            return Response({"error": "Department ID required"}, status=400)

        try:
            sbu = SBU.objects.get(email=email)
            department = Department.objects.get(id=department_id)
        except (SBU.DoesNotExist, Department.DoesNotExist):
            return Response({"error": "SBU or Department not found"}, status=404)

        updated_reviewers = [r for r in department.reviewers if r.get("email") != email]
        department.reviewers = updated_reviewers
        department.save()

        sbu.departments = [d for d in sbu.departments if d != department.name]
        if sbu.departments:
            sbu.save()
        else:
            sbu.delete()

        return Response({"message": "Reviewer removed from department and SBU updated"})

# ==========================================================
# EXISTING EMAIL TEMPLATE MANAGEMENT
# ==========================================================

class EmailTemplateListView(APIView):
    def get(self, request):
        templates = EmailTemplate.objects.all()
        serializer = EmailTemplateSerializer(templates, many=True)
        return Response(serializer.data)

class EmailTemplateDetailView(APIView):
    def get(self, request, purpose):
        try:
            template = EmailTemplate.objects.get(purpose=purpose)
        except EmailTemplate.DoesNotExist:
            return Response({"error": "Template not found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = EmailTemplateSerializer(template)
        return Response(serializer.data)

    def put(self, request, purpose):
        try:
            template = EmailTemplate.objects.get(purpose=purpose)
        except EmailTemplate.DoesNotExist:
            return Response({"error": "Template not found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = EmailTemplateSerializer(template, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class SBUListView(APIView):
    def get(self, request):
        sbus = SBU.objects.all().values("id", "name", "email")
        return Response(list(sbus), status=status.HTTP_200_OK)

# ==========================================================
# COMPLETED REFERRALS - ADMIN AUTHORIZATION
# ==========================================================

class AdminOnlyPermission(BasePermission):
    message = "Only authorized administrators can access completed referrals."
    def has_permission(self, request, view):
        user = request.user
        email = str(getattr(user, "email", "") or "").strip().lower()
        return bool(
            getattr(user, "is_authenticated", False)
            and getattr(user, "is_active", False)
            and email in ADMIN_EMAILS
        )

# ==========================================================
# COMPLETED REFERRALS - SERIALIZATION HELPERS
# ==========================================================

def serialize_completed_review(review):
    if review is None:
        return None
    reviewer = review.reviewer
    return {
        "id": review.id,
        "decision": review.decision,
        "comment": review.comment,
        "reviewed_at": review.reviewed_at,
        "reviewed_by": {
            "emp_id": reviewer.emp_id,
            "name": reviewer.name,
            "email": reviewer.email
        } if reviewer else None
    }


def serialize_completed_hr_history(history):
    updated_by = history.updated_by
    return {
        "id": history.id,
        "revision": history.revision,
        "stage": history.stage,
        "status": history.status,
        "comment": history.comment,
        "action": history.action,
        "created_at": history.created_at,
        "updated_by": {
            "emp_id": updated_by.emp_id,
            "name": updated_by.name,
            "email": updated_by.email
        } if updated_by else None,
        "offer_released": history.offer_released,
        "offer_outcome": history.offer_outcome,
        "joining_date": history.joining_date
    }


def serialize_completed_hr_evaluation(evaluation):
    if evaluation is None:
        return None
    updated_by = evaluation.updated_by
    finalized_by = evaluation.finalized_by
    return {
        "id": evaluation.id,
        "stage": evaluation.stage,
        "status": evaluation.status,
        "comment": evaluation.comment,
        "updated_at": evaluation.updated_at,
        "updated_by": updated_by.name if updated_by else "Unknown HR Employee",
        "evaluation_status": evaluation.evaluation_status,
        "is_locked": evaluation.is_locked,
        "finalized_at": evaluation.finalized_at,
        "finalized_by": {
            "emp_id": finalized_by.emp_id,
            "name": finalized_by.name,
            "email": finalized_by.email
        } if finalized_by else None,
        "offer_released": evaluation.offer_released,
        "offer_outcome": evaluation.offer_outcome,
        "joining_date": evaluation.joining_date
    }


def serialize_completed_referral(referral, include_history=False):
    evaluations = getattr(referral, "prefetched_hr_evaluations", [])
    reviews = getattr(referral, "prefetched_reviews", [])
    completed_evaluations = [
        evaluation for evaluation in evaluations
        if evaluation.evaluation_status == "COMPLETED"
    ]
    evaluation = (
        max(
            completed_evaluations,
            key=lambda item: (item.finalized_at is not None, item.finalized_at, item.id)
        )
        if completed_evaluations else None
    )
    if evaluation is None:
        return None

    latest_review = reviews[0] if reviews else None
    is_fresher = referral.is_fresher
    is_academic_completed = (
        is_fresher and referral.academic_details_status == "COMPLETED"
    )
    academic_details = {
        "tenth_percentage": referral.tenth_percentage,
        "twelfth_percentage": referral.twelfth_percentage,
        "graduation_cgpa": referral.graduation_cgpa
    } if is_academic_completed else None
    finalized_by = evaluation.finalized_by

    result = {
        "id": referral.id,
        "candidate_name": referral.candidate_name,
        "candidate_email": referral.candidate_email,
        "candidate_phone": referral.candidate_phone,
        "candidate_type": referral.candidate_type,
        "submitted_at": referral.submitted_at,
        "referral_reason_type": referral.referral_reason_type,
        "current_status": referral.current_status,
        "rejection_stage": referral.rejection_stage,
        "rejection_reason": referral.rejection_reason,
        "cv_url": referral.cv_url,
        "additional_comment": referral.additional_comment,
        "sbus": [
            {"name": sbu.name, "email": sbu.email}
            for sbu in referral.sbus.all()
        ],
        "referrer": {
            "emp_id": referral.referrer.emp_id,
            "name": referral.referrer.name,
            "email": referral.referrer.email
        } if referral.referrer else None,
        "academic_details_status": referral.academic_details_status,
        "is_academic_locked": is_academic_completed,
        "academic_details": academic_details,
        "tenth_percentage": referral.tenth_percentage if is_academic_completed else None,
        "twelfth_percentage": referral.twelfth_percentage if is_academic_completed else None,
        "graduation_cgpa": referral.graduation_cgpa if is_academic_completed else None,
        "academic_details_updated_at": (
            referral.academic_details_updated_at if is_academic_completed else None
        ),
        "review": serialize_completed_review(latest_review),
        "hr_evaluation": serialize_completed_hr_evaluation(evaluation),
        "hr_evaluation_status": evaluation.evaluation_status,
        "is_hr_locked": evaluation.is_locked,
        "hr_evaluation_started": True,
        "is_finalized": True,
        "can_edit_sbu_review": False,
        "finalized_at": evaluation.finalized_at,
        "finalized_by": {
            "emp_id": finalized_by.emp_id,
            "name": finalized_by.name,
            "email": finalized_by.email
        } if finalized_by else None,
        "considered_at": (
            latest_review.reviewed_at
            if latest_review and latest_review.decision == "CONSIDERED"
            else None
        ),
        "final_at": evaluation.finalized_at,

        # Offer and joining details
        "offer_released": evaluation.offer_released,
        "offer_outcome": evaluation.offer_outcome,
        "joining_date": evaluation.joining_date
    }

    if include_history:
        history = getattr(evaluation, "prefetched_history", [])
        result["review_history"] = [
            serialize_completed_review(review) for review in reviews
        ]
        result["hr_evaluation_history"] = [
            serialize_completed_hr_history(item) for item in history
        ]
        result["hr_evaluation_version"] = (
            history[0].revision if history else 0
        )

    return result

# ==========================================================
# COMPLETED REFERRALS - QUERY HELPERS
# ==========================================================

def get_completed_referrals_queryset(include_history=False):
    evaluation_queryset = HREvaluation.objects.filter(
        evaluation_status="COMPLETED"
    ).select_related("updated_by", "finalized_by").order_by(
        "-finalized_at", "-id"
    )
    if include_history:
        evaluation_queryset = evaluation_queryset.prefetch_related(
            Prefetch(
                "history",
                queryset=HREvaluationHistory.objects.select_related(
                    "updated_by"
                ).order_by("-revision"),
                to_attr="prefetched_history"
            )
        )

    queryset = Referral.objects.filter(
        hrevaluation__evaluation_status="COMPLETED"
    ).distinct().select_related(
        "referrer", "academic_details_updated_by"
    ).prefetch_related(
        "sbus",
        Prefetch(
            "review_set",
            queryset=Review.objects.select_related(
                "reviewer"
            ).order_by("-id"),
            to_attr="prefetched_reviews"
        ),
        Prefetch(
            "hrevaluation_set",
            queryset=evaluation_queryset,
            to_attr="prefetched_hr_evaluations"
        )
    ).order_by("-hrevaluation__finalized_at", "-id")

    return queryset

# ==========================================================
# COMPLETED REFERRALS - LIST
# ==========================================================

class CompletedReferralsListView(APIView):
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [AdminOnlyPermission]

    def get(self, request):
        base_queryset = Referral.objects.filter(
            hrevaluation__evaluation_status="COMPLETED"
        ).distinct()
        summary = {
            "total_completed": base_queryset.count(),
            "selected": base_queryset.filter(
                hrevaluation__evaluation_status="COMPLETED",
                hrevaluation__status="ACCEPTED"
            ).distinct().count(),
            "rejected": base_queryset.filter(
                hrevaluation__evaluation_status="COMPLETED",
                hrevaluation__status="REJECTED"
            ).distinct().count()
        }
        queryset = get_completed_referrals_queryset()
        search = (request.query_params.get("search") or "").strip()
        decision = (request.query_params.get("decision") or "ALL").upper()
        if decision not in {"ALL", "ACCEPTED", "REJECTED"}:
            return Response({"error": "Invalid decision filter."}, status=400)

        if search:
            queryset = queryset.filter(
                Q(candidate_name__icontains=search) |
                Q(candidate_email__icontains=search) |
                Q(referrer__name__icontains=search) |
                Q(referrer__emp_id__icontains=search)
            )
        if decision != "ALL":
            queryset = queryset.filter(
                hrevaluation__evaluation_status="COMPLETED",
                hrevaluation__status=decision
            )

        results = [
            serialize_completed_referral(referral)
            for referral in queryset
        ]
        results = [item for item in results if item is not None]

        return Response({
            "count": len(results),
            "summary": summary,
            "results": results
        }, status=200)

# ==========================================================
# COMPLETED REFERRALS - DETAIL AND PERMANENT DELETION
# ==========================================================

class CompletedReferralDetailView(APIView):
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [AdminOnlyPermission]

    def get(self, request, referral_id):
        referral = get_completed_referrals_queryset(
            include_history=True
        ).filter(id=referral_id).first()
        if referral is None:
            return Response({"error": "Completed referral not found."}, status=404)
        return Response(
            serialize_completed_referral(referral, include_history=True),
            status=200
        )

    def delete(self, request, referral_id):
        confirmation = request.data.get("confirmation")
        candidate_name_confirmation = request.data.get("candidate_name")
        if confirmation != "DELETE":
            return Response({
                "error": "Deletion confirmation is required. Enter DELETE."
            }, status=400)
        if not isinstance(candidate_name_confirmation, str):
            return Response({
                "error": "Candidate name confirmation is required."
            }, status=400)

        try:
            with transaction.atomic():
                referral = Referral.objects.select_for_update().get(id=referral_id)
                is_completed = HREvaluation.objects.filter(
                    referral=referral,
                    evaluation_status="COMPLETED"
                ).exists()
                if not is_completed:
                    return Response({
                        "error": "Only completed referrals can be deleted from this module."
                    }, status=403)
                if candidate_name_confirmation.strip() != referral.candidate_name.strip():
                    return Response({
                        "error": "Candidate name does not match. Deletion cancelled."
                    }, status=400)

                deleted_name = referral.candidate_name
                deleted_id = referral.id
                referral.delete()

            return Response({
                "message": "Completed referral and its related database records permanently deleted.",
                "deleted_referral_id": deleted_id,
                "candidate_name": deleted_name
            }, status=200)

        except Referral.DoesNotExist:
            return Response({"error": "Referral not found."}, status=404)
        except (ProtectedError, RestrictedError):
            return Response({
                "error": "Referral cannot be deleted because protected related records exist."
            }, status=409)