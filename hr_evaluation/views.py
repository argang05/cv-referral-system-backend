from django.conf import settings
from django.db import transaction
from django.db.models import Prefetch, Max
from django.utils import timezone
from datetime import date
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from api.models import Referral, User, Review, HREvaluation, HREvaluationHistory
from api.utils import send_dynamic_email, get_role_and_departments

# ==========================================================
# CONSTANTS
# ==========================================================

VALID_HR_STATUSES = {"IN_PROGRESS", "ACCEPTED", "REJECTED"}
VALID_HR_STAGES = {"TEST", "T1", "T2", "T3", "HR", "OTHER"}
VALID_ACTIONS = {"SAVE_DRAFT", "FINALIZE"}
VALID_OFFER_OUTCOMES = {"OFFER_DECLINED", "DID_NOT_JOIN", "JOINED"}
FINAL_STATUSES = {"FINAL_ACCEPTED", "FINAL_REJECTED"}
FRESHER_TYPES = {"INTERN_FRESHER", "FULL_TIME_FRESHER"}

# ==========================================================
# HELPERS
# ==========================================================

def get_hr_user(emp_id):
    if not emp_id:
        return None
    try:
        user = User.objects.get(emp_id=emp_id)
    except User.DoesNotExist:
        return None
    sub_bu = str(getattr(user, "sub_bu", "") or "").strip().casefold()
    hr_keywords = ("human resource", "human resourse")
    is_hr_by_sub_bu = sub_bu == "hr" or any(keyword in sub_bu for keyword in hr_keywords)
    _, _, is_hr_by_role = get_role_and_departments(user.email)
    return user if is_hr_by_sub_bu or is_hr_by_role else None


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


def serialize_hr_evaluation(evaluation):
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


def serialize_hr_history(history):
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


def serialize_academic_details(referral):
    if referral.candidate_type not in FRESHER_TYPES:
        return None
    if referral.academic_details_status != "COMPLETED":
        return None
    return {
        "tenth_percentage": referral.tenth_percentage,
        "twelfth_percentage": referral.twelfth_percentage,
        "graduation_cgpa": referral.graduation_cgpa
    }


def is_academic_ready(referral):
    return (
        referral.candidate_type not in FRESHER_TYPES
        or referral.academic_details_status == "COMPLETED"
    )


def parse_offer_released(value):
    if isinstance(value, bool):
        return value, None
    if value in (0, 1):
        return bool(value), None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "1"):
            return True, None
        if normalized in ("false", "0"):
            return False, None
    return None, "offer_released must be a boolean."


def parse_joining_date(value):
    if value is None or value == "":
        return None, None
    if not isinstance(value, str):
        return None, "joining_date must be a valid date in YYYY-MM-DD format."
    try:
        return date.fromisoformat(value), None
    except ValueError:
        return None, "joining_date must be a valid date in YYYY-MM-DD format."


def validate_hr_evaluation_payload(data):
    referral_id = data.get("referral_id")
    emp_id = data.get("emp_id")
    hr_status = data.get("status")
    stage = data.get("stage") or ""
    comment = data.get("comment")
    action = data.get("action")
    expected_version = data.get("expected_version")

    # New offer fields
    raw_offer_released = data.get("offer_released", False)
    offer_outcome = data.get("offer_outcome") or None
    raw_joining_date = data.get("joining_date")

    if not referral_id:
        return None, "referral_id is required."
    if not emp_id:
        return None, "emp_id is required."
    if action not in VALID_ACTIONS:
        return None, "Invalid action. Use SAVE_DRAFT or FINALIZE."
    if hr_status not in VALID_HR_STATUSES:
        return None, "Invalid HR evaluation status."
    if not isinstance(stage, str):
        return None, "Invalid HR evaluation stage."
    if not isinstance(comment, str) or not comment.strip():
        return None, "HR evaluation comment is required."
    if stage and stage not in VALID_HR_STAGES:
        return None, "Invalid HR evaluation stage."
    if hr_status == "REJECTED" and stage not in VALID_HR_STAGES:
        return None, "A valid rejection stage is required."
    if action == "FINALIZE" and hr_status == "IN_PROGRESS":
        return None, "An evaluation cannot be finalized while its status is IN_PROGRESS."

    # Optimistic concurrency validation
    if expected_version is None or isinstance(expected_version, bool):
        return None, "expected_version is required."
    try:
        expected_version = int(expected_version)
    except (TypeError, ValueError):
        return None, "expected_version must be a non-negative integer."
    if expected_version < 0:
        return None, "expected_version must be a non-negative integer."

    # Validate offer fields
    offer_released, offer_error = parse_offer_released(raw_offer_released)
    if offer_error:
        return None, offer_error

    if offer_outcome is not None and offer_outcome not in VALID_OFFER_OUTCOMES:
        return None, "Invalid offer outcome. Use OFFER_DECLINED, DID_NOT_JOIN or JOINED."

    joining_date, date_error = parse_joining_date(raw_joining_date)
    if date_error:
        return None, date_error

    # Rejected or in-progress candidates cannot have offer details
    if hr_status != "ACCEPTED":
        if offer_released or offer_outcome or joining_date:
            return None, "Offer details are only applicable when the HR decision is ACCEPTED."
        offer_released = False
        offer_outcome = None
        joining_date = None

    # Offer outcome requires the offer to be released
    if hr_status == "ACCEPTED":
        if not offer_released and offer_outcome:
            return None, "An offer outcome cannot be selected before the offer is released."
        if not offer_released and joining_date:
            return None, "Joining date cannot be entered before the offer is released."
        if offer_outcome != "JOINED" and joining_date:
            return None, "Joining date is only applicable when the offer outcome is JOINED."

    # Finalization rules
    if action == "FINALIZE" and hr_status == "ACCEPTED":
        if not offer_released:
            return None, "The offer must be released before finalizing an accepted candidate."
        if not offer_outcome:
            return None, "Select the final offer outcome before finalizing."
        if offer_outcome == "JOINED" and not joining_date:
            return None, "Joining date is required when the candidate has joined."

    return {
        "referral_id": referral_id,
        "emp_id": emp_id,
        "status": hr_status,
        "stage": stage,
        "comment": comment.strip(),
        "action": action,
        "expected_version": expected_version,
        "offer_released": offer_released,
        "offer_outcome": offer_outcome,
        "joining_date": joining_date
    }, None


def apply_hr_decision(referral, status, comment, action):
    if action == "SAVE_DRAFT":
        referral.current_status = "CONSIDERED"
        referral.rejection_stage = None
        referral.rejection_reason = None
    elif status == "ACCEPTED":
        referral.current_status = "FINAL_ACCEPTED"
        referral.rejection_stage = None
        referral.rejection_reason = None
    elif status == "REJECTED":
        referral.current_status = "FINAL_REJECTED"
        referral.rejection_stage = "HR"
        referral.rejection_reason = comment

    referral.save(update_fields=[
        "current_status", "rejection_stage", "rejection_reason"
    ])


def send_hr_evaluation_notification(candidate_name, status, comment):
    try:
        if status == "REJECTED":
            send_dynamic_email(
                purpose="CV_REJECTED_HR",
                to_emails=["abgang05@gmail.com"],
                context_data={
                    "candidate_name": candidate_name,
                    "portal_link": f"{settings.FRONTEND_BASE_URL}/",
                    "rejection_reason": comment
                }
            )
        elif status == "ACCEPTED":
            send_dynamic_email(
                purpose="CV_APPROVED_HR",
                to_emails=["abgang05@gmail.com"],
                context_data={
                    "candidate_name": candidate_name,
                    "portal_link": f"{settings.FRONTEND_BASE_URL}/"
                }
            )
    except Exception as error:
        print("HR evaluation notification failed:", str(error))


def create_hr_history(evaluation, user, action, revision):
    return HREvaluationHistory.objects.create(
        evaluation=evaluation,
        revision=revision,
        stage=evaluation.stage,
        status=evaluation.status,
        comment=evaluation.comment,
        action=action,
        updated_by=user,
        offer_released=evaluation.offer_released,
        offer_outcome=evaluation.offer_outcome,
        joining_date=evaluation.joining_date
    )


def get_current_version(evaluation):
    return evaluation.history.aggregate(
        max_revision=Max("revision")
    )["max_revision"] or 0


# ==========================================================
# HR EVALUATION VIEW
# ==========================================================

class HREvaluationView(APIView):
    permission_classes = [AllowAny]

    # ------------------------------------------------------
    # GET - REFERRALS, ACADEMIC DETAILS, REVIEWS AND HISTORY
    # ------------------------------------------------------

    def get(self, request):
        referrals = (
            Referral.objects
            .filter(current_status__in=[
                "CONSIDERED", "FINAL_ACCEPTED", "FINAL_REJECTED"
            ])
            .select_related("referrer")
            .prefetch_related(
                "sbus",
                Prefetch(
                    "review_set",
                    queryset=Review.objects.select_related("reviewer").order_by("-id"),
                    to_attr="prefetched_reviews"
                ),
                Prefetch(
                    "hrevaluation_set",
                    queryset=HREvaluation.objects.select_related(
                        "updated_by", "finalized_by"
                    ).prefetch_related(
                        Prefetch(
                            "history",
                            queryset=HREvaluationHistory.objects.select_related(
                                "updated_by"
                            ).order_by("-revision"),
                            to_attr="prefetched_history"
                        )
                    ).order_by("-updated_at", "-id"),
                    to_attr="prefetched_hr_evaluations"
                )
            )
            .order_by("-submitted_at")
        )

        response_data = []

        for referral in referrals:
            reviews = referral.prefetched_reviews
            evaluations = referral.prefetched_hr_evaluations
            latest_review = reviews[0] if reviews else None
            latest_hr_evaluation = evaluations[0] if evaluations else None
            hr_started = latest_hr_evaluation is not None
            is_finalized = referral.current_status in FINAL_STATUSES
            is_hr_locked = (
                latest_hr_evaluation.is_locked
                if latest_hr_evaluation else False
            )

            hr_history = (
                latest_hr_evaluation.prefetched_history
                if latest_hr_evaluation else []
            )
            hr_version = hr_history[0].revision if hr_history else 0
            considered_at = (
                latest_review.reviewed_at
                if latest_review and latest_review.decision == "CONSIDERED"
                else None
            )
            final_at = (
                latest_hr_evaluation.finalized_at
                if latest_hr_evaluation and is_hr_locked
                else None
            )

            is_fresher = referral.candidate_type in FRESHER_TYPES
            is_academic_completed = (
                is_fresher and referral.academic_details_status == "COMPLETED"
            )
            academic_details = serialize_academic_details(referral)

            response_data.append({
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

                # Academic details
                "academic_details_status": referral.academic_details_status,
                "is_academic_locked": is_academic_completed,
                "academic_details": academic_details,
                "tenth_percentage": (
                    referral.tenth_percentage if is_academic_completed else None
                ),
                "twelfth_percentage": (
                    referral.twelfth_percentage if is_academic_completed else None
                ),
                "graduation_cgpa": (
                    referral.graduation_cgpa if is_academic_completed else None
                ),
                "academic_details_updated_at": (
                    referral.academic_details_updated_at if is_academic_completed else None
                ),

                # SBU reviews
                "review": serialize_review(latest_review),
                "review_history": [
                    serialize_review(review) for review in reviews
                ],

                # HR evaluation
                "hr_evaluation": serialize_hr_evaluation(latest_hr_evaluation),
                "hr_evaluation_status": (
                    latest_hr_evaluation.evaluation_status
                    if latest_hr_evaluation else "NOT_STARTED"
                ),
                "is_hr_locked": is_hr_locked,
                "hr_evaluation_history": [
                    serialize_hr_history(history) for history in hr_history
                ],
                "hr_evaluation_version": hr_version,
                "finalized_at": (
                    latest_hr_evaluation.finalized_at
                    if latest_hr_evaluation else None
                ),
                "finalized_by": (
                    serialize_hr_evaluation(latest_hr_evaluation)["finalized_by"]
                    if latest_hr_evaluation else None
                ),

                # Workflow flags
                "hr_evaluation_started": hr_started,
                "is_finalized": is_finalized,
                "can_edit_sbu_review": not hr_started and not is_finalized,

                # Progress timestamps
                "considered_at": considered_at,
                "final_at": final_at
            })

        return Response(response_data, status=200)

    # ------------------------------------------------------
    # POST - INITIAL HR EVALUATION
    # ------------------------------------------------------

    def post(self, request):
        validated_data, error = validate_hr_evaluation_payload(request.data)
        if error:
            return Response({"error": error}, status=400)

        user = get_hr_user(validated_data["emp_id"])
        if not user:
            return Response({"error": "Only HR employees can submit HR evaluations."}, status=403)

        with transaction.atomic():
            try:
                referral = Referral.objects.select_for_update().get(
                    id=validated_data["referral_id"]
                )
            except Referral.DoesNotExist:
                return Response({"error": "Referral not found."}, status=404)

            if not is_academic_ready(referral):
                return Response({
                    "error": "Academic details must be finalized before HR evaluation."
                }, status=403)

            if referral.current_status in FINAL_STATUSES:
                return Response({
                    "error": "This referral has already been finalized and permanently locked."
                }, status=403)

            if HREvaluation.objects.filter(referral=referral).exists():
                return Response({
                    "error": "HR evaluation already exists. Please update the existing evaluation instead."
                }, status=409)

            latest_review = Review.objects.filter(
                referral=referral
            ).order_by("-id").first()

            if latest_review is None or latest_review.decision != "CONSIDERED":
                return Response({
                    "error": "The latest SBU reviewer must recommend this candidate before HR evaluation."
                }, status=409)

            if referral.current_status != "CONSIDERED":
                return Response({
                    "error": "This referral is not currently eligible for HR evaluation."
                }, status=409)

            if validated_data["expected_version"] != 0:
                return Response({
                    "error": "Evaluation state changed. Refresh the referral and try again."
                }, status=409)

            action = validated_data["action"]
            hr_status = validated_data["status"]
            comment = validated_data["comment"]
            is_finalizing = action == "FINALIZE"

            evaluation = HREvaluation.objects.create(
                referral=referral,
                updated_by=user,
                stage=validated_data["stage"],
                status=hr_status,
                comment=comment,
                evaluation_status="COMPLETED" if is_finalizing else "DRAFT",
                finalized_at=timezone.now() if is_finalizing else None,
                finalized_by=user if is_finalizing else None,
                offer_released=validated_data["offer_released"],
                offer_outcome=validated_data["offer_outcome"],
                joining_date=validated_data["joining_date"]
            )

            create_hr_history(evaluation, user, action, revision=1)
            apply_hr_decision(referral, hr_status, comment, action)

            if is_finalizing:
                candidate_name = referral.candidate_name
                transaction.on_commit(
                    lambda name=candidate_name, status=hr_status, reason=comment:
                    send_hr_evaluation_notification(name, status, reason)
                )

        return Response({
            "message": (
                "HR evaluation finalized and permanently locked successfully."
                if is_finalizing else "HR evaluation saved as draft successfully."
            ),
            "evaluation_id": evaluation.id,
            "evaluation_status": evaluation.evaluation_status,
            "is_hr_locked": evaluation.is_locked,
            "hr_evaluation_version": 1
        }, status=201)

    # ------------------------------------------------------
    # PUT - UPDATE DRAFT OR FINALIZE EXISTING EVALUATION
    # ------------------------------------------------------

    def put(self, request):
        validated_data, error = validate_hr_evaluation_payload(request.data)
        if error:
            return Response({"error": error}, status=400)

        user = get_hr_user(validated_data["emp_id"])
        if not user:
            return Response({"error": "Only HR employees can update HR evaluations."}, status=403)

        with transaction.atomic():
            try:
                referral = Referral.objects.select_for_update().get(
                    id=validated_data["referral_id"]
                )
            except Referral.DoesNotExist:
                return Response({"error": "Referral not found."}, status=404)

            if not is_academic_ready(referral):
                return Response({
                    "error": "Academic details must be finalized before HR evaluation."
                }, status=403)

            evaluation = (
                HREvaluation.objects
                .filter(referral=referral)
                .order_by("-updated_at", "-id")
                .first()
            )

            if evaluation is None:
                return Response({
                    "error": "HR evaluation not found. Please submit an initial evaluation first."
                }, status=404)

            if evaluation.is_locked or referral.current_status in FINAL_STATUSES:
                return Response({
                    "error": "HR evaluation has been finalized and permanently locked. Further modifications are not permitted."
                }, status=403)

            if referral.current_status != "CONSIDERED":
                return Response({
                    "error": "This referral is no longer eligible for HR evaluation."
                }, status=409)

            current_version = get_current_version(evaluation)
            if validated_data["expected_version"] != current_version:
                return Response({
                    "error": "Another HR employee has updated this evaluation. Refresh the referral before saving.",
                    "current_version": current_version
                }, status=409)

            action = validated_data["action"]
            hr_status = validated_data["status"]
            comment = validated_data["comment"]
            is_finalizing = action == "FINALIZE"

            evaluation.stage = validated_data["stage"]
            evaluation.status = hr_status
            evaluation.comment = comment
            evaluation.updated_by = user
            evaluation.evaluation_status = "COMPLETED" if is_finalizing else "DRAFT"
            evaluation.offer_released = validated_data["offer_released"]
            evaluation.offer_outcome = validated_data["offer_outcome"]
            evaluation.joining_date = validated_data["joining_date"]

            if is_finalizing:
                evaluation.finalized_at = timezone.now()
                evaluation.finalized_by = user

            evaluation.save(update_fields=[
                "stage", "status", "comment", "updated_by", "updated_at",
                "evaluation_status", "finalized_at", "finalized_by",
                "offer_released", "offer_outcome", "joining_date"
            ])

            next_version = current_version + 1
            create_hr_history(evaluation, user, action, revision=next_version)
            apply_hr_decision(referral, hr_status, comment, action)

            if is_finalizing:
                candidate_name = referral.candidate_name
                transaction.on_commit(
                    lambda name=candidate_name, status=hr_status, reason=comment:
                    send_hr_evaluation_notification(name, status, reason)
                )

        return Response({
            "message": (
                "HR evaluation finalized and permanently locked successfully."
                if is_finalizing else "HR evaluation draft updated successfully."
            ),
            "evaluation_id": evaluation.id,
            "evaluation_status": evaluation.evaluation_status,
            "is_hr_locked": evaluation.is_locked,
            "hr_evaluation_version": next_version
        }, status=200)