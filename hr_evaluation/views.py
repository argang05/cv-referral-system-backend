from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from api.models import Referral, User, Review, HREvaluation
from .serializers import HREvaluationSerializer  # you'll define this
from django.utils.timezone import now
from api.utils import send_dynamic_email
from django.conf import settings

class HREvaluationView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        approved_referrals = Referral.objects.filter(
            current_status__in=['CONSIDERED', 'FINAL_ACCEPTED', 'FINAL_REJECTED']
        ).distinct()
        data = []
        
        for r in approved_referrals:
            review = Review.objects.filter(referral=r).first()
            hr_eval = HREvaluation.objects.filter(referral=r).first()
            latest_review = Review.objects.filter(referral=r).order_by('-reviewed_at').first()
            latest_eval = HREvaluation.objects.filter(referral=r).order_by('-updated_at').first()
            
            data.append({
                "id": r.id,
                "candidate_name": r.candidate_name,
                "candidate_type": r.candidate_type,
                "submitted_at": r.submitted_at,
                "considered_at": latest_review.reviewed_at if latest_review else None,
                "final_at": latest_eval.updated_at if latest_eval else None,
                "current_status": r.current_status,
                "cv_url": r.cv_url,
                "sbus": [{"name": s.name, "email": s.email} for s in r.sbus.all()],
                "additional_comment": r.additional_comment,
                "referrer": {
                    "emp_id": r.referrer.emp_id,
                    "name": r.referrer.name,
                    "email": r.referrer.email
                },
                "review": {
                    "decision": review.decision,
                    "comment": review.comment,
                    "reviewed_at": review.reviewed_at
                } if review else None,
                "hr_evaluation": {
                    "stage": hr_eval.stage,
                    "status": hr_eval.status,
                    "comment": hr_eval.comment,
                    "updated_by": hr_eval.updated_by.name,
                    "updated_at": hr_eval.updated_at,
                } if hr_eval else None
            })
        
        return Response(data)


    def post(self, request):
        print("POST payload:", request.data)
        data = request.data
        referral_id = data.get('referral_id')
        user_id = data.get('emp_id')
        stage = data.get('stage')
        status = data.get('status')
        comment = data.get('comment')

        try:
            referral = Referral.objects.get(id=referral_id)
            user = User.objects.get(emp_id=user_id)
        except (Referral.DoesNotExist, User.DoesNotExist):
            return Response({"error": "Referral or user not found"}, status=404)

        evaluation = HREvaluation.objects.create(
            referral=referral,
            updated_by=user,
            stage=stage,
            status=status,
            comment=comment
        )

        # Update referral timestamps
        referral.final_at = now()
        if status == "REJECTED":
            referral.current_status = "FINAL_REJECTED"
            referral.rejection_stage = "HR"
            referral.rejection_reason = comment
            referrerEmail = referral.referrer.email
            print("Recipient Email: ",referrerEmail)
            send_dynamic_email(
                purpose="CV_REJECTED_HR",
                to_emails=["abhishek.ganguly@tor.ai"],
                context_data={
                    "candidate_name": referral.candidate_name,
                    "portal_link": f"{settings.FRONTEND_BASE_URL}/",
                    "rejection_reason": comment
                }
            )
        elif status == "ACCEPTED":
            referral.current_status = "FINAL_ACCEPTED"
            referrerEmail = referral.referrer.email
            print("Recipient Email: ",referrerEmail)
            send_dynamic_email(
                purpose="CV_APPROVED_HR",
                to_emails=["abhishek.ganguly@tor.ai"],
                context_data={
                    "candidate_name": referral.candidate_name,
                    "portal_link": f"{settings.FRONTEND_BASE_URL}/"
                }
            )
        referral.save()

        return Response({"message": "Evaluation submitted successfully"})

    def put(self, request):
        print("PUT payload:", request.data)
        data = request.data
        referral_id = data.get('referral_id')
        user_id = data.get('emp_id')

        try:
            eval_obj = HREvaluation.objects.get(referral__id=referral_id)

            # Update evaluation fields
            eval_obj.stage = data.get('stage')
            eval_obj.status = data.get('status')
            eval_obj.comment = data.get('comment')
            eval_obj.updated_by = User.objects.get(emp_id=user_id)
            eval_obj.save()

            # Update referral status accordingly
            referral = eval_obj.referral
            referral.final_at = now()
            comment = data.get('comment')  # 👈 Always pull from data directly

            if eval_obj.status == 'REJECTED':
                referral.current_status = 'FINAL_REJECTED'
                referral.rejection_stage = 'HR'
                referral.rejection_reason = comment  # ✅ updated from request directly
                referral.save()

                referrerEmail = referral.referrer.email
                print("Recipient: ",referrerEmail)
                print("Rejection Reason:", comment)
                send_dynamic_email(
                    purpose="CV_REJECTED_HR",
                    to_emails=['abhishek.ganguly@tor.ai'],
                    context_data={
                        "candidate_name": referral.candidate_name,
                        "portal_link": f"{settings.FRONTEND_BASE_URL}/",
                        "rejection_reason": comment  # ✅ Pass explicitly
                    }
                )

            elif eval_obj.status == 'ACCEPTED':
                referral.current_status = 'FINAL_ACCEPTED'
                referral.rejection_stage = None
                referral.rejection_reason = None
                referral.save()

                referrerEmail = referral.referrer.email
                print("Recipient: ",referrerEmail)
                send_dynamic_email(
                    purpose="CV_APPROVED_HR",
                    to_emails=['abhishek.ganguly@tor.ai'],
                    context_data={
                        "candidate_name": referral.candidate_name,
                        "portal_link": f"{settings.FRONTEND_BASE_URL}/"
                    }
                )

            return Response({"message": "Evaluation updated"})

        except HREvaluation.DoesNotExist:
            return Response({"error": "Evaluation not found"}, status=404)