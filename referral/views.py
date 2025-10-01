# referral/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from api.models import Referral, User, SBU
from django.utils.timezone import now
from rest_framework.permissions import AllowAny
from rest_framework.parsers import MultiPartParser, FormParser,JSONParser
from api.models import Review, HREvaluation
from api.utils import send_dynamic_email
from django.conf import settings
from .serializers import ReferralSerializer


class SubmitReferralView(APIView):
    parser_classes = [JSONParser]  # Accept JSON

    def post(self, request):
        print("Referral Data: ", request.data)
        emp_id = request.data.get("emp_id")
        candidate_name = request.data.get("candidate_name")
        candidate_type = request.data.get("candidate_type")
        referral_reason_type = request.data.get("referral_reason_type")  # ✅ New field
        sbu_emails = request.data.get("sbu_emails", [])
        cv_url = request.data.get("cv_url")
        additional_comment = request.data.get("additional_comment", "")

        print("SBU Emails: ", sbu_emails)

        if not (emp_id and candidate_name and candidate_type and sbu_emails and cv_url and referral_reason_type):
            return Response({"error": "Missing required fields."}, status=400)

        try:
            user = User.objects.get(emp_id=emp_id)
        except User.DoesNotExist:
            return Response({"error": "User not found."}, status=404)

        referral = Referral.objects.create(
            referrer=user,
            candidate_name=candidate_name,
            candidate_type=candidate_type,
            referral_reason_type=referral_reason_type,   # ✅ Save new field
            cv_url=cv_url,
            submitted_at=now(),
            current_status="PENDING_REVIEW",
            additional_comment=additional_comment
        )

        matched_sbus = SBU.objects.filter(email__in=sbu_emails)
        print("Matched SBUs:", matched_sbus.count())
        referral.sbus.set(matched_sbus)

        recipients = [sbu.personal_email for sbu in referral.sbus.all()]
        print("Recipients: ", recipients)

        portal_link = f"{settings.FRONTEND_BASE_URL}/review-cv"

        send_dynamic_email(
            purpose='CV_TO_SBU',
            to_emails=['abgang05@gmail.com'],  # 🔄 replace with recipients later
            context_data={
                'candidate_name': referral.candidate_name,
                'portal_link': portal_link
            }
        )

        return Response({"message": "Referral submitted successfully."}, status=201)


# referral/views.py
class MyReferralsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        emp_id = request.query_params.get("emp_id")
        if not emp_id:
            return Response({"error": "Missing emp_id"}, status=400)

        try:
            user = User.objects.get(emp_id=emp_id)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=404)

        referrals = Referral.objects.filter(referrer=user).order_by('-submitted_at')
        data = []

        for r in referrals:
            latest_review = Review.objects.filter(referral=r).order_by('-reviewed_at').first()
            latest_eval = HREvaluation.objects.filter(referral=r).order_by('-updated_at').first()

            data.append({
                "id": r.id,
                "candidate_name": r.candidate_name,
                "candidate_type": r.candidate_type,
                "referral_reason_type": r.referral_reason_type,  # ✅ Added
                "submitted_at": r.submitted_at,
                "current_status": r.current_status,
                "cv_url": r.cv_url,
                "sbus": [{"name": s.name, "email": s.email} for s in r.sbus.all()],
                "additional_comment": r.additional_comment,
                "rejection_stage": r.rejection_stage,
                "rejection_reason": r.rejection_reason,
                "referrer": {
                    "emp_id": r.referrer.emp_id,
                    "name": r.referrer.name,
                    "email": r.referrer.email
                },
                "considered_at": latest_review.reviewed_at if latest_review else None,
                "final_at": latest_eval.updated_at if latest_eval else None,
                "review": {
                    "decision": latest_review.decision,
                    "comment": latest_review.comment,
                    "reviewed_at": latest_review.reviewed_at,
                    "reviewed_by": latest_review.reviewer.name
                } if latest_review else None,
                "hr_evaluation": {
                    "stage": latest_eval.stage,
                    "status": latest_eval.status,
                    "comment": latest_eval.comment,
                    "updated_at": latest_eval.updated_at,
                    "updated_by": latest_eval.updated_by.name
                } if latest_eval else None
            })

        return Response(data)

class UpdateReferralView(APIView):
    parser_classes = [JSONParser]
    permission_classes = [AllowAny]

    def put(self, request, referral_id):
        try:
            referral = Referral.objects.get(id=referral_id)
        except Referral.DoesNotExist:
            return Response({"error": "Referral not found."}, status=404)

        # Ensure the referrer is making the request
        emp_id = request.data.get('emp_id')
        if referral.referrer.emp_id != emp_id:
            return Response({"error": "Unauthorized"}, status=403)

        # Update fields
        referral.candidate_name = request.data.get('candidate_name', referral.candidate_name)
        referral.candidate_type = request.data.get('candidate_type', referral.candidate_type)
        referral.referral_reason_type = request.data.get('referral_reason_type', referral.referral_reason_type)  # ✅ NEW
        referral.additional_comment = request.data.get('additional_comment', referral.additional_comment)

        cv_url = request.data.get('cv_url')
        if cv_url:
            referral.cv_url = cv_url

        referral.save()

        recipients = [sbu.personal_email for sbu in referral.sbus.all()]
        print("Recipients:", recipients) 
        send_dynamic_email(
            purpose="CV_UPDATED_SBU",
            to_emails=["abgang05@gmail.com"],  # Replace later with recipients
            context_data={
                "candidate_name": referral.candidate_name,
                "portal_link": f"{settings.FRONTEND_BASE_URL}/review-cv"
            }
        )
        return Response({"message": "Referral updated successfully."}, status=200)

class DeleteReferralView(APIView):
    permission_classes = [AllowAny]

    def delete(self, request, referral_id):
        try:
            referral = Referral.objects.get(id=referral_id)
        except Referral.DoesNotExist:
            return Response({"error": "Referral not found."}, status=404)

        emp_id = request.query_params.get("emp_id")
        if referral.referrer.emp_id != emp_id:
            return Response({"error": "Unauthorized"}, status=403)

        recipients = [sbu.personal_email for sbu in referral.sbus.all()]
        print("Recipients:", recipients) 
        send_dynamic_email(
            purpose="CV_DELETED_SBU",
            to_emails=["abgang05@gmail.com"], # ✅ Set this to recipients to see in action
            context_data={
                "candidate_name": referral.candidate_name
            }
        )

        referral.delete()
        return Response(status=204)

