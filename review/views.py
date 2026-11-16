from django.conf import settings
from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework import status

from api.models import (
    Referral,
    Review,
    User,
    HREvaluation,
)

from api.utils import send_dynamic_email


# ==========================================================
# Helpers
# ==========================================================

VALID_DECISIONS = {"CONSIDERED", "REJECTED"}


def serialize_review(review):
    """
    Convert a Review instance into a frontend-friendly object.
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


def get_latest_review(referral):
    """
    The most recently CREATED review is the effective
    SBU recommendation.

    Ordering by ID gives us a deterministic sequence.
    """

    return (
        Review.objects
        .filter(referral=referral)
        .select_related("reviewer")
        .order_by("-id")
        .first()
    )


def is_assigned_reviewer(referral, reviewer):
    """
    Confirm that the employee is assigned to this referral
    through the SBU relationship.

    Normalize email addresses to avoid case differences.
    """

    reviewer_email = (reviewer.email or "").strip().lower()

    if not reviewer_email:
        return False

    return any(
        (sbu.email or "").strip().lower() == reviewer_email
        for sbu in referral.sbus.all()
    )


def has_hr_started(referral):
    """
    An existing HR evaluation record locks SBU decisions.

    This assumes HR evaluation records are created only
    when HR begins evaluating a candidate.
    """

    return HREvaluation.objects.filter(
        referral=referral
    ).exists()


def validate_review_payload(request):
    """
    Validate decision, comment and employee ID.
    """

    emp_id = request.data.get("emp_id")

    decision = request.data.get("decision")

    comment = request.data.get("comment")

    if not emp_id:
        return None, None, None, Response(
            {"error": "emp_id is required."},
            status=400,
        )

    if decision not in VALID_DECISIONS:
        return None, None, None, Response(
            {"error": "Invalid review decision."},
            status=400,
        )

    if not isinstance(comment, str) or not comment.strip():
        return None, None, None, Response(
            {"error": "Review comment is required."},
            status=400,
        )

    return (
        emp_id,
        decision,
        comment.strip(),
        None,
    )


def apply_review_decision(referral, decision, comment):
    """
    Synchronize the referral's status with the latest
    effective SBU review decision.

    Review timestamps are stored in Review.reviewed_at,
    not in the Referral model.
    """

    if decision == "REJECTED":

        referral.current_status = "REJECTED"

        referral.rejection_stage = "SBU"

        referral.rejection_reason = comment

    elif decision == "CONSIDERED":

        referral.current_status = "CONSIDERED"

        # Clear any previous SBU rejection details.
        referral.rejection_stage = None

        referral.rejection_reason = None

    # Save only fields that actually exist in Referral.
    referral.save(
        update_fields=[
            "current_status",
            "rejection_stage",
            "rejection_reason",
        ]
    )

def notify_review_change(referral, previous_decision, decision):
    """
    Preserve existing notification purposes.

    Testing emails remain hardcoded, matching the
    current application configuration.

    Notification errors are logged rather than causing
    a committed review to appear unsuccessful.
    """

    try:

        if decision == "REJECTED":

            send_dynamic_email(
                purpose="CV_REJECTED_SBU",
                to_emails=["abgang05@gmail.com"],
                context_data={
                    "candidate_name": referral.candidate_name,
                    "portal_link": (
                        f"{settings.FRONTEND_BASE_URL}/"
                    ),
                    "reason": referral.rejection_reason,
                },
            )

            if previous_decision == "CONSIDERED":

                send_dynamic_email(
                    purpose="CV_REVOKED_BY_SBU",
                    to_emails=["abgang05@gmail.com"],
                    context_data={
                        "candidate_name": referral.candidate_name,
                        "portal_link": (
                            f"{settings.FRONTEND_BASE_URL}/hr-evaluation"
                        ),
                    },
                )

        elif decision == "CONSIDERED":

            send_dynamic_email(
                purpose="CV_APPROVED_SBU",
                to_emails=["abgang05@gmail.com"],
                context_data={
                    "candidate_name": referral.candidate_name,
                    "portal_link": (
                        f"{settings.FRONTEND_BASE_URL}/"
                    ),
                },
            )

            # Notify HR when the referral first becomes
            # considered or changes from rejected to considered.
            if previous_decision != "CONSIDERED":

                send_dynamic_email(
                    purpose="CV_TO_HR",
                    to_emails=["abgang05@gmail.com"],
                    context_data={
                        "candidate_name": referral.candidate_name,
                        "portal_link": (
                            f"{settings.FRONTEND_BASE_URL}/hr-evaluation"
                        ),
                    },
                )

    except Exception as error:

        print(
            "Review notification failed:",
            str(error),
        )


def create_review_revision(request, referral_id, require_existing):
    """
    Shared implementation for initial reviews and revisions.

    POST:
        Creates the first review.

    PUT:
        Creates a new revision of an existing review.

    Existing reviews are never overwritten.

    expected_review_id:
        Prevents stale clients from silently changing
        a review that another reviewer has already revised.
    """

    emp_id, decision, comment, error = validate_review_payload(
        request
    )

    if error:
        return error

    # ======================================================
    # Validate expected review ID
    # ======================================================

    if "expected_review_id" not in request.data:

        return Response(
            {
                "error": (
                    "expected_review_id is required. "
                    "Refresh the referral and try again."
                )
            },
            status=400,
        )

    expected_review_id = request.data.get(
        "expected_review_id"
    )

    if expected_review_id is not None:

        try:
            expected_review_id = int(expected_review_id)

        except (TypeError, ValueError):

            return Response(
                {"error": "Invalid expected_review_id."},
                status=400,
            )

    # ======================================================
    # Fetch reviewer
    # ======================================================

    try:

        reviewer = User.objects.get(emp_id=emp_id)

    except User.DoesNotExist:

        return Response(
            {"error": "Reviewer not found."},
            status=404,
        )

    # ======================================================
    # Atomic review submission
    # ======================================================

    with transaction.atomic():

        try:

            # Lock the referral row while checking and
            # changing its effective SBU decision.
            referral = (
                Referral.objects
                .select_for_update()
                .select_related("referrer")
                .get(id=referral_id)
            )

        except Referral.DoesNotExist:

            return Response(
                {"error": "Referral not found."},
                status=404,
            )

        # --------------------------------------------------
        # Verify reviewer assignment
        # --------------------------------------------------

        if not is_assigned_reviewer(referral, reviewer):

            return Response(
                {
                    "error": (
                        "You are not assigned as an "
                        "SBU reviewer for this referral."
                    )
                },
                status=403,
            )

        # --------------------------------------------------
        # Lock review once HR has started
        # --------------------------------------------------

        if has_hr_started(referral):

            return Response(
                {
                    "error": (
                        "HR evaluation has already started. "
                        "SBU reviews can no longer be modified."
                    )
                },
                status=403,
            )

        # --------------------------------------------------
        # Prevent modifications after HR finalization
        # --------------------------------------------------

        if referral.current_status in [
            "FINAL_ACCEPTED",
            "FINAL_REJECTED",
        ]:

            return Response(
                {
                    "error": (
                        "This referral has already been "
                        "finalized by HR."
                    )
                },
                status=403,
            )

        # --------------------------------------------------
        # Fetch the current effective review
        # --------------------------------------------------

        latest_review = get_latest_review(referral)

        current_review_id = (
            latest_review.id
            if latest_review
            else None
        )

        # --------------------------------------------------
        # Validate initial submission vs revision
        # --------------------------------------------------

        if require_existing and latest_review is None:

            return Response(
                {
                    "error": (
                        "No existing review was found. "
                        "Submit an initial review instead."
                    )
                },
                status=409,
            )

        if not require_existing and latest_review is not None:

            return Response(
                {
                    "error": (
                        "A review already exists. "
                        "Refresh and use Revise SBU Review."
                    )
                },
                status=409,
            )

        # --------------------------------------------------
        # Optimistic concurrency check
        # --------------------------------------------------

        if expected_review_id != current_review_id:

            return Response(
                {
                    "error": (
                        "Another reviewer has updated this "
                        "referral. Refresh to see the latest "
                        "decision before submitting."
                    ),
                    "latest_review": serialize_review(
                        latest_review
                    ),
                },
                status=409,
            )

        previous_decision = (
            latest_review.decision
            if latest_review
            else None
        )

        # --------------------------------------------------
        # Create a NEW review record
        # --------------------------------------------------

        new_review = Review.objects.create(
            referral=referral,
            reviewer=reviewer,
            decision=decision,
            comment=comment,
        )

        # --------------------------------------------------
        # Update the effective referral status
        # --------------------------------------------------

        apply_review_decision(
            referral,
            decision,
            comment,
        )

        # --------------------------------------------------
        # Notify after successful transaction commit
        # --------------------------------------------------

        transaction.on_commit(
            lambda: notify_review_change(
                referral,
                previous_decision,
                decision,
            )
        )

    return Response(
        {
            "message": (
                "Review revised successfully."
                if require_existing
                else "Review submitted successfully."
            ),
            "review": serialize_review(new_review),
        },
        status=201 if not require_existing else 200,
    )


# ==========================================================
# GET: CVs assigned to the logged-in SBU reviewer
# ==========================================================

class CVsForReview(APIView):

    permission_classes = [AllowAny]

    def get(self, request):

        emp_id = request.query_params.get("emp_id")

        if not emp_id:

            return Response(
                {"error": "emp_id is required."},
                status=400,
            )

        try:

            user = User.objects.get(emp_id=emp_id)

        except User.DoesNotExist:

            return Response(
                {"error": "User not found."},
                status=404,
            )

        # --------------------------------------------------
        # Fetch referrals assigned to this employee
        # --------------------------------------------------

        referrals = (
            Referral.objects
            .filter(sbus__email__iexact=user.email.strip())
            .distinct()
            .select_related("referrer")
            .prefetch_related(
                "sbus",
                Prefetch(
                    "review_set",
                    queryset=(
                        Review.objects
                        .select_related("reviewer")
                        .order_by("id")
                    ),
                ),
            )
            .order_by("-submitted_at")
        )

        data = []

        for referral in referrals:

            # ------------------------------------------------
            # Fetch ALL reviews, not only this user's reviews
            # ------------------------------------------------

            reviews = list(referral.review_set.all())

            latest_review = (
                reviews[-1]
                if reviews
                else None
            )

            # ------------------------------------------------
            # HR evaluation information
            # ------------------------------------------------

            hr_eval = (
                HREvaluation.objects
                .filter(referral=referral)
                .select_related("updated_by")
                .order_by("-updated_at", "-id")
                .first()
            )

            hr_started = hr_eval is not None

            is_finalized = referral.current_status in [
                "FINAL_ACCEPTED",
                "FINAL_REJECTED",
            ]

            can_edit_sbu_review = (
                not hr_started
                and not is_finalized
            )

            # ------------------------------------------------
            # Serialize review history
            # ------------------------------------------------

            review_history = [
                serialize_review(review)
                for review in reversed(reviews)
            ]

            # ------------------------------------------------
            # Build referral response
            # ------------------------------------------------

            data.append({

                "id": referral.id,

                "candidate_name": referral.candidate_name,

                "candidate_type": referral.candidate_type,

                "candidate_email": referral.candidate_email,

                "candidate_phone": referral.candidate_phone,

                "submitted_at": referral.submitted_at,

                "referral_reason_type": (
                    referral.referral_reason_type
                ),

                "current_status": referral.current_status,

                "rejection_stage": referral.rejection_stage,

                "rejection_reason": referral.rejection_reason,

                "cv_url": referral.cv_url,

                "sbus": [
                    {
                        "name": sbu.name,
                        "email": sbu.email,
                    }
                    for sbu in referral.sbus.all()
                ],

                "additional_comment": (
                    referral.additional_comment
                ),

                "referrer": {
                    "emp_id": referral.referrer.emp_id,
                    "name": referral.referrer.name,
                    "email": referral.referrer.email,
                },

                # Latest effective SBU review
                "review": serialize_review(latest_review),

                # Complete SBU review history
                "review_history": review_history,

                # Explicit permission flag for frontend
                "can_edit_sbu_review": can_edit_sbu_review,

                "hr_evaluation_started": hr_started,

                "hr_evaluation": {
                    "stage": hr_eval.stage,
                    "status": hr_eval.status,
                    "comment": hr_eval.comment,
                    "updated_at": hr_eval.updated_at,
                    "updated_by": hr_eval.updated_by.name,
                } if hr_eval else None,

            # Timestamp of the latest effective SBU review.

            "considered_at": (

                latest_review.reviewed_at

                if latest_review

                else None

            ),

            # Timestamp of the latest HR evaluation update.

            "final_at": (

                hr_eval.updated_at

                if hr_eval

                else None

            ),
                        })

        return Response(data, status=200)


# ==========================================================
# POST: Submit the first SBU review
# ==========================================================

class SubmitReviewView(APIView):

    permission_classes = [AllowAny]

    def post(self, request, referral_id):

        return create_review_revision(
            request=request,
            referral_id=referral_id,
            require_existing=False,
        )


# ==========================================================
# PUT: Revise the effective SBU decision
# ==========================================================

class UpdateReviewView(APIView):

    permission_classes = [AllowAny]

    def put(self, request, referral_id):

        return create_review_revision(
            request=request,
            referral_id=referral_id,
            require_existing=True,
        )