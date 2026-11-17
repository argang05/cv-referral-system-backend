from django.db import models
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MinValueValidator, MaxValueValidator
from decimal import Decimal
import uuid

# 1. Users Table
class User(models.Model):
    ROLE_CHOICES = [('EMPLOYEE', 'Employee'), ('REVIEWER', 'Reviewer'), ('HR', 'HR'), ('ADMIN', 'Admin')]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    emp_id = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    personal_email = models.EmailField(null=True, blank=True)
    password_og = models.TextField()
    password_hash = models.TextField()
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    is_active = models.BooleanField(default=True)
    department = ArrayField(models.CharField(max_length=100), default=list)
    is_hr = models.BooleanField(default=False)
    reporting_manager_emp_id = models.CharField(max_length=20, null=True, blank=True)
    reporting_manager_name = models.CharField(max_length=100, null=True, blank=True)
    band = models.CharField(max_length=10, null=True, blank=True)
    designation = models.CharField(max_length=100, null=True, blank=True)
    sub_bu = models.CharField(max_length=100, null=True, blank=True)
    manager = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='subordinates')

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def __str__(self):
        return f"{self.emp_id} - {self.name}"

# 2. SBU Reviewer Table
class SBU(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    personal_email = models.EmailField(null=True, blank=True)
    departments = models.JSONField(default=list)

    def __str__(self):
        return f"{self.name} ({self.email})"

# 3. Referral Table
class Referral(models.Model):
    CANDIDATE_TYPE_CHOICES = [
        ('INTERN_FRESHER', 'Internship - Fresher'),
        ('INTERN_EXPERIENCED', 'Internship - Experienced'),
        ('FULL_TIME_FRESHER', 'Full Time - Fresher'),
        ('FULL_TIME_EXPERIENCED', 'Full Time - Experienced')
    ]
    STATUS_CHOICES = [
        ('PENDING_REVIEW', 'Pending Review'),
        ('REJECTED', 'Rejected'),
        ('CONSIDERED', 'To Be Considered'),
        ('FINAL_ACCEPTED', 'Final Accepted'),
        ('FINAL_REJECTED', 'Final Rejected')
    ]
    REJECTION_STAGE_CHOICES = [('SBU', 'SBU'), ('HR', 'HR')]
    REFERRAL_REASON_CHOICES = [
        ('COURTESY', 'Courtesy Referral : Shared out of obligation or goodwill (e.g., customer, family, or acquaintance referral not aligned to any open role).'),
        ('POTENTIAL_FIT', 'Potential Fit Referral : Candidate with a strong background/skills; evaluation depends on role fitment and mutual interest.'),
        ('DIRECT_ROLE_FIT', 'Direct Role Fit Referral : Candidate clearly aligned with an existing open position and worth evaluating formally.'),
        ('INTERNAL_NETWORK', 'Internal Network Referral : Former colleague, vendor contact, or past intern with prior association with Tor or related teams.'),
        ('STRATEGIC', 'Strategic Referral : High-value or niche skillset candidate referred by leadership or key partner, considered for special review.')
    ]
    ACADEMIC_STATUS_CHOICES = [('PENDING', 'Pending'), ('DRAFT', 'Draft'), ('COMPLETED', 'Completed'), ('NOT_REQUIRED', 'Not Required')]
    referrer = models.ForeignKey(User, to_field='emp_id', db_column='referrer_emp_id', on_delete=models.CASCADE)
    job_posting = models.ForeignKey('JobVacancy', on_delete=models.SET_NULL, null=True, blank=True, related_name='referrals')
    candidate_name = models.CharField(max_length=100)
    candidate_email = models.EmailField(max_length=254, null=True, blank=True)
    candidate_phone = models.CharField(max_length=20, null=True, blank=True)
    candidate_type = models.CharField(max_length=30, choices=CANDIDATE_TYPE_CHOICES)
    referral_reason_type = models.CharField(max_length=30, choices=REFERRAL_REASON_CHOICES, default='COURTESY')
    sbus = models.ManyToManyField(SBU)
    cv_url = models.TextField()
    submitted_at = models.DateTimeField(auto_now_add=True)
    current_status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='PENDING_REVIEW')
    additional_comment = models.TextField(blank=True, null=True)
    rejection_stage = models.CharField(max_length=10, choices=REJECTION_STAGE_CHOICES, null=True, blank=True)
    rejection_reason = models.TextField(null=True, blank=True)
    tenth_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('100'))])
    twelfth_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('100'))])
    graduation_cgpa = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('10'))])
    academic_details_status = models.CharField(max_length=20, choices=ACADEMIC_STATUS_CHOICES, default='PENDING')
    academic_details_updated_at = models.DateTimeField(null=True, blank=True)
    academic_details_updated_by = models.ForeignKey(User, to_field='emp_id', on_delete=models.SET_NULL, null=True, blank=True, related_name='academic_details_updated_referrals')

    @property
    def is_fresher(self):
        return self.candidate_type.endswith('_FRESHER')

    @property
    def is_experienced(self):
        return self.candidate_type.endswith('_EXPERIENCED')

    def __str__(self):
        return f"{self.candidate_name} (Referred by {self.referrer.name})"

# 4. SBU Review Table
class Review(models.Model):
    DECISION_CHOICES = [('REJECTED', 'Rejected'), ('CONSIDERED', 'To Be Considered')]
    referral = models.ForeignKey(Referral, on_delete=models.CASCADE)
    reviewer = models.ForeignKey(User, on_delete=models.CASCADE)
    decision = models.CharField(max_length=20, choices=DECISION_CHOICES)
    comment = models.TextField()
    reviewed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Review for {self.referral.candidate_name} by {self.reviewer.name}"

# 5. HR Evaluation Table
class HREvaluation(models.Model):
    STAGE_CHOICES = [
        ('TEST', 'Test'),
        ('T1', 'Technical Round 1'),
        ('T2', 'Technical Round 2'),
        ('T3', 'Technical Round 3'),
        ('HR', 'HR Round'),
        ('OTHER', 'Other Reason')
    ]
    STATUS_CHOICES = [('IN_PROGRESS', 'In Progress'), ('ACCEPTED', 'Accepted'), ('REJECTED', 'Rejected')]
    EVALUATION_STATUS_CHOICES = [('DRAFT', 'Draft'), ('COMPLETED', 'Completed')]
    OFFER_OUTCOME_CHOICES = [('OFFER_DECLINED', 'Offer Declined'), ('DID_NOT_JOIN', 'Did Not Join'), ('JOINED', 'Joined')]
    referral = models.ForeignKey(Referral, on_delete=models.CASCADE)
    stage = models.CharField(max_length=20, choices=STAGE_CHOICES, blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    comment = models.TextField()
    updated_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='hr_updates')
    updated_at = models.DateTimeField(auto_now=True)
    evaluation_status = models.CharField(max_length=20, choices=EVALUATION_STATUS_CHOICES, default='DRAFT')
    finalized_at = models.DateTimeField(null=True, blank=True)
    finalized_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='finalized_hr_evaluations')
    offer_released = models.BooleanField(default=False)
    offer_outcome = models.CharField(max_length=20, choices=OFFER_OUTCOME_CHOICES, null=True, blank=True)
    joining_date = models.DateField(null=True, blank=True)

    @property
    def is_locked(self):
        return self.evaluation_status == 'COMPLETED'

    def __str__(self):
        return f"{self.referral.candidate_name} - {self.status} ({self.evaluation_status})"

# 6. HR Evaluation History
class HREvaluationHistory(models.Model):
    ACTION_CHOICES = [('SAVE_DRAFT', 'Save Draft'), ('FINALIZE', 'Finalize & Lock')]
    evaluation = models.ForeignKey(HREvaluation, on_delete=models.CASCADE, related_name='history')
    revision = models.PositiveIntegerField()
    stage = models.CharField(max_length=20, choices=HREvaluation.STAGE_CHOICES, blank=True, default='')
    status = models.CharField(max_length=20, choices=HREvaluation.STATUS_CHOICES)
    comment = models.TextField()
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='hr_evaluation_revisions')
    created_at = models.DateTimeField(auto_now_add=True)
    offer_released = models.BooleanField(default=False)
    offer_outcome = models.CharField(max_length=20, choices=HREvaluation.OFFER_OUTCOME_CHOICES, null=True, blank=True)
    joining_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ['-revision']
        constraints = [models.UniqueConstraint(fields=['evaluation', 'revision'], name='unique_hr_evaluation_revision')]

    def __str__(self):
        return f"HR Evaluation #{self.evaluation_id} - Revision {self.revision}"

# 7. Admin Configuration
class AdminConfig(models.Model):
    sbu = models.CharField(max_length=100)
    reviewer_ids = ArrayField(models.IntegerField(), size=2)
    hr_email_list = ArrayField(models.EmailField())

    def __str__(self):
        return f"Config for {self.sbu}"

# 8. Department Master
class Department(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    reviewers = models.JSONField()

    def __str__(self):
        return self.name

# 9. Email Templates
class EmailTemplate(models.Model):
    PURPOSE_CHOICES = [
        ('CV_TO_SBU', 'CV Referral (to SBU)'),
        ('CV_APPROVED_SBU', 'CV Referral Approved [By SBU]'),
        ('CV_REJECTED_SBU', 'CV Referral Disapproved [By SBU]'),
        ('CV_TO_HR', 'CV Referral to HR'),
        ('CV_APPROVED_HR', 'CV Referral Approved [By HR]'),
        ('CV_REJECTED_HR', 'CV Referral Disapproved [By HR]'),
        ('CV_UPDATED_SBU', 'CV Referral Updated [To SBU]'),
        ('CV_DELETED_SBU', 'CV Referral Deleted [To SBU]'),
        ('CV_APPROVED_SBU_REFERRER', 'CV Approved by SBU - Notify Referrer'),
        ('CV_APPROVED_SBU_TO_HR', 'CV Approved by SBU - Notify HR'),
        ('CV_REVOKED_BY_SBU', 'CV Approval Revoked by SBU - Notify HR')
    ]
    purpose = models.CharField(max_length=50, choices=PURPOSE_CHOICES, unique=True)
    subject = models.CharField(max_length=255)
    html_body = models.TextField()

    def __str__(self):
        return self.get_purpose_display()

# 10. Internal Job Posting / Job Vacancy
class JobVacancy(models.Model):
    STATUS_CHOICES = [('DRAFT', 'Draft'), ('OPEN', 'Open'), ('CLOSED', 'Closed'), ('ARCHIVED', 'Archived')]
    EMPLOYMENT_TYPE_CHOICES = [('INTERNSHIP', 'Internship'), ('FULL_TIME', 'Full-time')]
    MODE_CHOICES = [('WFH', 'Work From Home'), ('OFFICE', 'In Office'), ('HYBRID', 'Hybrid')]
    job_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    job_title = models.CharField(max_length=255)
    job_description = models.TextField()
    work_experience = models.CharField(max_length=100, help_text='Example: 2-4 years')
    job_desc_document_url = models.URLField(blank=True, null=True)
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default='OFFICE')
    location = models.CharField(max_length=255, blank=True, null=True)
    department = models.ForeignKey('Department', on_delete=models.PROTECT, null=True, blank=True, related_name='job_postings')
    employment_type = models.CharField(max_length=20, choices=EMPLOYMENT_TYPE_CHOICES, null=True, blank=True)
    education_summary = models.CharField(max_length=500, blank=True, default='')
    key_skills = models.TextField(blank=True, default='')
    min_experience = models.PositiveSmallIntegerField(null=True, blank=True)
    max_experience = models.PositiveSmallIntegerField(null=True, blank=True)
    functional_background = models.TextField(blank=True, default='')
    preferred_industry = models.TextField(blank=True, default='')
    behavioural_attributes = models.TextField(blank=True, default='')
    closing_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT', db_index=True)
    posted_by = models.ForeignKey('User', to_field='emp_id', on_delete=models.SET_NULL, null=True, blank=True, related_name='created_job_postings')
    published_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at'], name='ijp_status_created_idx'),
            models.Index(fields=['department', 'status'], name='ijp_department_status_idx'),
            models.Index(fields=['-published_at'], name='ijp_published_idx')
        ]

    def __str__(self):
        return f"{self.job_title} ({self.job_id})"

# 11. Job Posting Audit History
class JobPostingHistory(models.Model):
    ACTION_CHOICES = [
        ('CREATED', 'Created'),
        ('UPDATED', 'Updated'),
        ('PUBLISHED', 'Published'),
        ('CLOSED', 'Closed'),
        ('REOPENED', 'Reopened'),
        ('ARCHIVED', 'Archived')
    ]
    job = models.ForeignKey('JobVacancy', on_delete=models.PROTECT, related_name='history')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    performed_by = models.ForeignKey('User', to_field='emp_id', on_delete=models.SET_NULL, null=True, blank=True, related_name='job_posting_actions')
    changes = models.JSONField(default=dict, blank=True)
    previous_status = models.CharField(max_length=20, choices=JobVacancy.STATUS_CHOICES, null=True, blank=True)
    new_status = models.CharField(max_length=20, choices=JobVacancy.STATUS_CHOICES, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['job', '-created_at'], name='ijp_history_job_date_idx'),
            models.Index(fields=['action', '-created_at'], name='ijp_history_action_idx')
        ]

    def __str__(self):
        return f"{self.job.job_title} - {self.action}"

# 12. Shared In-App Notifications
class Notification(models.Model):
    NOTIFICATION_TYPE_CHOICES = [('NEW_JOB', 'New Job Posting')]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    notification_type = models.CharField(max_length=30, choices=NOTIFICATION_TYPE_CHOICES, default='NEW_JOB')
    job_posting = models.ForeignKey('JobVacancy', on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=255)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title

# 13. Employee Notification Read Tracking
class NotificationRead(models.Model):
    notification = models.ForeignKey('Notification', on_delete=models.CASCADE, related_name='read_records')
    employee = models.ForeignKey('User', to_field='emp_id', on_delete=models.CASCADE, related_name='read_notifications')
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['notification', 'employee'], name='unique_notification_employee_read')]

    def __str__(self):
        return f"{self.employee.name} read {self.notification.title}"

# 14. Legacy Job Applications - Preserved
class JobApplication(models.Model):
    applicant_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    job = models.ForeignKey('JobVacancy', on_delete=models.CASCADE, related_name='applicants')
    name = models.CharField(max_length=255)
    cv_url = models.URLField()
    appliers_emp_id = models.CharField(max_length=20, null=True, blank=True)
    applied_at = models.DateTimeField(auto_now_add=True)
    review_decision = models.JSONField(null=True, blank=True, default=None)

    def __str__(self):
        return f"{self.name} applied for {self.job.job_title}"