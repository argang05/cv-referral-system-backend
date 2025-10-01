from django.db import models
from django.contrib.postgres.fields import ArrayField
import uuid
from django.contrib.postgres.fields import JSONField

# Create your models here.

# -----------------------------
# 1. Users Table
# -----------------------------
class User(models.Model):
    ROLE_CHOICES = [
        ('EMPLOYEE', 'Employee'),
        ('REVIEWER', 'Reviewer'),
        ('HR', 'HR'),
        ('ADMIN', 'Admin'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    emp_id = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    personal_email = models.EmailField(null=True, blank=True)  # ✅ new field
    password_og = models.TextField()
    password_hash = models.TextField()
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    is_active = models.BooleanField(default=True)
    department = ArrayField(models.CharField(max_length=100), default=list)
    is_hr = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.emp_id} - {self.name}"



# -----------------------------
# 2. SBU Table (used for M2M)
# -----------------------------
# in your models file (e.g., api/models.py or wherever SBU lives)
class SBU(models.Model):
    name = models.CharField(max_length=100)  # Reviewer name
    email = models.EmailField(unique=True)   # Reviewer email
    personal_email = models.EmailField(null=True, blank=True)  # NEW: optional personal email
    departments = models.JSONField(default=list)  # List of department names

    def __str__(self):
        return f"{self.name} ({self.email})"




# -----------------------------
# 3. Referral Table
# -----------------------------
class Referral(models.Model):
    CANDIDATE_TYPE_CHOICES = [
        ('INTERN', 'Internship'),
        ('FULL_TIME', 'Full Time'),
    ]
    STATUS_CHOICES = [
        ('PENDING_REVIEW', 'Pending Review'),
        ('REJECTED', 'Rejected'),
        ('CONSIDERED', 'To Be Considered'),
        ('FINAL_ACCEPTED', 'Final Accepted'),
        ('FINAL_REJECTED', 'Final Rejected'),
    ]

    REJECTION_STAGE_CHOICES = [
        ('SBU', 'SBU'),
        ('HR', 'HR'),
    ]

    REFERRAL_REASON_CHOICES = [
        ('PERSONAL_CONNECTION', 'Personal Connection Referral'),
        ('TALENT_BASED', 'Referral Based on Talent'),
    ]

    referrer = models.ForeignKey(User, to_field='emp_id', db_column='referrer_emp_id', on_delete=models.CASCADE)
    candidate_name = models.CharField(max_length=100)
    candidate_type = models.CharField(max_length=20, choices=CANDIDATE_TYPE_CHOICES)
    referral_reason_type = models.CharField(   # ✅ NEW FIELD
        max_length=30,
        choices=REFERRAL_REASON_CHOICES,
        default='PERSONAL_CONNECTION'
    )
    sbus = models.ManyToManyField(SBU)
    cv_url = models.TextField()
    submitted_at = models.DateTimeField(auto_now_add=True)
    current_status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='PENDING_REVIEW')
    additional_comment = models.TextField(blank=True, null=True)
    rejection_stage = models.CharField(max_length=10, choices=REJECTION_STAGE_CHOICES, null=True, blank=True)  # ✅ New
    rejection_reason = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"{self.candidate_name} (Referred by {self.referrer.name})"



# -----------------------------
# 4. Review Table
# -----------------------------
class Review(models.Model):
    DECISION_CHOICES = [
        ('REJECTED', 'Rejected'),
        ('CONSIDERED', 'To Be Considered'),
    ]

    referral = models.ForeignKey(Referral, on_delete=models.CASCADE)
    reviewer = models.ForeignKey(User, on_delete=models.CASCADE)
    decision = models.CharField(max_length=20, choices=DECISION_CHOICES)
    comment = models.TextField()
    reviewed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Review for {self.referral.candidate_name} by {self.reviewer.name}"





# -----------------------------
# 5. HR Evaluation Table
# -----------------------------
class HREvaluation(models.Model):
    STAGE_CHOICES = [
        ('TEST', 'Test'),
        ('T1', 'Technical Round 1'),
        ('T2', 'Technical Round 2'),
        ('T3', 'Technical Round 3'),
        ('HR', 'HR Round'),
        ('OTHER', 'Other Reason'),
    ]

    STATUS_CHOICES = [
        ('IN_PROGRESS', 'In Progress'),
        ('ACCEPTED', 'Accepted'),
        ('REJECTED', 'Rejected'),
    ]

    # referral = models.ForeignKey(Referral, on_delete=models.CASCADE)
    referral = models.ForeignKey(Referral, on_delete=models.CASCADE)
    stage = models.CharField(max_length=20, choices=STAGE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    comment = models.TextField()
    updated_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="hr_updates")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.referral.candidate_name} - {self.stage} ({self.status})"


# -----------------------------
# 6. Admin Config Table
# -----------------------------
class AdminConfig(models.Model):
    sbu = models.CharField(max_length=100)
    reviewer_ids = ArrayField(models.IntegerField(), size=2)  # Store reviewer User IDs
    hr_email_list = ArrayField(models.EmailField())

    def __str__(self):
        return f"Config for {self.sbu}"


class Department(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    reviewers = models.JSONField()  # list of {"name": ..., "email": ...} dicts

    def __str__(self):
        return self.name

class EmailTemplate(models.Model):
    PURPOSE_CHOICES = [
        ("CV_TO_SBU", "CV Referral (to SBU)"),
        ("CV_APPROVED_SBU", "CV Referral Approved [By SBU]"),
        ("CV_REJECTED_SBU", "CV Referral Disapproved [By SBU]"),
        ("CV_TO_HR", "CV Referral to HR"),
        ("CV_APPROVED_HR", "CV Referral Approved [By HR]"),
        ("CV_REJECTED_HR", "CV Referral Disapproved [By HR]"),
        ("CV_UPDATED_SBU", "CV Referral Updated [To SBU]"),
        ("CV_DELETED_SBU", "CV Referral Deleted [To SBU]"),

        # ✅ Previously added
        ("CV_APPROVED_SBU_REFERRER", "CV Approved by SBU - Notify Referrer"),
        ("CV_APPROVED_SBU_TO_HR", "CV Approved by SBU - Notify HR"),

        # ✅ New for revoked approval case
        ("CV_REVOKED_BY_SBU", "CV Approval Revoked by SBU - Notify HR"),
    ]

    purpose = models.CharField(max_length=50, choices=PURPOSE_CHOICES, unique=True)
    subject = models.CharField(max_length=255)
    html_body = models.TextField()

    def __str__(self):
        return self.get_purpose_display()
