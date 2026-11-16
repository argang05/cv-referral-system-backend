import httpx
import os
import logging

from django.template import Template, Context
from django.utils.html import strip_tags

from .models import EmailTemplate


logger = logging.getLogger(__name__)


# ============================================================
# SUPABASE CONFIGURATION
# ============================================================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET")


# ============================================================
# SUPABASE FILE UPLOAD
# ============================================================

def upload_to_supabase(file_obj, file_name):
    upload_url = (
        f"{SUPABASE_URL}/storage/v1/object/"
        f"{SUPABASE_BUCKET}/{file_name}"
    )

    headers = {
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "apikey": SUPABASE_KEY,
        "Content-Type": "application/octet-stream"
    }

    response = httpx.put(
        upload_url,
        content=file_obj.read(),
        headers=headers,
        timeout=30
    )

    if response.status_code == 200:
        return (
            f"{SUPABASE_URL}/storage/v1/object/public/"
            f"{SUPABASE_BUCKET}/{file_name}"
        )

    raise Exception(
        f"Upload failed: {response.status_code} — {response.text}"
    )


# ============================================================
# BREVO EMAIL CONFIGURATION
# ============================================================

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


# ============================================================
# BREVO EMAIL DELIVERY
# ============================================================

def send_email_via_brevo(subject, html_body, to_emails):
    """
    Send an HTML email using Brevo's HTTPS REST API.

    Returns:
        True  -> Brevo accepted the email request.
        False -> Email request failed.

    Does not use Gmail SMTP.
    """

    api_key = os.getenv("BREVO_API_KEY")

    sender_email = os.getenv("BREVO_SENDER_EMAIL")

    sender_name = os.getenv(
        "BREVO_SENDER_NAME",
        "CV Referral System"
    )

    # --------------------------------------------------------
    # Validate Brevo configuration
    # --------------------------------------------------------

    if not api_key:
        logger.error(
            "BREVO_API_KEY is missing from environment variables."
        )
        return False

    if not sender_email:
        logger.error(
            "BREVO_SENDER_EMAIL is missing from environment variables."
        )
        return False

    # --------------------------------------------------------
    # Validate and clean recipients
    # --------------------------------------------------------

    if isinstance(to_emails, str):
        to_emails = [to_emails]

    valid_emails = list(
        dict.fromkeys(
            email.strip()
            for email in (to_emails or [])
            if isinstance(email, str) and email.strip()
        )
    )

    if not valid_emails:
        logger.warning(
            "Email not sent: No valid recipient addresses."
        )
        return False

    # --------------------------------------------------------
    # Prepare email payload
    # --------------------------------------------------------

    payload = {
        "sender": {
            "name": sender_name,
            "email": sender_email
        },

        "to": [
            {"email": email}
            for email in valid_emails
        ],

        "subject": subject,

        "htmlContent": html_body,

        "textContent": strip_tags(html_body) or " "
    }

    headers = {
        "api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    # --------------------------------------------------------
    # Send email using HTTPS
    # --------------------------------------------------------

    try:
        response = httpx.post(
            BREVO_API_URL,
            headers=headers,
            json=payload,
            timeout=10
        )

        response.raise_for_status()

        logger.info(
            "Brevo accepted email request. Recipients: %s",
            len(valid_emails)
        )

        return True

    except httpx.HTTPStatusError as exc:
        logger.error(
            "Brevo API error: HTTP %s - %s",
            exc.response.status_code,
            exc.response.text[:500]
        )

        return False

    except httpx.RequestError:
        logger.exception(
            "Brevo email API connection failed."
        )

        return False


# ============================================================
# DYNAMIC EMAIL TEMPLATE SYSTEM
# ============================================================

def send_dynamic_email(purpose, to_emails, context_data):
    """
    Sends emails using the existing EmailTemplate database model.

    Preserves:
        - EmailTemplate model
        - Dynamic HTML templates
        - Django template placeholders
        - Existing function signature
        - Existing notification triggers

    Example:
        send_dynamic_email(
            purpose="CV_TO_SBU",
            to_emails=["reviewer@example.com"],
            context_data={
                "candidate_name": "John Doe",
                "portal_link": "https://example.com"
            }
        )

    Returns:
        True  -> Email request accepted by Brevo.
        False -> Email request failed.
    """

    try:
        # ----------------------------------------------------
        # Fetch existing email template from database
        # ----------------------------------------------------

        template_obj = EmailTemplate.objects.get(
            purpose=purpose
        )

        # ----------------------------------------------------
        # Retrieve existing subject
        # ----------------------------------------------------

        subject = template_obj.subject

        # ----------------------------------------------------
        # Render existing HTML template
        # ----------------------------------------------------

        html_template = Template(
            template_obj.html_body
        )

        html_body = html_template.render(
            Context(context_data)
        )

        # ----------------------------------------------------
        # Send rendered email through Brevo
        # ----------------------------------------------------

        return send_email_via_brevo(
            subject=subject,
            html_body=html_body,
            to_emails=to_emails
        )

    except EmailTemplate.DoesNotExist:
        logger.warning(
            "Email template not found for purpose: %s",
            purpose
        )

        return False

    except Exception:
        logger.exception(
            "Failed to process dynamic email for purpose: %s",
            purpose
        )

        return False