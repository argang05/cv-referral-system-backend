import httpx
import os
import smtplib
from django.core.mail import send_mail
from django.template import Template, Context
from django.conf import settings
from .models import EmailTemplate  # Assuming you have this model

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")  # This should be your anon/public API key
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET")

def upload_to_supabase(file_obj, file_name):
    upload_url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{file_name}"

    headers = {
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "apikey": SUPABASE_KEY,
        "Content-Type": "application/octet-stream"
    }

    response = httpx.put(upload_url, content=file_obj.read(), headers=headers)

    if response.status_code == 200:
        return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{file_name}"
    else:
        raise Exception(f"Upload failed: {response.status_code} — {response.text}")


def send_dynamic_email(purpose, to_emails, context_data):
    """
    Sends an email using a stored HTML template with dynamic values.

    Args:
    - purpose: str → like 'CV_TO_SBU'
    - to_emails: list → list of recipient email strings
    - context_data: dict → e.g., {'candidate_name': 'John Doe', 'portal_link': 'https://portal.link'}

    Example:
    send_dynamic_email(
        'CV_TO_SBU',
        ['reviewer@tor.ai'],
        {'candidate_name': 'John Doe', 'portal_link': 'https://portal.cv/123'}
    )
    """
    try:
        template_obj = EmailTemplate.objects.get(purpose=purpose)
        subject = template_obj.subject
        html_template = Template(template_obj.html_body)
        html_body = html_template.render(Context(context_data))

        send_mail(
            subject=subject,
            message='',  # Fallback plain text can be added optionally
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=to_emails,
            html_message=html_body,
            fail_silently=False
        )
    except EmailTemplate.DoesNotExist:
        print(f"Email template for purpose '{purpose}' not found.")


# backend/cvrsbackend/api/utils/reviewer_mapping.py

REVIEWER_SBU_MAPPING = {
    "Software Development": [
        {"name": "Aditya Avinash Kelkar", "email": "aditya.kelkar@tor.ai"},
        {"name": "Jatin Sudhakar Bhole", "email": "jatin.bhole@tor.ai"},
        {"name": "Shweta Pawan Kulkarni", "email": "shweta.kulkarni@tor.ai"}
    ],
    "Hardware Development": [
        {"name": "Aditya Avinash Kelkar", "email": "aditya.kelkar@tor.ai"},
        {"name": "Milind Madhav Vaze", "email": "milind.vaze@tor.ai"},
        {"name": "Shweta Pawan Kulkarni", "email": "shweta.kulkarni@tor.ai"}
    ],
    "Firmware Development": [
        {"name": "Aditya Avinash Kelkar", "email": "aditya.kelkar@tor.ai"},
        {"name": "Hrishikesh Raghunath Limaye", "email": "hrishikesh.limaye@tor.ai"},
        {"name": "Shweta Pawan Kulkarni", "email": "shweta.kulkarni@tor.ai"}
    ],
    "Finance & Legal": [
        {"name": "Aditya Kiran Paranjpe", "email": "aditya.paranjpe@tor.ai"},
        {"name": "Priyanka Pawan Agarwal", "email": "priyanka.agarwal@tor.ai"},
        {"name": "Shweta Pawan Kulkarni", "email": "shweta.kulkarni@tor.ai"}
    ],
    "Support-IOT": [
        {"name": "Swati Prasad Chavare", "email": "swati.chavare@tor.ai"},
        {"name": "Makarand Vinayak Jadhav", "email": "makarand.jadhav@tor.ai"},
        {"name": "Shweta Pawan Kulkarni", "email": "shweta.kulkarni@tor.ai"}
    ],
    "Strategic Partnership and SEA": [
        {"name": "Rajesh Vidydhar Kulkarni", "email": "rajesh.kulkarni@tor.ai"},
        {"name": "Omkar Vishwas Pant", "email": "omkar.pant@tor.ai"},
        {"name": "Shweta Pawan Kulkarni", "email": "shweta.kulkarni@tor.ai"}
    ],
    "Quality Assurance": [
        {"name": "Aditya Avinash Kelkar", "email": "aditya.kelkar@tor.ai"},
        {"name": "Milind Madhav Vaze", "email": "milind.vaze@tor.ai"},
        {"name": "Ravindra Babasaheb Barbade", "email": "ravindra.barbade@tor.ai"},
        {"name": "Shweta Pawan Kulkarni", "email": "shweta.kulkarni@tor.ai"}
    ],
    "Production": [
        {"name": "Swati Prasad Chavare", "email": "swati.chavare@tor.ai"},
        {"name": "Nilesh Bhausaheb Mungase", "email": "nilesh.mungase@tor.ai"},
        {"name": "Shweta Pawan Kulkarni", "email": "shweta.kulkarni@tor.ai"}
    ],
    "Implementation": [
        {"name": "Swati Prasad Chavare", "email": "swati.chavare@tor.ai"},
        {"name": "Makarand Vinayak Jadhav", "email": "makarand.jadhav@tor.ai"},
        {"name": "Shweta Pawan Kulkarni", "email": "shweta.kulkarni@tor.ai"}
    ],
    "Supply Chain Management": [
        {"name": "Swati Prasad Chavare", "email": "swati.chavare@tor.ai"},
        {"name": "Siddhi Sandip Phatak", "email": "siddhi.phatak@tor.ai"},
        {"name": "Shweta Pawan Kulkarni", "email": "shweta.kulkarni@tor.ai"}
    ],
    "Business Development": [
        {"name": "Rajesh Vidydhar Kulkarni", "email": "rajesh.kulkarni@tor.ai"},
        {"name": "Ashish Arbindkumar Pathak Bharadwaj", "email": "ashish.bharadwaj@tor.ai"},
        {"name": "Ganesh Manikrao Kamble", "email": "ganesh.kamble@tor.ai"},
        {"name": "Shweta Pawan Kulkarni", "email": "shweta.kulkarni@tor.ai"}
    ],
    "Product Management": [
        {"name": "Aditya Kiran Paranjpe", "email": "aditya.paranjpe@tor.ai"},
        {"name": "Rohit Motilal Pandita", "email": "rohit.pandita@tor.ai"},
        {"name": "Shweta Pawan Kulkarni", "email": "shweta.kulkarni@tor.ai"}
    ],
    "Marketing": [
        {"name": "Rajesh Vidydhar Kulkarni", "email": "rajesh.kulkarni@tor.ai"},
        {"name": "Ashish Arbindkumar Pathak Bharadwaj", "email": "ashish.bharadwaj@tor.ai"},
        {"name": "Ganesh Manikrao Kamble", "email": "ganesh.kamble@tor.ai"},
        {"name": "Shweta Pawan Kulkarni", "email": "shweta.kulkarni@tor.ai"}
    ],
    "Sales": [
        {"name": "Rajesh Vidydhar Kulkarni", "email": "rajesh.kulkarni@tor.ai"},
        {"name": "Vaibhav Pramodrao Dhole", "email": "vaibhav.dhole@tor.ai"},
        {"name": "Shweta Pawan Kulkarni", "email": "shweta.kulkarni@tor.ai"}
    ],
    "Human Resource Management": [
        {"name": "Aditya Kiran Paranjpe", "email": "aditya.paranjpe@tor.ai"},
        {"name": "Abhishek Ganguly", "email": "abhishek.ganguly@tor.ai"},
        {"name": "Shweta Pawan Kulkarni", "email": "shweta.kulkarni@tor.ai"}
    ],
    "Systems Management": [
        {"name": "Aditya Avinash Kelkar", "email": "aditya.kelkar@tor.ai"},
        {"name": "Jatin Sudhakar Bhole", "email": "jatin.bhole@tor.ai"},
        {"name": "Shweta Pawan Kulkarni", "email": "shweta.kulkarni@tor.ai"}
    ]
}

def get_role_and_departments(email: str):
    email = email.lower()
    matched_departments = []

    for dept, reviewers in REVIEWER_SBU_MAPPING.items():
        for reviewer in reviewers:
            if reviewer["email"].lower() == email:
                matched_departments.append(dept)

    is_hr = any("human resource" in dept.lower() for dept in matched_departments)

    if matched_departments:
        role = "REVIEWER"
    else:
        role = "EMPLOYEE"
        matched_departments = ["NONE"]
        is_hr = False

    return role, matched_departments, is_hr
    email = email.lower()
    matched_departments = []

    for dept, reviewers in REVIEWER_SBU_MAPPING.items():
        for reviewer in reviewers:
            if reviewer["email"].lower() == email:
                matched_departments.append(dept)

    if not matched_departments:
        return "EMPLOYEE", ["NONE"]

    role = "HR" if any("human resource" in dept.lower() for dept in matched_departments) else "REVIEWER"
    return role, matched_departments



