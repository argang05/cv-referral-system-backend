# api/serializers.py

from rest_framework import serializers
from api.models import Referral, User, Department, Review, HREvaluation

class UserResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['emp_id', 'name', 'email']

class ReferralSerializer(serializers.ModelSerializer):
    referrer = UserResponseSerializer()
    sbus = UserResponseSerializer(many=True)
    review = serializers.SerializerMethodField()
    hr_evaluation = serializers.SerializerMethodField()

    class Meta:
        model = Referral
        fields = [
            'id',
            'candidate_name',
            'candidate_type',
            'submitted_at',
            'considered_at',
            'final_at',
            'cv_url',
            'current_status',
            'rejection_stage',
            'additional_comment',
            'referrer',
            'sbus',
            'review',
            'hr_evaluation',
        ]

    def get_review(self, obj):
        review = Review.objects.filter(referral=obj).first()
        if review:
            return {
                "decision": review.decision,
                "comment": review.comment,
                "reviewed_at": review.reviewed_at,
                "reviewed_by": {
                    "emp_id": review.reviewer.emp_id,
                    "name": review.reviewer.name,
                    "email": review.reviewer.email,
                }
            }
        return None

    def get_hr_evaluation(self, obj):
        hr = HREvaluation.objects.filter(referral=obj).first()
        if hr:
            return {
                "stage": hr.stage,
                "status": hr.status,
                "comment": hr.comment,
                "updated_by": {
                    "emp_id": hr.updated_by.emp_id,
                    "name": hr.updated_by.name,
                    "email": hr.updated_by.email,
                },
                "updated_at": hr.updated_at,
            }
        return None
