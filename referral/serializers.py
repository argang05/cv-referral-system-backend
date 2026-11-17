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
            # NEW: Optional candidate contact details
            'candidate_email',
            'candidate_phone',
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

class AcademicDetailsSerializer(serializers.ModelSerializer):

    tenth_percentage = serializers.DecimalField(

        max_digits=5, decimal_places=2, min_value=0, max_value=100,

        required=False, allow_null=True

    )

    twelfth_percentage = serializers.DecimalField(

        max_digits=5, decimal_places=2, min_value=0, max_value=100,

        required=False, allow_null=True

    )

    graduation_cgpa = serializers.DecimalField(

        max_digits=4, decimal_places=2, min_value=0, max_value=10,

        required=False, allow_null=True

    )

    class Meta:

        model = Referral

        fields = ["tenth_percentage", "twelfth_percentage", "graduation_cgpa"]

    def validate(self, attrs):

        if not self.instance or not self.instance.is_fresher:

            raise serializers.ValidationError("Academic details are only applicable to fresher candidates.")

        action = self.context.get("action")

        if action == "FINALIZE":

            fields = ["tenth_percentage", "twelfth_percentage", "graduation_cgpa"]

            errors = {}

            for field in fields:

                value = attrs.get(field, getattr(self.instance, field))

                if value is None:

                    errors[field] = "This field is required before finalization."

            if errors:

                raise serializers.ValidationError(errors)

        return attrs