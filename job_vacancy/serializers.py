# job_vacancy/serializers.py
from rest_framework import serializers
from api.models import JobVacancy, JobApplication


class JobApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobApplication
        fields = '__all__'
        read_only_fields = ['job', 'applicant_id', 'applied_at']


class JobVacancySerializer(serializers.ModelSerializer):
    applicants = JobApplicationSerializer(many=True, read_only=True)  # ✅ Include nested applicants
    applicants_count = serializers.SerializerMethodField()

    class Meta:
        model = JobVacancy
        fields = [
            "id",
            "job_id",
            "job_title",
            "job_description",
            "work_experience",
            "job_desc_document_url",
            "mode",
            "location",
            "created_at",
            "updated_at",
            "applicants",
            "applicants_count",
        ]

    def get_applicants_count(self, obj):
        return obj.applicants.count()
