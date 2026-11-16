from django.db import transaction
from django.conf import settings

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

from api.models import (
    Referral,
    User,
    Review,
    HREvaluation,
)

from api.utils import send_dynamic_email


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
    Serialize one SBU review.

    Every review is an independent historical record.
    """

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
            "email": reviewer.email,
        } if reviewer else None,
    }


# ==========================================================
# SERIALIZE HR EVALUATION
# ==========================================================

def serialize_hr_evaluation(evaluation):
    """
    Serialize the latest HR evaluation.
    """

    if evaluation is None:
        return None

    updated_by = evaluation.updated_by

    return {
        "id": evaluation.id,

        "stage": evaluation.stage,

        "status": evaluation.status,

        "comment": evaluation.comment,

        "updated_at": evaluation.updated_at,

        "updated_by": (
            updated_by.name
            if updated_by
            else "Unknown HR Employee"
        ),
    }


# ==========================================================
# VALIDATE HR EVALUATION PAYLOAD
# ==========================================================

def validate_hr_evaluation_payload(data):
    """
    Validate POST/PUT payload.

    Returns:
        (validated_data, error)
    """

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
            return None, (
                "A valid rejection stage is required."
            )

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
# APPLY HR DECISION TO REFERRAL
# ==========================================================

def apply_hr_decision(referral, status, comment):
    """
    Synchronize the referral with the HR evaluation.

    Does not write to nonexistent Referral.final_at.
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

def send_hr_evaluation_notification(
    referral,
    status,
    comment,
):
    """
    Send notification for final HR decisions only.

    Preserves the existing testing recipient.
    """

    if status == "REJECTED":

        send_dynamic_email(
            purpose="CV_REJECTED_HR",

            to_emails=[
                "abgang05@gmail.com",
            ],

            context_data={
                "candidate_name": referral.candidate_name,

                "portal_link": (
                    f"{settings.FRONTEND_BASE_URL}/"
                ),

                "rejection_reason": comment,
            },
        )

    elif status == "ACCEPTED":

        send_dynamic_email(
            purpose="CV_APPROVED_HR",

            to_emails=[
                "abgang05@gmail.com",
            ],

            context_data={
                "candidate_name": referral.candidate_name,

                "portal_link": (
                    f"{settings.FRONTEND_BASE_URL}/"
                ),
            },
        )


# ==========================================================
# HR EVALUATION VIEW
# ==========================================================

class HREvaluationView(APIView):

    permission_classes = [AllowAny]

    # ======================================================
    # GET - HR REFERRALS + COMPLETE SBU HISTORY
    # ======================================================

    def get(self, request):
        """
        Fetch all referrals eligible for HR evaluation.

        Returns:
        - Candidate details
        - Referrer details
        - Latest SBU recommendation
        - Complete SBU review history
        - Latest HR evaluation
        - Workflow flags
        - Progress timestamps
        """

        # --------------------------------------------------
        # FETCH ELIGIBLE REFERRALS
        # --------------------------------------------------

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
            .prefetch_related("sbus")
            .order_by("-submitted_at")
        )

        response_data = []

        # --------------------------------------------------
        # PROCESS EACH REFERRAL
        # --------------------------------------------------

        for referral in referrals:

            # ==============================================
            # FETCH COMPLETE SBU REVIEW HISTORY
            # ==============================================

            reviews = list(
                Review.objects
                .filter(referral=referral)
                .select_related("reviewer")
                .order_by("-id")
            )

            # Latest review = newest appended record
            latest_review = (
                reviews[0]
                if reviews
                else None
            )

            # Complete history, newest first
            review_history = [
                serialize_review(review)
                for review in reviews
            ]

            # ==============================================
            # FETCH HR EVALUATION
            # ==============================================

            evaluations = list(
                HREvaluation.objects
                .filter(referral=referral)
                .select_related("updated_by")
                .order_by("-updated_at", "-id")
            )

            latest_hr_evaluation = (
                evaluations[0]
                if evaluations
                else None
            )

            # ==============================================
            # WORKFLOW FLAGS
            # ==============================================

            hr_started = (
                latest_hr_evaluation is not None
            )

            is_finalized = (
                referral.current_status in FINAL_STATUSES
            )

            can_edit_sbu_review = (
                not hr_started
                and not is_finalized
            )

            # ==============================================
            # PROGRESS TIMESTAMPS
            # ==============================================

            considered_at = (
                latest_review.reviewed_at
                if (
                    latest_review
                    and latest_review.decision == "CONSIDERED"
                )
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

            # ==============================================
            # SERIALIZE ASSIGNED SBUS
            # ==============================================

            sbus = [
                {
                    "name": sbu.name,
                    "email": sbu.email,
                }
                for sbu in referral.sbus.all()
            ]

            # ==============================================
            # SERIALIZE REFERRER
            # ==============================================

            referrer = referral.referrer

            referrer_data = {
                "emp_id": referrer.emp_id,
                "name": referrer.name,
                "email": referrer.email,
            } if referrer else None

            # ==============================================
            # BUILD RESPONSE
            # ==============================================

            response_data.append({

                # ------------------------------------------
                # REFERRAL DETAILS
                # ------------------------------------------

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
                # SBU ASSIGNMENTS
                # ------------------------------------------

                "sbus": sbus,

                # ------------------------------------------
                # REFERRER
                # ------------------------------------------

                "referrer": referrer_data,

                # ------------------------------------------
                # LATEST SBU REVIEW
                # ------------------------------------------

                "review": serialize_review(
                    latest_review
                ),

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
                    can_edit_sbu_review
                ),

                # ------------------------------------------
                # PROGRESS TIMESTAMPS
                # ------------------------------------------

                "considered_at": considered_at,

                "final_at": final_at,
            })

        return Response(response_data)

    # ======================================================
    # POST - CREATE INITIAL HR EVALUATION
    # ======================================================

    def post(self, request):

        validated_data, error = (
            validate_hr_evaluation_payload(
                request.data
            )
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

        # --------------------------------------------------
        # VALIDATE HR USER
        # --------------------------------------------------

        try:
            user = User.objects.get(
                emp_id=emp_id
            )

        except User.DoesNotExist:
            return Response(
                {
                    "error": "HR employee not found."
                },
                status=404,
            )

        if not user.is_hr:
            return Response(
                {
                    "error": (
                        "Only HR employees can "
                        "submit HR evaluations."
                    )
                },
                status=403,
            )

        # --------------------------------------------------
        # ATOMIC TRANSACTION
        # --------------------------------------------------

        with transaction.atomic():

            try:
                referral = (
                    Referral.objects
                    .select_for_update()
                    .get(id=referral_id)
                )

            except Referral.DoesNotExist:
                return Response(
                    {
                        "error": "Referral not found."
                    },
                    status=404,
                )

            # ----------------------------------------------
            # PREVENT DUPLICATE HR EVALUATIONS
            # ----------------------------------------------

            existing_evaluation = (
                HREvaluation.objects
                .filter(referral=referral)
                .exists()
            )

            if existing_evaluation:

                return Response(
                    {
                        "error": (
                            "HR evaluation already exists. "
                            "Please update the existing "
                            "evaluation instead."
                        )
                    },
                    status=409,
                )

            # ----------------------------------------------
            # VERIFY LATEST SBU RECOMMENDATION
            # ----------------------------------------------

            latest_review = (
                Review.objects
                .filter(referral=referral)
                .order_by("-id")
                .first()
            )

            if latest_review is None:

                return Response(
                    {
                        "error": (
                            "No SBU review exists "
                            "for this referral."
                        )
                    },
                    status=409,
                )

            if latest_review.decision != "CONSIDERED":

                return Response(
                    {
                        "error": (
                            "The latest SBU reviewer "
                            "has not recommended "
                            "this candidate for "
                            "HR evaluation."
                        )
                    },
                    status=409,
                )

            if referral.current_status != "CONSIDERED":

                return Response(
                    {
                        "error": (
                            "This referral is not "
                            "currently eligible "
                            "for HR evaluation."
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
                referral=referral,
                status=status,
                comment=comment,
            )

            # ----------------------------------------------
            # SEND EMAIL ON FINAL DECISION ONLY
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
                "message": (
                    "HR evaluation submitted successfully."
                )
            },
            status=201,
        )

    # ======================================================
    # PUT - UPDATE EXISTING HR EVALUATION
    # ======================================================

    def put(self, request):

        validated_data, error = (
            validate_hr_evaluation_payload(
                request.data
            )
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

        # --------------------------------------------------
        # VALIDATE HR USER
        # --------------------------------------------------

        try:
            user = User.objects.get(
                emp_id=emp_id
            )

        except User.DoesNotExist:
            return Response(
                {
                    "error": "HR employee not found."
                },
                status=404,
            )

        if not user.is_hr:
            return Response(
                {
                    "error": (
                        "Only HR employees can "
                        "update HR evaluations."
                    )
                },
                status=403,
            )

        # --------------------------------------------------
        # ATOMIC TRANSACTION
        # --------------------------------------------------

        with transaction.atomic():

            try:
                referral = (
                    Referral.objects
                    .select_for_update()
                    .get(id=referral_id)
                )

            except Referral.DoesNotExist:
                return Response(
                    {
                        "error": "Referral not found."
                    },
                    status=404,
                )

            # ----------------------------------------------
            # FIND EXISTING EVALUATION
            # ----------------------------------------------

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
                            "Please submit an initial "
                            "evaluation first."
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
                referral=referral,
                status=status,
                comment=comment,
            )

            # ----------------------------------------------
            # NOTIFY WHEN FINAL DECISION CHANGES
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
                "message": (
                    "HR evaluation updated successfully."
                )
            },
            status=200,
        )