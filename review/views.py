from django.conf import settings
from django.db import transaction
from django.db.models import Prefetch, Q
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from api.models import Referral, Review, User, HREvaluation
from api.utils import send_dynamic_email

# ==========================================================
# CONSTANTS
# ==========================================================
VALID_DECISIONS = {"CONSIDERED", "REJECTED"}
FINAL_STATUSES = {"FINAL_ACCEPTED", "FINAL_REJECTED"}
FRESHER_TYPES = {"INTERN_FRESHER", "FULL_TIME_FRESHER"}

# ==========================================================
# SHARED HELPERS
# ==========================================================
def serialize_review(review):
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

def serialize_final_hr_evaluation(evaluation):
    if evaluation is None or evaluation.evaluation_status != "COMPLETED":
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

def get_latest_review(referral):
    return Review.objects.filter(referral=referral).select_related("reviewer").order_by("-id").first()

def is_assigned_reviewer(referral, reviewer):
    reviewer_email = (reviewer.email or "").strip().lower()
    if not reviewer_email:
        return False
    return any(
        (sbu.email or "").strip().lower() == reviewer_email
        for sbu in referral.sbus.all()
    )

def has_hr_started(referral):
    return HREvaluation.objects.filter(referral=referral).exists()

def is_academic_ready(referral):
    if referral.candidate_type not in FRESHER_TYPES:
        return True
    return referral.academic_details_status == "COMPLETED"

def serialize_academic_details(referral):
    if referral.candidate_type not in FRESHER_TYPES or not is_academic_ready(referral):
        return None
    return {
        "tenth_percentage": referral.tenth_percentage,
        "twelfth_percentage": referral.twelfth_percentage,
        "graduation_cgpa": referral.graduation_cgpa
    }

def validate_review_payload(request):
    emp_id = request.data.get("emp_id")
    decision = request.data.get("decision")
    comment = request.data.get("comment")
    if not emp_id:
        return None, None, None, Response({"error": "emp_id is required."}, status=400)
    if decision not in VALID_DECISIONS:
        return None, None, None, Response({"error": "Invalid review decision."}, status=400)
    if not isinstance(comment, str) or not comment.strip():
        return None, None, None, Response({"error": "Review comment is required."}, status=400)
    return emp_id, decision, comment.strip(), None

def apply_review_decision(referral, decision, comment):
    if decision == "REJECTED":
        referral.current_status = "REJECTED"
        referral.rejection_stage = "SBU"
        referral.rejection_reason = comment
    elif decision == "CONSIDERED":
        referral.current_status = "CONSIDERED"
        referral.rejection_stage = None
        referral.rejection_reason = None
    referral.save(update_fields=["current_status", "rejection_stage", "rejection_reason"])

# ==========================================================
# EMAIL NOTIFICATIONS
# ==========================================================
def notify_review_change(referral, previous_decision, decision):
    try:
        if decision == "REJECTED":
            send_dynamic_email(
                purpose="CV_REJECTED_SBU",
                to_emails=["abgang05@gmail.com"],
                context_data={
                    "candidate_name": referral.candidate_name,
                    "portal_link": f"{settings.FRONTEND_BASE_URL}/",
                    "reason": referral.rejection_reason
                }
            )
            if previous_decision == "CONSIDERED":
                send_dynamic_email(
                    purpose="CV_REVOKED_BY_SBU",
                    to_emails=["abgang05@gmail.com"],
                    context_data={
                        "candidate_name": referral.candidate_name,
                        "portal_link": f"{settings.FRONTEND_BASE_URL}/hr-evaluation"
                    }
                )
        elif decision == "CONSIDERED":
            send_dynamic_email(
                purpose="CV_APPROVED_SBU",
                to_emails=["abgang05@gmail.com"],
                context_data={
                    "candidate_name": referral.candidate_name,
                    "portal_link": f"{settings.FRONTEND_BASE_URL}/"
                }
            )
            if previous_decision != "CONSIDERED":
                send_dynamic_email(
                    purpose="CV_TO_HR",
                    to_emails=["abgang05@gmail.com"],
                    context_data={
                        "candidate_name": referral.candidate_name,
                        "portal_link": f"{settings.FRONTEND_BASE_URL}/hr-evaluation"
                    }
                )
    except Exception as error:
        print("Review notification failed:", str(error))

# ==========================================================
# SHARED REVIEW SUBMISSION / REVISION LOGIC
# ==========================================================
def create_review_revision(request, referral_id, require_existing):
    emp_id, decision, comment, error = validate_review_payload(request)
    if error:
        return error

    if "expected_review_id" not in request.data:
        return Response({
            "error": "expected_review_id is required. Refresh the referral and try again."
        }, status=400)

    expected_review_id = request.data.get("expected_review_id")
    if expected_review_id is not None:
        try:
            expected_review_id = int(expected_review_id)
        except (TypeError, ValueError):
            return Response({"error": "Invalid expected_review_id."}, status=400)

    try:
        reviewer = User.objects.get(emp_id=emp_id)
    except User.DoesNotExist:
        return Response({"error": "Reviewer not found."}, status=404)

    with transaction.atomic():
        try:
            referral = Referral.objects.select_for_update().select_related("referrer").get(id=referral_id)
        except Referral.DoesNotExist:
            return Response({"error": "Referral not found."}, status=404)

        if not is_assigned_reviewer(referral, reviewer):
            return Response({
                "error": "You are not assigned as an SBU reviewer for this referral."
            }, status=403)

        if not is_academic_ready(referral):
            return Response({
                "error": "Academic details are not finalized. HR must complete and lock the candidate's academic records before SBU review.",
                "academic_details_status": referral.academic_details_status
            }, status=403)

        if has_hr_started(referral):
            return Response({
                "error": "HR evaluation has already started. SBU reviews can no longer be modified."
            }, status=403)

        if referral.current_status in FINAL_STATUSES:
            return Response({
                "error": "This referral has already been finalized by HR."
            }, status=403)

        latest_review = get_latest_review(referral)
        current_review_id = latest_review.id if latest_review else None

        if require_existing and latest_review is None:
            return Response({
                "error": "No existing review was found. Submit an initial review instead."
            }, status=409)

        if not require_existing and latest_review is not None:
            return Response({
                "error": "A review already exists. Refresh and use Revise SBU Review."
            }, status=409)

        if expected_review_id != current_review_id:
            return Response({
                "error": "Another reviewer has updated this referral. Refresh to see the latest decision before submitting.",
                "latest_review": serialize_review(latest_review)
            }, status=409)

        previous_decision = latest_review.decision if latest_review else None
        new_review = Review.objects.create(
            referral=referral,
            reviewer=reviewer,
            decision=decision,
            comment=comment
        )
        apply_review_decision(referral, decision, comment)
        transaction.on_commit(
            lambda: notify_review_change(referral, previous_decision, decision)
        )

    return Response({
        "message": "Review revised successfully." if require_existing else "Review submitted successfully.",
        "review": serialize_review(new_review)
    }, status=200 if require_existing else 201)

# ==========================================================
# GET: REFERRALS ASSIGNED TO SBU REVIEWER
# ==========================================================
class CVsForReview(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        emp_id = request.query_params.get("emp_id")
        if not emp_id:
            return Response({"error": "emp_id is required."}, status=400)

        try:
            user = User.objects.get(emp_id=emp_id)
        except User.DoesNotExist:
            return Response({"error": "User not found."}, status=404)

        review_queryset = Review.objects.select_related("reviewer").order_by("id")
        hr_evaluation_queryset = HREvaluation.objects.select_related(
            "updated_by", "finalized_by"
        ).order_by("-updated_at", "-id")

        referrals = (
            Referral.objects
            .filter(sbus__email__iexact=user.email.strip())
            .filter(
                Q(candidate_type__in=["INTERN_EXPERIENCED", "FULL_TIME_EXPERIENCED"]) |
                Q(candidate_type__in=["INTERN_FRESHER", "FULL_TIME_FRESHER"], academic_details_status="COMPLETED")
            )
            .distinct()
            .select_related("referrer")
            .prefetch_related(
                "sbus",
                Prefetch("review_set", queryset=review_queryset, to_attr="prefetched_reviews"),
                Prefetch("hrevaluation_set", queryset=hr_evaluation_queryset, to_attr="prefetched_hr_evaluations")
            )
            .order_by("-submitted_at")
        )

        data = []
        for referral in referrals:
            reviews = referral.prefetched_reviews
            latest_review = reviews[-1] if reviews else None
            evaluations = referral.prefetched_hr_evaluations
            hr_started = bool(evaluations)
            completed_evaluations = [
                evaluation for evaluation in evaluations
                if evaluation.evaluation_status == "COMPLETED"
            ]
            final_hr_eval = max(
                completed_evaluations,
                key=lambda evaluation: (
                    evaluation.finalized_at is not None,
                    evaluation.finalized_at,
                    evaluation.id
                )
            ) if completed_evaluations else None

            is_finalized = referral.current_status in FINAL_STATUSES
            can_edit_sbu_review = not hr_started and not is_finalized
            review_history = [
                serialize_review(review) for review in reversed(reviews)
            ]
            academic_ready = is_academic_ready(referral)
            is_fresher = referral.candidate_type in FRESHER_TYPES

            data.append({
                "id": referral.id,
                "candidate_name": referral.candidate_name,
                "candidate_type": referral.candidate_type,
                "candidate_email": referral.candidate_email,
                "candidate_phone": referral.candidate_phone,
                "submitted_at": referral.submitted_at,
                "referral_reason_type": referral.referral_reason_type,
                "current_status": referral.current_status,
                "rejection_stage": referral.rejection_stage,
                "rejection_reason": referral.rejection_reason,
                "cv_url": referral.cv_url,
                "sbus": [
                    {"name": sbu.name, "email": sbu.email}
                    for sbu in referral.sbus.all()
                ],
                "additional_comment": referral.additional_comment,
                "referrer": {
                    "emp_id": referral.referrer.emp_id,
                    "name": referral.referrer.name,
                    "email": referral.referrer.email
                } if referral.referrer else None,

                # Academic details
                "academic_details_status": referral.academic_details_status,
                "is_academic_locked": is_fresher and academic_ready,
                "academic_details": serialize_academic_details(referral),
                "tenth_percentage": referral.tenth_percentage if is_fresher and academic_ready else None,
                "twelfth_percentage": referral.twelfth_percentage if is_fresher and academic_ready else None,
                "graduation_cgpa": referral.graduation_cgpa if is_fresher and academic_ready else None,
                "academic_details_updated_at": referral.academic_details_updated_at if is_fresher else None,

                # Latest SBU review and complete SBU history
                "review": serialize_review(latest_review),
                "review_history": review_history,
                "can_edit_sbu_review": can_edit_sbu_review,

                # HR workflow visibility
                "hr_evaluation_started": hr_started,
                "hr_evaluation": serialize_final_hr_evaluation(final_hr_eval),
                "hr_evaluation_status": final_hr_eval.evaluation_status if final_hr_eval else None,
                "is_hr_locked": final_hr_eval.is_locked if final_hr_eval else False,
                "is_finalized": bool(final_hr_eval),

                # Offer and joining report
                "offer_released": final_hr_eval.offer_released if final_hr_eval else False,
                "offer_outcome": final_hr_eval.offer_outcome if final_hr_eval else None,
                "joining_date": final_hr_eval.joining_date if final_hr_eval else None,

                # Existing timeline fields
                "considered_at": latest_review.reviewed_at if latest_review else None,
                "final_at": final_hr_eval.finalized_at if final_hr_eval else None
            })

        return Response(data, status=200)

# ==========================================================
# POST: INITIAL SBU REVIEW
# ==========================================================
class SubmitReviewView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, referral_id):
        return create_review_revision(
            request=request,
            referral_id=referral_id,
            require_existing=False
        )

# ==========================================================
# PUT: REVISE EXISTING SBU REVIEW
# ==========================================================
class UpdateReviewView(APIView):
    permission_classes = [AllowAny]

    def put(self, request, referral_id):
        return create_review_revision(
            request=request,
            referral_id=referral_id,
            require_existing=True
        )