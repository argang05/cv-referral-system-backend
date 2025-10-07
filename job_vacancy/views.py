from django.shortcuts import render

# Create your views here.
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from api.models import JobVacancy, JobApplication
from .serializers import JobVacancySerializer, JobApplicationSerializer
from django.shortcuts import get_object_or_404
from api.utils import upload_to_supabase
import re

def sanitize_filename(filename: str) -> str:
    """
    Make a filename URL-safe:
    - Replace spaces with underscores
    - Remove any special characters except dash, underscore, dot
    """
    filename = filename.replace(" ", "_")  # spaces → underscores
    filename = re.sub(r"[^A-Za-z0-9_\-\.]", "", filename)
    return filename

# ✅ CREATE + LIST Job Vacancies
class JobVacancyListCreateView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        jobs = JobVacancy.objects.all().order_by('-created_at')
        serializer = JobVacancySerializer(jobs, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = JobVacancySerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ✅ RETRIEVE Job Vacancy by job_id
class JobVacancyDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, job_id):
        try:
            job = JobVacancy.objects.get(job_id=job_id)
            serializer = JobVacancySerializer(job)
            return Response(serializer.data)
        except JobVacancy.DoesNotExist:
            return Response({"error": "Job not found"}, status=status.HTTP_404_NOT_FOUND)


# ✅ UPDATE Job Vacancy by job_id
class JobVacancyUpdateView(APIView):
    permission_classes = [AllowAny]

    def put(self, request, job_id):
        try:
            job = JobVacancy.objects.get(job_id=job_id)
        except JobVacancy.DoesNotExist:
            return Response({"error": "Job not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = JobVacancySerializer(job, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "Job updated successfully", "job": serializer.data})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ✅ DELETE Job Vacancy by job_id
class JobVacancyDeleteView(APIView):
    permission_classes = [AllowAny]

    def delete(self, request, job_id):
        try:
            job = JobVacancy.objects.get(job_id=job_id)
            job.delete()
            return Response({"message": "Job deleted successfully"})
        except JobVacancy.DoesNotExist:
            return Response({"error": "Job not found"}, status=status.HTTP_404_NOT_FOUND)


# ✅ CREATE Application for a Job
class JobApplicationCreateView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, job_id):
        try:
            job = JobVacancy.objects.get(job_id=job_id)
        except JobVacancy.DoesNotExist:
            return Response({"error": "Job not found"}, status=status.HTTP_404_NOT_FOUND)

        # ✅ Copy data and remove 'job' if sent
        data = request.data.copy()
        data.pop("job", None)  # Avoid duplicate validation issues

        serializer = JobApplicationSerializer(data=data)
        if serializer.is_valid():
            serializer.save(job=job)  # ✅ set FK manually
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ✅ LIST Applicants for a specific Job
class JobApplicantListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, job_id):
        try:
            job = JobVacancy.objects.get(job_id=job_id)
        except JobVacancy.DoesNotExist:
            return Response({"error": "Job not found"}, status=status.HTTP_404_NOT_FOUND)

        applicants = JobApplication.objects.filter(job=job)
        serializer = JobApplicationSerializer(applicants, many=True)
        return Response(serializer.data)


# ✅ UPDATE Application by applicant_id
class JobApplicationUpdateView(APIView):
    permission_classes = [AllowAny]

    def put(self, request, applicant_id):
        try:
            application = JobApplication.objects.get(applicant_id=applicant_id)
        except JobApplication.DoesNotExist:
            return Response({"error": "Application not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = JobApplicationSerializer(application, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "Application updated successfully", "application": serializer.data})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ✅ DELETE Application by applicant_id
class JobApplicationDeleteView(APIView):
    permission_classes = [AllowAny]

    def delete(self, request, applicant_id):
        try:
            application = JobApplication.objects.get(applicant_id=applicant_id)
            application.delete()
            return Response({"message": "Application deleted successfully"})
        except JobApplication.DoesNotExist:
            return Response({"error": "Application not found"}, status=status.HTTP_404_NOT_FOUND)

class UploadJobDescriptionView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            file_obj = request.FILES.get("file")
            if not file_obj:
                return Response({"error": "No file provided."}, status=status.HTTP_400_BAD_REQUEST)

            file_name = f"job_descriptions/{sanitize_filename(file_obj.name)}"
            uploaded_url = upload_to_supabase(file_obj, file_name)

            return Response(
                {"message": "File uploaded successfully", "file_url": uploaded_url},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class UploadApplicantCVView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            file_obj = request.FILES.get("file")
            applicant_name = request.data.get("name")
            original_file_name = file_obj.name
            if not file_obj or not applicant_name:
                return Response({"error": "File and applicant name are required."}, status=status.HTTP_400_BAD_REQUEST)

            file_name = f"applicant_cvs/{sanitize_filename(applicant_name)}_{original_file_name}"
            uploaded_url = upload_to_supabase(file_obj, file_name)

            return Response(
                {"message": "CV uploaded successfully", "cv_url": uploaded_url},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)