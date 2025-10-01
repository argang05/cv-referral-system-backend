from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from api.models import Referral, Review, User
from api.models import SBU, HREvaluation
from django.utils import timezone
from django.utils.timezone import now
from django.core.mail import send_mail
from api.utils import send_dynamic_email
from django.conf import settings

class CVsForReview(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        emp_id = request.GET.get("emp_id")
        if not emp_id:
            return Response({"error": "emp_id is required"}, status=400)

        try:
            user = User.objects.get(emp_id=emp_id)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=404)

        referrals = Referral.objects.filter(sbus__email=user.email).distinct()
        data = []

        for r in referrals:
            review = Review.objects.filter(referral=r, reviewer=user).order_by('-reviewed_at').first()
            hr_eval = HREvaluation.objects.filter(referral=r).order_by('-updated_at').first()

            review_data = {
                "decision": review.decision,
                "comment": review.comment,
                "reviewed_at": review.reviewed_at,
                "reviewed_by": review.reviewer.name
            } if review else None

            if review and review.decision == 'REJECTED' and r.current_status != 'REJECTED':
                r.current_status = 'REJECTED'
                r.rejection_stage = 'SBU'
                r.rejection_reason = review.comment
                if not r.considered_at:
                    r.considered_at = review.reviewed_at
                r.save()

            data.append({
                "id": r.id,
                "candidate_name": r.candidate_name,
                "candidate_type": r.candidate_type,
                "submitted_at": r.submitted_at,
                "referral_reason_type": r.referral_reason_type,  # ✅ Added
                "current_status": r.current_status,
                "rejection_stage": r.rejection_stage,
                "rejection_reason": r.rejection_reason,
                "cv_url": r.cv_url,
                "sbus": [{"name": s.name, "email": s.email} for s in r.sbus.all()],
                "additional_comment": r.additional_comment,
                "referrer": {
                    "emp_id": r.referrer.emp_id,
                    "name": r.referrer.name,
                    "email": r.referrer.email
                },
                "review": review_data,
                "hr_evaluation": {
                    "stage": hr_eval.stage,
                    "status": hr_eval.status,
                    "comment": hr_eval.comment,
                    "updated_at": hr_eval.updated_at,
                    "updated_by": hr_eval.updated_by.name
                } if hr_eval else None,
                "considered_at": review.reviewed_at if review else None,
                "final_at": hr_eval.updated_at if hr_eval else None,
            })

        return Response(data)



class SubmitReviewView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, referral_id):
        decision = request.data.get("decision")
        comment = request.data.get("comment")
        emp_id = request.data.get("emp_id")

        if not all([decision, comment, emp_id]):
            return Response({"error": "decision, comment, and emp_id are required"}, status=400)

        try:
            referral = Referral.objects.get(id=referral_id)
        except Referral.DoesNotExist:
            return Response({"error": "Referral not found."}, status=404)

        try:
            reviewer = User.objects.get(emp_id=emp_id)
        except User.DoesNotExist:
            return Response({"error": "Reviewer not found."}, status=404)

        Review.objects.create(
            referral=referral,
            reviewer=reviewer,
            decision=decision,
            comment=comment,
        )

        if decision == "REJECTED":
            referral.current_status = "REJECTED"
            referral.rejection_stage = "SBU"
            referral.rejection_reason = comment

            recipientReferrer = referral.referrer.personal_email
            print("Recipient Referrer: ",recipientReferrer)

            # ✅ Email to Referrer
            send_dynamic_email(
                purpose="CV_REJECTED_SBU",
                to_emails=['abgang05@gmail.com'],
                context_data={
                    "candidate_name": referral.candidate_name,
                    "portal_link": f"{settings.PORTAL_BASE_URL}/",
                    "reason": comment
                }
            )

        elif decision == "CONSIDERED":
            referral.current_status = "CONSIDERED"

            recipientReferrer = referral.referrer.personal_email
            print("Recipient Referrer: ",recipientReferrer)

            # ✅ Email to Referrer
            send_dynamic_email(
                purpose="CV_APPROVED_SBU",
                to_emails=['abgang05@gmail.com'],
                context_data={
                    "candidate_name": referral.candidate_name,
                    "portal_link": f"{settings.FRONTEND_BASE_URL}/"
                }
            )

            # ✅ Notify HR
            hr_emails = list(User.objects.filter(is_hr=True).values_list('personal_email', flat=True))
            print("HR Personal Emails: ",hr_emails)
            send_dynamic_email(
                purpose="CV_TO_HR",
                to_emails=['abgang05@gmail.com'],
                context_data={
                    "candidate_name": referral.candidate_name,
                    "portal_link": f"{settings.FRONTEND_BASE_URL}/hr-evaluation"
                }
            )

        else:
            return Response({"error": "Invalid decision"}, status=400)

        referral.considered_at = timezone.now()
        referral.save()

        return Response({"message": "Review submitted."})


class UpdateReviewView(APIView):
    permission_classes = [AllowAny]

    def put(self, request, referral_id):
        emp_id = request.data.get("emp_id")
        decision = request.data.get("decision")
        comment = request.data.get("comment")

        if not emp_id or not decision:
            return Response({"error": "Missing required fields"}, status=400)

        try:
            reviewer = User.objects.get(emp_id=emp_id)
        except User.DoesNotExist:
            return Response({"error": "Reviewer not found"}, status=404)

        try:
            review = Review.objects.filter(
                referral__id=referral_id, reviewer=reviewer
            ).order_by('-reviewed_at').first()

            if not review:
                return Response({"error": "Review not found"}, status=404)

            previous_decision = review.decision
            referral = review.referral

            # Update review
            review.decision = decision
            review.comment = comment
            review.save()

            if decision == "REJECTED":
                referral.current_status = "REJECTED"
                referral.rejection_stage = "SBU"
                referral.rejection_reason = comment

                referrerMail = referral.referrer.personal_email
                print("Referrer Mail: ",referrerMail)

                # Notify Referrer
                send_dynamic_email(
                    purpose="CV_REJECTED_SBU",
                    to_emails=['abgang05@gmail.com'],
                    context_data={
                        "candidate_name": referral.candidate_name,
                        "portal_link": f"{settings.FRONTEND_BASE_URL}/",
                        "reason": comment
                    }
                )

                # ✅ Notify HRs if it was previously accepted
                if previous_decision == "CONSIDERED":
                    hr_emails = list(User.objects.filter(is_hr=True).values_list('personal_email', flat=True))
                    print("HR Personal Emails: ",hr_emails)
                    send_dynamic_email(
                        purpose="CV_REVOKED_BY_SBU",
                        to_emails=['abgang05@gmail.com'],
                        context_data={
                            "candidate_name": referral.candidate_name,
                            "portal_link": f"{settings.FRONTEND_BASE_URL}/hr-evaluation",
                        }
                    )

            elif decision == "CONSIDERED":
                referral.current_status = "CONSIDERED"
                referral.rejection_stage = None
                referral.rejection_reason = None

                referrerMail = referral.referrer.personal_email
                print("Referrer Mail: ",referrerMail)

                # Notify Referrer
                send_dynamic_email(
                    purpose="CV_APPROVED_SBU",
                    to_emails=['abgang05@gmail.com'],
                    context_data={
                        "candidate_name": referral.candidate_name,
                        "portal_link": f"{settings.FRONTEND_BASE_URL}/"
                    }
                )

                # Notify HR only if previously rejected
                if previous_decision == "REJECTED":
                    hr_emails = list(User.objects.filter(is_hr=True).values_list('personal_email', flat=True))
                    print("HR Personal Emails: ",hr_emails)
                    send_dynamic_email(
                        purpose="CV_TO_HR",
                        to_emails=['abgang05@gmail.com'],
                        context_data={
                            "candidate_name": referral.candidate_name,
                            "portal_link": f"{settings.FRONTEND_BASE_URL}/hr-evaluation"
                        }
                    )

            referral.save()
            return Response({"message": "Review and referral updated successfully."})

        except Exception as e:
            return Response({"error": str(e)}, status=500)
