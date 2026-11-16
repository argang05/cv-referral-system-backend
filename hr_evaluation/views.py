from django.db import transaction
from django.db.models import Prefetch

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

from api.models import Referral, User, Review, HREvaluation
from api.utils import send_dynamic_email
from django.conf import settings


# ==========================================================
# CONSTANTS
# ==========================================================

VALID_HR_STATUSES = {
    "IN_PROGRESS",
    "ACCEPTED",
    "REJECTED",
}

VALID_HR_STAGES = {
    "TEST",
    "T1",
    "T2",
    "T3",
    "HR",
    "OTHER",
}

FINAL_STATUSES = {
    "FINAL_ACCEPTED",
    "FINAL_REJECTED",
}


# ==========================================================
# SERIALIZE SBU REVIEW
# ==========================================================

def serialize_review(review):
    """
    Serialize an individual SBU review.

    Includes:
    - Reviewer identity
    - Decision
    - Comment
    - Timestamp
    """

    if review is None:
        return None

    return {
        "id": review.id,
        "decision": review.decision,
        "comment": review.comment,
        "reviewed_at": review.reviewed_at,

        "reviewed_by": {
            "emp_id": review.reviewer.emp_id,
            "name": review.reviewer.name,
            "email": review.reviewer.email,
        },
    }


# ==========================================================
# SERIALIZE HR EVALUATION
# ==========================================================

def serialize_hr_evaluation(evaluation):

    if evaluation is None:
        return None

    return {
        "id": evaluation.id,
        "stage": evaluation.stage,
        "status": evaluation.status,
        "comment": evaluation.comment,
        "updated_at": evaluation.updated_at,
        "updated_by": evaluation.updated_by.name,
    }


# ==========================================================
# VALIDATE HR EVALUATION
# ==========================================================

def validate_hr_evaluation_payload(data):

    referral_id = data.get("referral_id")
    emp_id = data.get("emp_id")
    status = data.get("status")
    stage = data.get("stage") or ""
    comment = data.get("comment")

    if not referral_id:
        return None, "referral_id is required."

    if not emp_id:
        return None, "emp_id is required."

    if status not in VALID_HR_STATUSES:
        return None, "Invalid HR evaluation status."

    if not isinstance(comment, str) or not comment.strip():
        return None, "HR evaluation comment is required."

    if status == "REJECTED":
        if stage not in VALID_HR_STAGES:
            return None, "A valid rejection stage is required."

    elif stage and stage not in VALID_HR_STAGES:
        return None, "Invalid HR evaluation stage."

    return {
        "referral_id": referral_id,
        "emp_id": emp_id,
        "status": status,
        "stage": stage,
        "comment": comment.strip(),
    }, None


# ==========================================================
# APPLY HR DECISION
# ==========================================================

def apply_hr_decision(referral, status, comment):
    """
    Synchronize Referral.current_status
    with the HR evaluation decision.
    """

    if status == "IN_PROGRESS":

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

    referral.save(
        update_fields=[
            "current_status",
            "rejection_stage",
            "rejection_reason",
        ]
    )


# ==========================================================
# SEND HR NOTIFICATION
# ==========================================================

def send_hr_evaluation_notification(referral, status, comment):

    if status == "REJECTED":

        send_dynamic_email(
            purpose="CV_REJECTED_HR",
            to_emails=["abgang05@gmail.com"],
            context_data={
                "candidate_name": referral.candidate_name,
                "portal_link": f"{settings.FRONTEND_BASE_URL}/",
                "rejection_reason": comment,
            },
        )

    elif status == "ACCEPTED":

        send_dynamic_email(
            purpose="CV_APPROVED_HR",
            to_emails=["abgang05@gmail.com"],
            context_data={
                "candidate_name": referral.candidate_name,
                "portal_link": f"{settings.FRONTEND_BASE_URL}/",
            },
        )


# ==========================================================
# HR EVALUATION VIEW
# ==========================================================

class HREvaluationView(APIView):

    permission_classes = [AllowAny]

    # ======================================================
    # GET - FETCH HR REFERRALS WITH SBU REVIEW HISTORY
    # ======================================================

    def get(self, request):

        referrals = (
            Referral.objects
            .filter(
                current_status__in=[
                    "CONSIDERED",
                    "FINAL_ACCEPTED",
                    "FINAL_REJECTED",
                ]
            )
            .select_related("referrer")
            .prefetch_related(
                "sbus",

                Prefetch(
                    "review_set",
                    queryset=(
                        Review.objects
                        .select_related("reviewer")
                        .order_by("-reviewed_at", "-id")
                    ),
                    to_attr="prefetched_reviews",
                ),

                Prefetch(
                    "hrevaluation_set",
                    queryset=(
                        HREvaluation.objects
                        .select_related("updated_by")
                        .order_by("-updated_at", "-id")
                    ),
                    to_attr="prefetched_hr_evaluations",
                ),
            )
            .distinct()
            .order_by("-submitted_at")
        )

        response_data = []

        for referral in referrals:

            # ----------------------------------------------
            # SBU REVIEW HISTORY
            # ----------------------------------------------

            reviews = referral.prefetched_reviews

            latest_review = reviews[0] if reviews else None

            review_history = [
                serialize_review(review)
                for review in reviews
            ]

            # ----------------------------------------------
            # HR EVALUATION
            # ----------------------------------------------

            evaluations = referral.prefetched_hr_evaluations

            latest_hr_evaluation = (
                evaluations[0]
                if evaluations
                else None
            )

            hr_started = latest_hr_evaluation is not None

            is_finalized = (
                referral.current_status in FINAL_STATUSES
            )

            # ----------------------------------------------
            # TIMESTAMPS
            # ----------------------------------------------

            considered_at = (
                latest_review.reviewed_at
                if latest_review
                else None
            )

            final_at = (
                latest_hr_evaluation.updated_at
                if (
                    latest_hr_evaluation
                    and latest_hr_evaluation.status in {
                        "ACCEPTED",
                        "REJECTED",
                    }
                )
                else None
            )

            # ----------------------------------------------
            # RESPONSE
            # ----------------------------------------------

            response_data.append({

                "id": referral.id,

                "candidate_name": referral.candidate_name,
                "candidate_email": referral.candidate_email,
                "candidate_phone": referral.candidate_phone,
                "candidate_type": referral.candidate_type,

                "submitted_at": referral.submitted_at,

                "referral_reason_type": (
                    referral.referral_reason_type
                ),

                "current_status": referral.current_status,

                "rejection_stage": referral.rejection_stage,
                "rejection_reason": referral.rejection_reason,

                "cv_url": referral.cv_url,

                "additional_comment": (
                    referral.additional_comment
                ),

                # ------------------------------------------
                # ASSIGNED SBU REVIEWERS
                # ------------------------------------------

                "sbus": [
                    {
                        "name": sbu.name,
                        "email": sbu.email,
                    }
                    for sbu in referral.sbus.all()
                ],

                # ------------------------------------------
                # REFERRER
                # ------------------------------------------

                "referrer": {
                    "emp_id": referral.referrer.emp_id,
                    "name": referral.referrer.name,
                    "email": referral.referrer.email,
                },

                # ------------------------------------------
                # LATEST SBU REVIEW
                # ------------------------------------------

                "review": serialize_review(latest_review),

                # ------------------------------------------
                # COMPLETE SBU REVIEW HISTORY
                # ------------------------------------------

                "review_history": review_history,

                # ------------------------------------------
                # HR EVALUATION
                # ------------------------------------------

                "hr_evaluation": serialize_hr_evaluation(
                    latest_hr_evaluation
                ),

                # ------------------------------------------
                # WORKFLOW FLAGS
                # ------------------------------------------

                "hr_evaluation_started": hr_started,

                "is_finalized": is_finalized,

                "can_edit_sbu_review": (
                    not hr_started
                    and not is_finalized
                ),

                # ------------------------------------------
                # PROGRESS BAR TIMESTAMPS
                # ------------------------------------------

                "considered_at": considered_at,

                "final_at": final_at,
            })

        return Response(response_data)

    # ======================================================
    # POST - INITIAL HR EVALUATION
    # ======================================================

    def post(self, request):

        validated_data, error = validate_hr_evaluation_payload(
            request.data
        )

        if error:
            return Response(
                {"error": error},
                status=400,
            )

        referral_id = validated_data["referral_id"]
        emp_id = validated_data["emp_id"]
        status = validated_data["status"]
        stage = validated_data["stage"]
        comment = validated_data["comment"]

        # ----------------------------------------------
        # VALIDATE HR EMPLOYEE
        # ----------------------------------------------

        try:
            user = User.objects.get(emp_id=emp_id)

        except User.DoesNotExist:
            return Response(
                {"error": "HR employee not found."},
                status=404,
            )

        if not user.is_hr:
            return Response(
                {"error": "Only HR employees can evaluate referrals."},
                status=403,
            )

        # ----------------------------------------------
        # ATOMIC TRANSACTION
        # ----------------------------------------------

        with transaction.atomic():

            try:
                referral = (
                    Referral.objects
                    .select_for_update()
                    .get(id=referral_id)
                )

            except Referral.DoesNotExist:
                return Response(
                    {"error": "Referral not found."},
                    status=404,
                )

            # Prevent duplicate evaluations

            if HREvaluation.objects.filter(
                referral=referral
            ).exists():

                return Response(
                    {
                        "error": (
                            "HR evaluation already exists. "
                            "Use the update endpoint."
                        )
                    },
                    status=409,
                )

            # ----------------------------------------------
            # CHECK LATEST SBU DECISION
            # ----------------------------------------------

            latest_review = (
                Review.objects
                .filter(referral=referral)
                .order_by("-reviewed_at", "-id")
                .first()
            )

            if latest_review is None:
                return Response(
                    {
                        "error": (
                            "No SBU review exists for this referral."
                        )
                    },
                    status=409,
                )

            if latest_review.decision != "CONSIDERED":
                return Response(
                    {
                        "error": (
                            "The latest SBU decision does not "
                            "recommend this candidate for HR evaluation."
                        )
                    },
                    status=409,
                )

            if referral.current_status != "CONSIDERED":
                return Response(
                    {
                        "error": (
                            "Referral is not eligible for HR evaluation."
                        )
                    },
                    status=409,
                )

            # ----------------------------------------------
            # CREATE HR EVALUATION
            # ----------------------------------------------

            HREvaluation.objects.create(
                referral=referral,
                updated_by=user,
                stage=stage,
                status=status,
                comment=comment,
            )

            # ----------------------------------------------
            # UPDATE REFERRAL STATUS
            # ----------------------------------------------

            apply_hr_decision(
                referral,
                status,
                comment,
            )

            # ----------------------------------------------
            # NOTIFY ONLY ON FINAL DECISION
            # ----------------------------------------------

            if status in {"ACCEPTED", "REJECTED"}:

                transaction.on_commit(
                    lambda: send_hr_evaluation_notification(
                        referral,
                        status,
                        comment,
                    )
                )

        return Response(
            {
                "message": "HR evaluation submitted successfully."
            },
            status=201,
        )

    # ======================================================
    # PUT - UPDATE HR EVALUATION
    # ======================================================

    def put(self, request):

        validated_data, error = validate_hr_evaluation_payload(
            request.data
        )

        if error:
            return Response(
                {"error": error},
                status=400,
            )

        referral_id = validated_data["referral_id"]
        emp_id = validated_data["emp_id"]
        status = validated_data["status"]
        stage = validated_data["stage"]
        comment = validated_data["comment"]

        # ----------------------------------------------
        # VALIDATE HR EMPLOYEE
        # ----------------------------------------------

        try:
            user = User.objects.get(emp_id=emp_id)

        except User.DoesNotExist:
            return Response(
                {"error": "HR employee not found."},
                status=404,
            )

        if not user.is_hr:
            return Response(
                {"error": "Only HR employees can update evaluations."},
                status=403,
            )

        # ----------------------------------------------
        # ATOMIC UPDATE
        # ----------------------------------------------

        with transaction.atomic():

            try:
                referral = (
                    Referral.objects
                    .select_for_update()
                    .get(id=referral_id)
                )

            except Referral.DoesNotExist:
                return Response(
                    {"error": "Referral not found."},
                    status=404,
                )

            evaluation = (
                HREvaluation.objects
                .filter(referral=referral)
                .order_by("-updated_at", "-id")
                .first()
            )

            if evaluation is None:
                return Response(
                    {
                        "error": (
                            "HR evaluation not found. "
                            "Submit an initial evaluation first."
                        )
                    },
                    status=404,
                )

            previous_status = evaluation.status

            # ----------------------------------------------
            # UPDATE EVALUATION
            # ----------------------------------------------

            evaluation.stage = stage
            evaluation.status = status
            evaluation.comment = comment
            evaluation.updated_by = user

            evaluation.save(
                update_fields=[
                    "stage",
                    "status",
                    "comment",
                    "updated_by",
                    "updated_at",
                ]
            )

            # ----------------------------------------------
            # UPDATE REFERRAL
            # ----------------------------------------------

            apply_hr_decision(
                referral,
                status,
                comment,
            )

            # ----------------------------------------------
            # SEND EMAIL ONLY WHEN FINAL STATUS CHANGES
            # ----------------------------------------------

            if (
                status in {"ACCEPTED", "REJECTED"}
                and previous_status != status
            ):

                transaction.on_commit(
                    lambda: send_hr_evaluation_notification(
                        referral,
                        status,
                        comment,
                    )
                )

        return Response(
            {
                "message": "HR evaluation updated successfully."
            },
            status=200,
        )