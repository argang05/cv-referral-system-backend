from rest_framework import serializers
from api.models import JobVacancy, JobApplication, JobPostingHistory, Referral

class JobApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobApplication
        fields = '__all__'
        read_only_fields = ['job', 'applicant_id', 'applied_at']

class JobPostingHistorySerializer(serializers.ModelSerializer):
    performed_by_name = serializers.CharField(source='performed_by.name', read_only=True, default=None)

    class Meta:
        model = JobPostingHistory
        fields = ['id', 'action', 'performed_by', 'performed_by_name', 'changes', 'created_at']

class JobReferralSerializer(serializers.ModelSerializer):
    referrer_name = serializers.CharField(source='referrer.name', read_only=True)
    referrer_emp_id = serializers.CharField(source='referrer.emp_id', read_only=True)
    sbu_decision = serializers.SerializerMethodField()
    hr_decision = serializers.SerializerMethodField()
    offer_released = serializers.SerializerMethodField()
    offer_outcome = serializers.SerializerMethodField()
    joining_date = serializers.SerializerMethodField()

    class Meta:
        model = Referral
        fields = ['id', 'candidate_name', 'candidate_type', 'referrer_name', 'referrer_emp_id', 'submitted_at', 'current_status', 'sbu_decision', 'hr_decision', 'offer_released', 'offer_outcome', 'joining_date']

    def get_sbu_decision(self, obj):
        review = obj.review_set.order_by('-reviewed_at', '-id').first()
        return review.decision if review else None

    def get_hr_evaluation(self, obj):
        if not hasattr(obj, '_ijphrevaluation'):
            obj._ijphrevaluation = obj.hrevaluation_set.order_by('-updated_at', '-id').first()
        return obj._ijphrevaluation

    def get_hr_decision(self, obj):
        evaluation = self.get_hr_evaluation(obj)
        return evaluation.status if evaluation else None

    def get_offer_released(self, obj):
        evaluation = self.get_hr_evaluation(obj)
        return evaluation.offer_released if evaluation else False

    def get_offer_outcome(self, obj):
        evaluation = self.get_hr_evaluation(obj)
        return evaluation.offer_outcome if evaluation else None

    def get_joining_date(self, obj):
        evaluation = self.get_hr_evaluation(obj)
        return evaluation.joining_date if evaluation else None

class JobVacancySerializer(serializers.ModelSerializer):
    applicants = JobApplicationSerializer(many=True, read_only=True)
    applicants_count = serializers.SerializerMethodField()
    department_name = serializers.CharField(source='department.name', read_only=True, default=None)
    posted_by_name = serializers.CharField(source='posted_by.name', read_only=True, default=None)
    referrals_count = serializers.SerializerMethodField()

    class Meta:
        model = JobVacancy
        fields = [
            'id', 'job_id', 'job_title', 'job_description', 'work_experience',
            'job_desc_document_url', 'mode', 'location', 'department',
            'department_name', 'employment_type', 'education_summary',
            'key_skills', 'min_experience', 'max_experience',
            'functional_background', 'preferred_industry',
            'behavioural_attributes', 'closing_date', 'status',
            'posted_by', 'posted_by_name', 'published_at', 'closed_at',
            'archived_at', 'created_at', 'updated_at', 'applicants',
            'applicants_count', 'referrals_count'
        ]
        read_only_fields = [
            'id', 'job_id', 'status', 'posted_by', 'published_at',
            'closed_at', 'archived_at', 'created_at', 'updated_at'
        ]
        extra_kwargs = {
            'job_title': {'required': False, 'allow_blank': True},
            'job_description': {'required': False, 'allow_blank': True},
            'work_experience': {'required': False, 'allow_blank': True},
            'location': {'required': False, 'allow_blank': True},
            'job_desc_document_url': {'required': False, 'allow_blank': True, 'allow_null': True},
            'department': {'required': False, 'allow_null': True},
            'employment_type': {'required': False, 'allow_null': True},
            'education_summary': {'required': False, 'allow_blank': True},
            'key_skills': {'required': False, 'allow_blank': True},
            'min_experience': {'required': False, 'allow_null': True},
            'max_experience': {'required': False, 'allow_null': True},
            'closing_date': {'required': False, 'allow_null': True}
        }

    def get_applicants_count(self, obj):
        return obj.applicants.count()

    def get_referrals_count(self, obj):
        return obj.referrals.count()

    def validate(self, attrs):
        minimum = attrs.get('min_experience', getattr(self.instance, 'min_experience', None))
        maximum = attrs.get('max_experience', getattr(self.instance, 'max_experience', None))

        if minimum is not None and maximum is not None and maximum < minimum:
            raise serializers.ValidationError({
                'max_experience': 'Maximum experience cannot be less than minimum experience.'
            })

        return attrs

class JobPostingDetailSerializer(JobVacancySerializer):
    history = JobPostingHistorySerializer(many=True, read_only=True)
    referrals = JobReferralSerializer(many=True, read_only=True)

    class Meta(JobVacancySerializer.Meta):
        fields = JobVacancySerializer.Meta.fields + ['history', 'referrals']

class EmployeeJobVacancySerializer(JobVacancySerializer):
    class Meta(JobVacancySerializer.Meta):
        fields = [
            field for field in JobVacancySerializer.Meta.fields
            if field not in ['applicants', 'applicants_count', 'posted_by']
        ]