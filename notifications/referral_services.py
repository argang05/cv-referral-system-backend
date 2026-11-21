import logging
import re

from django.db.models import Q

from api.models import User, HREvaluation
from api.utils import get_role_and_departments

from .services import create_notification


logger = logging.getLogger(__name__)


# ==========================================================
# NOTIFICATION TARGETS
# ==========================================================

REFERRER_URL = "/referrals"
SBU_REVIEW_URL = "/review-cv"
ACADEMIC_DETAILS_URL = "/academic-details"
HR_EVALUATION_URL = "/hr-evaluation"


# ==========================================================
# LABELS
# ==========================================================

HR_STAGE_LABELS = {
    "TEST": "Assessment Test",
    "T1": "Technical Round 1",
    "T2": "Technical Round 2",
    "T3": "Technical Round 3",
    "HR": "HR Interview",
    "OTHER": "Other",
}

HR_STATUS_LABELS = {
    "IN_PROGRESS": "In Progress",
    "ACCEPTED": "Selected",
    "REJECTED": "Rejected",
}

OFFER_OUTCOME_LABELS = {
    "OFFER_DECLINED": "Offer Declined",
    "DID_NOT_JOIN": "Candidate Did Not Join",
    "JOINED": "Candidate Joined",
}


# ==========================================================
# HR IDENTIFICATION
# ==========================================================

def is_hr_employee(user):
    """
    Determine whether an active employee has HR responsibilities.

    Supports:
    1. Explicit User.is_hr flag.
    2. User.role == HR.
    3. HR-related sub_bu.
    4. Existing HR reviewer mapping.

    A user may simultaneously be HR, a reviewer, and a referrer.
    """

    if user is None or not user.is_active:
        return False

    if getattr(user, "is_hr", False):
        return True

    if str(getattr(user, "role", "")).upper() == "HR":
        return True

    sub_bu = str(
        getattr(user, "sub_bu", "") or ""
    ).strip().casefold()

    if re.search(r"\bhr\b", sub_bu):
        return True

    hr_keywords = (
        "human resource",
        "human resources",
        "human resourse",
        "human resourses",
    )

    if any(keyword in sub_bu for keyword in hr_keywords):
        return True

    email = str(getattr(user, "email", "") or "").strip()

    if not email:
        return False

    _, _, is_hr_by_mapping = get_role_and_departments(email)

    return bool(is_hr_by_mapping)


def get_active_hr_users():
    """
    Return all active HR employees.

    Deduplicate employees using emp_id.
    """

    users = User.objects.filter(is_active=True)

    hr_users = []
    seen = set()

    for user in users:
        if not is_hr_employee(user):
            continue

        emp_id = str(user.emp_id)

        if emp_id in seen:
            continue

        seen.add(emp_id)
        hr_users.append(user)

    return hr_users


def get_hr_recipients():
    return get_active_hr_users()


# ==========================================================
# SBU REVIEWER RESOLUTION
# ==========================================================

def get_assigned_sbu_reviewers(referral):
    """
    Resolve assigned SBU reviewers using their registered emails.

    Employees are not excluded because they are HR or referrers.
    """

    reviewer_emails = {
        str(email).strip().casefold()
        for email in referral.sbus.values_list(
            "email", flat=True
        )
        if email
    }

    if not reviewer_emails:
        return []

    email_filter = Q()

    for email in reviewer_emails:
        email_filter |= Q(email__iexact=email)

    return list(
        User.objects.filter(
            email_filter,
            is_active=True
        ).distinct()
    )


def get_sbu_reviewers(referral, exclude_emp_id=None):
    reviewers = get_assigned_sbu_reviewers(referral)

    if exclude_emp_id is None:
        return reviewers

    return [
        reviewer
        for reviewer in reviewers
        if str(reviewer.emp_id) != str(exclude_emp_id)
    ]


def get_referrer(referral):
    referrer = referral.referrer

    if referrer and referrer.is_active:
        return referrer

    return None


# ==========================================================
# RECIPIENT HELPERS
# ==========================================================

def prepare_recipients(users, actor=None):
    """
    Return unique active employee IDs.

    actor is retained for compatibility with existing callers.

    The actor is NOT globally excluded.

    An employee performing an action may still need the
    notification because of another responsibility.
    """

    recipients = []
    seen = set()

    for user in users or []:
        if user is None or not user.is_active:
            continue

        emp_id = str(user.emp_id)

        if emp_id in seen:
            continue

        seen.add(emp_id)
        recipients.append(emp_id)

    return recipients


def unique_users(*groups):
    """
    Combine employee groups without duplicates.
    """

    result = []
    seen = set()

    for group in groups:
        for user in group or []:
            if user is None or not user.is_active:
                continue

            emp_id = str(user.emp_id)

            if emp_id in seen:
                continue

            seen.add(emp_id)
            result.append(user)

    return result


def exclude_users(users, excluded_ids=None):
    excluded = {
        str(emp_id)
        for emp_id in (excluded_ids or [])
        if emp_id is not None
    }

    return [
        user
        for user in users
        if user is not None
        and str(user.emp_id) not in excluded
    ]


# ==========================================================
# CORE REFERRAL NOTIFICATION
# ==========================================================

def create_referral_notification(
    referral,
    notification_type,
    title,
    message,
    users,
    target_url,
    actor=None
):
    """
    Create one notification shared by the specified recipients.

    Duplicate employee IDs are removed.

    The actor is not automatically excluded.
    """

    recipient_ids = prepare_recipients(users, actor)

    if not recipient_ids:
        logger.info(
            "No eligible recipients for referral %s, event %s",
            referral.id,
            notification_type
        )
        return None

    return create_notification(
        notification_type=notification_type,
        title=title,
        message=message,
        audience="SPECIFIC",
        recipients=recipient_ids,
        target_url=target_url,
        referral=referral
    )


def send_referral_notification(
    referral,
    notification_type,
    title,
    message,
    recipients,
    target_url,
    exclude_emp_ids=None
):
    users = exclude_users(
        recipients,
        excluded_ids=exclude_emp_ids
    )

    return create_referral_notification(
        referral=referral,
        notification_type=notification_type,
        title=title,
        message=message,
        users=users,
        target_url=target_url
    )


# ==========================================================
# ROLE-AWARE NOTIFICATION DISPATCH
# ==========================================================

def notify_referrer_and_reviewers(
    referral,
    notification_type,
    title,
    message,
    actor=None,
    include_hr=False
):
    """
    Notify the relevant parties without duplicate delivery.

    URL priority:
    1. HR evaluation page for HR workflow events.
    2. Referrals page for the original referrer.
    3. SBU review page for assigned reviewers.

    Each employee receives at most one notification
    from this dispatch call.

    Separate business events can generate separate notifications.
    """

    referrer = get_referrer(referral)

    reviewers = get_assigned_sbu_reviewers(referral)

    hr_users = get_active_hr_users() if include_hr else []

    assigned = set()

    notifications = []

    def dispatch(users, target_url):
        eligible = []

        for user in users:
            if user is None or not user.is_active:
                continue

            emp_id = str(user.emp_id)

            if emp_id in assigned:
                continue

            assigned.add(emp_id)
            eligible.append(user)

        if not eligible:
            return

        notification = create_referral_notification(
            referral=referral,
            notification_type=notification_type,
            title=title,
            message=message,
            users=eligible,
            target_url=target_url
        )

        if notification:
            notifications.append(notification)

    if include_hr:
        dispatch(hr_users, HR_EVALUATION_URL)

    if referrer:
        dispatch([referrer], REFERRER_URL)

    dispatch(reviewers, SBU_REVIEW_URL)

    return notifications


# ==========================================================
# REFERRAL SUBMISSION
# ==========================================================

def notify_referral_submitted(referral):
    """
    Fresher:
        Notify HR about academic verification.

    Experienced:
        Notify assigned SBU reviewers.

    HR employees are not excluded when they are referrers.
    """

    if referral.is_fresher:
        return create_referral_notification(
            referral=referral,
            notification_type="ACADEMIC_REQUIRED",
            title="Academic Details Required",
            message=(
                f"{referral.referrer.name} referred "
                f"{referral.candidate_name}. "
                f"Academic details must be verified "
                f"before SBU review."
            ),
            users=get_active_hr_users(),
            target_url=ACADEMIC_DETAILS_URL
        )

    return notify_sbu_review_assigned(referral)


def notify_sbu_review_assigned(referral):
    """
    Notify every assigned reviewer, including reviewers
    who are also HR employees or the original referrer.
    """

    return create_referral_notification(
        referral=referral,
        notification_type="REVIEW_ASSIGNED",
        title="New CV Referral Assigned",
        message=(
            f"{referral.candidate_name} has been referred "
            f"by {referral.referrer.name}. "
            f"Please review the candidate profile."
        ),
        users=get_assigned_sbu_reviewers(referral),
        target_url=SBU_REVIEW_URL
    )


# ==========================================================
# ACADEMIC DETAILS FINALIZED
# ==========================================================

def notify_academic_details_finalized(referral, hr_user=None):
    if not referral.is_fresher or referral.academic_details_status != "COMPLETED":
        return None

    referrer = get_referrer(referral)
    referrer_notification = None

    if referrer:
        referrer_notification = create_referral_notification(
            referral=referral,
            notification_type="ACADEMIC_COMPLETED",
            title="Candidate Ready for SBU Review",
            message=f"Academic details for {referral.candidate_name} have been finalized. The candidate has been forwarded for SBU review.",
            users=[referrer],
            target_url=REFERRER_URL,
            actor=hr_user
        )

    reviewer_notification = notify_sbu_review_assigned(referral)
    return [notification for notification in [referrer_notification, reviewer_notification] if notification]

# ==========================================================
# SBU REVIEW DECISION
# ==========================================================

def notify_sbu_review(
    referral,
    reviewer,
    decision,
    previous_decision=None,
    is_revision=False
):
    """
    Notify the referrer and assigned reviewers.

    Do not notify on unchanged decisions.
    """

    if decision not in ("CONSIDERED", "REJECTED"):
        return []

    if is_revision and previous_decision == decision:
        return []

    notification_type = (
        "SBU_REVISION"
        if is_revision
        else "SBU_DECISION"
    )

    title = (
        "SBU Review Decision Revised"
        if is_revision
        else "SBU Review Decision Submitted"
    )

    decision_label = (
        "To Be Considered"
        if decision == "CONSIDERED"
        else "Rejected"
    )

    if is_revision:
        previous_label = {
            "CONSIDERED": "To Be Considered",
            "REJECTED": "Rejected"
        }.get(previous_decision, "Pending")

        message = (
            f"{reviewer.name} revised the SBU decision "
            f"for {referral.candidate_name} "
            f"from {previous_label} to {decision_label}."
        )

    else:
        message = (
            f"{reviewer.name} reviewed "
            f"{referral.candidate_name} "
            f"and marked the decision as {decision_label}."
        )

    return notify_referrer_and_reviewers(
        referral=referral,
        notification_type=notification_type,
        title=title,
        message=message,
        actor=reviewer
    )


# ==========================================================
# HR EVALUATION ASSIGNMENT
# ==========================================================

def notify_hr_review_assigned(
    referral,
    reviewer=None,
    is_revision=False
):
    """
    Notify all HR employees when a candidate becomes
    eligible for HR evaluation.

    Trigger only when SBU status transitions to CONSIDERED.
    """

    if referral.current_status != "CONSIDERED":
        return None

    if HREvaluation.objects.filter(referral=referral).exists():
        return None

    reviewer_name = (
        reviewer.name
        if reviewer is not None
        else "An SBU reviewer"
    )

    title = (
        "Candidate Reconsidered for HR Evaluation"
        if is_revision
        else "New CV Awaiting HR Evaluation"
    )

    message = (
        f"{reviewer_name} marked "
        f"{referral.candidate_name} as "
        f"To Be Considered. "
        f"The candidate is now eligible "
        f"for HR evaluation."
    )

    return create_referral_notification(
        referral=referral,
        notification_type="HR_EVALUATION_UPDATED",
        title=title,
        message=message,
        users=get_active_hr_users(),
        target_url=HR_EVALUATION_URL
    )


# ==========================================================
# HR ELIGIBILITY REVOKED
# ==========================================================

def notify_hr_review_revoked(referral, reviewer=None):
    """
    Notify HR when a previously considered candidate
    becomes rejected before HR evaluation starts.
    """

    if referral.current_status != "REJECTED":
        return None

    if HREvaluation.objects.filter(referral=referral).exists():
        return None

    reviewer_name = (
        reviewer.name
        if reviewer is not None
        else "An SBU reviewer"
    )

    return create_referral_notification(
        referral=referral,
        notification_type="HR_EVALUATION_UPDATED",
        title="HR Evaluation Eligibility Revoked",
        message=(
            f"{reviewer_name} revised the SBU decision "
            f"for {referral.candidate_name} to Rejected. "
            f"The candidate is no longer eligible "
            f"for HR evaluation."
        ),
        users=get_active_hr_users(),
        target_url=HR_EVALUATION_URL
    )


# ==========================================================
# HR EVALUATION STARTED
# ==========================================================

def notify_hr_evaluation_started(referral, hr_user=None):
    """
    Retained for compatibility.

    This helper should only be called for a committed
    HR workflow transition, never SAVE_DRAFT.
    """

    actor_name = (
        hr_user.name
        if hr_user is not None
        else "HR"
    )

    return notify_referrer_and_reviewers(
        referral=referral,
        notification_type="HR_EVALUATION_STARTED",
        title="HR Evaluation Started",
        message=(
            f"{actor_name} started HR evaluation "
            f"for {referral.candidate_name}. "
            f"The SBU review is now locked."
        ),
        actor=hr_user,
        include_hr=True
    )


# ==========================================================
# HR EVALUATION PROGRESS
# ==========================================================

def notify_hr_evaluation_progress(
    referral,
    hr_user=None,
    stage=None,
    status=None
):
    """
    Retained for compatibility.

    Must not be called during draft saves.
    """

    stage_label = HR_STAGE_LABELS.get(
        stage,
        stage or "Evaluation"
    )

    status_label = HR_STATUS_LABELS.get(
        status,
        status or "Updated"
    )

    actor_name = (
        hr_user.name
        if hr_user is not None
        else "HR"
    )

    return notify_referrer_and_reviewers(
        referral=referral,
        notification_type="HR_EVALUATION_UPDATED",
        title="HR Evaluation Updated",
        message=(
            f"{actor_name} updated the evaluation "
            f"for {referral.candidate_name}. "
            f"Stage: {stage_label}. "
            f"Status: {status_label}."
        ),
        actor=hr_user,
        include_hr=True
    )


# ==========================================================
# HR EVALUATION FINALIZED
# ==========================================================

def notify_hr_evaluation_finalized(
    referral,
    hr_user,
    final_status
):
    """
    Notify referrer, reviewers and HR when the final
    HR decision is committed.

    Include meaningful decision and offer information.
    """

    status_label = {
        "ACCEPTED": "Selected",
        "REJECTED": "Rejected"
    }.get(final_status, final_status)

    actor_name = (
        hr_user.name
        if hr_user is not None
        else "HR"
    )

    message = (
        f"{actor_name} finalized the HR evaluation "
        f"for {referral.candidate_name}. "
        f"Final decision: {status_label}."
    )

    evaluation = (
        HREvaluation.objects
        .filter(
            referral=referral,
            evaluation_status="COMPLETED"
        )
        .order_by("-updated_at", "-id")
        .first()
    )

    if evaluation:
        if final_status == "REJECTED":
            stage_label = HR_STAGE_LABELS.get(
                evaluation.stage,
                evaluation.stage
            )

            if stage_label:
                message += (
                    f" Rejection stage: {stage_label}."
                )

        elif final_status == "ACCEPTED":
            if evaluation.offer_released:
                message += " Offer released."

            if evaluation.offer_outcome:
                outcome_label = OFFER_OUTCOME_LABELS.get(
                    evaluation.offer_outcome,
                    evaluation.offer_outcome
                )

                message += (
                    f" Offer outcome: {outcome_label}."
                )

            if (
                evaluation.offer_outcome == "JOINED"
                and evaluation.joining_date
            ):
                message += (
                    f" Joining date: "
                    f"{evaluation.joining_date.strftime('%d %b %Y')}."
                )

    return notify_referrer_and_reviewers(
        referral=referral,
        notification_type="HR_FINALIZED",
        title=f"HR Evaluation Finalized — {status_label}",
        message=message,
        actor=hr_user,
        include_hr=True
    )


# ==========================================================
# OFFER / JOINING UPDATES
# ==========================================================

def notify_offer_updated(
    referral,
    hr_user=None,
    offer_released=False,
    offer_outcome=None,
    joining_date=None
):
    """
    Retained for committed offer events.

    Draft offer changes must not trigger this helper.
    """

    if offer_outcome:
        outcome_label = OFFER_OUTCOME_LABELS.get(
            offer_outcome,
            offer_outcome
        )

        title = "Candidate Offer Outcome Updated"

        message = (
            f"Offer outcome for "
            f"{referral.candidate_name}: "
            f"{outcome_label}."
        )

        if (
            offer_outcome == "JOINED"
            and joining_date
        ):
            message += (
                f" Joining date: "
                f"{joining_date.strftime('%d %b %Y')}."
            )

    elif offer_released:
        title = "Candidate Offer Released"

        message = (
            f"An employment offer has been released "
            f"to {referral.candidate_name}."
        )

    else:
        return []

    return notify_referrer_and_reviewers(
        referral=referral,
        notification_type="OFFER_UPDATED",
        title=title,
        message=message,
        actor=hr_user,
        include_hr=True
    )