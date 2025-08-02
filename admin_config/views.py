# admin_config/views.py

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from api.models import Department, SBU, EmailTemplate
from api.serializers import DepartmentSerializer, SBUSerializer, EmailTemplateSerializer
from django.db import transaction, connection
import json

# Fetch all departments
class DepartmentListView(APIView):
    def get(self, request):
        departments = Department.objects.all()
        serializer = DepartmentSerializer(departments, many=True)
        return Response(serializer.data)

# Add new department
class DepartmentCreateView(APIView):
    def post(self, request):
        serializer = DepartmentSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)

class DepartmentUpdateView(APIView):
    def put(self, request, department_id):
        try:
            department = Department.objects.get(id=department_id)
        except Department.DoesNotExist:
            return Response({"error": "Department not found"}, status=404)

        new_reviewers = request.data.get('reviewers', [])
        old_reviewers = department.reviewers or []
        department.reviewers = new_reviewers
        department.save()

        # Emails of new and old reviewers
        new_emails = {r['email'] for r in new_reviewers if 'email' in r}
        old_emails = {r['email'] for r in old_reviewers if 'email' in r}

        # ✅ Add/Update reviewers in SBU table
        for reviewer in new_reviewers:
            email = reviewer.get('email')
            name = reviewer.get('name')
            if not email:
                continue

            sbu, created = SBU.objects.get_or_create(
                email=email,
                defaults={
                    'name': name or email.split('@')[0],
                    'departments': [department.name]
                }
            )
            if not created and department.name not in sbu.departments:
                sbu.departments.append(department.name)
                sbu.save()

        # ✅ Remove department from SBUs no longer reviewing this department
        removed_emails = old_emails - new_emails
        for email in removed_emails:
            try:
                sbu = SBU.objects.get(email=email)
                if department.name in sbu.departments:
                    sbu.departments.remove(department.name)
                    sbu.save()
            except SBU.DoesNotExist:
                continue

        return Response({"message": "Reviewers and SBUs synced"}, status=status.HTTP_200_OK)

# # Update SBU departments
# class UpdateSBUDepartmentsView(APIView):
#     def post(self, request):
#         email = request.data.get('reviewer_email')
#         department_name = request.data.get('department_name')

#         if not email or not department_name:
#             return Response({'error': 'Missing data'}, status=status.HTTP_400_BAD_REQUEST)

#         sbu, created = SBU.objects.get_or_create(
#             email=email,
#             defaults={
#                 'name': email.split('@')[0],
#                 'departments': [department_name]
#             }
#         )

#         if not created and department_name not in sbu.departments:
#             sbu.departments.append(department_name)
#             sbu.save()

#         return Response({'message': 'SBU updated'}, status=status.HTTP_200_OK)


# SBU Reviewer management
class SBUListCreateView(APIView):
    def get(self, request):
        sbus = SBU.objects.all()
        serializer = SBUSerializer(sbus, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = SBUSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)

class SBUDetailView(APIView):
    def put(self, request, email):
        try:
            sbu = SBU.objects.filter(email__iexact=email).first()
            if not sbu:
                return Response({"error": "SBU not found"}, status=404)
        except Exception:
            return Response({"error": "Error fetching SBU"}, status=500)

        new_email = request.data.get("email", sbu.email)
        new_name = request.data.get("name", sbu.name)
        incoming_departments = request.data.get("departments", None)
        replace_flag = request.data.get("replace_departments", False)

        # If email is being changed (case-insensitive), ensure no other record has it
        if new_email.lower() != sbu.email.lower():
            if SBU.objects.filter(email__iexact=new_email).exclude(pk=sbu.pk).exists():
                return Response({"error": "Email already exists."}, status=400)

        try:
            with transaction.atomic():
                # Update email via raw SQL if only case differs (to avoid unique conflict issues on some DBs)
                if new_email != sbu.email:
                    # Direct SQL to safely rename without creating duplicate entry race
                    with connection.cursor() as cursor:
                        cursor.execute("""
                            UPDATE api_sbu SET email = %s WHERE id = %s
                        """, [new_email, str(sbu.id)])
                    # re-fetch to reflect change
                    sbu = SBU.objects.get(pk=sbu.pk)

                # Update name
                sbu.name = new_name

                # Merge departments unless replace flag
                if incoming_departments is not None:
                    if replace_flag:
                        sbu.departments = incoming_departments
                    else:
                        existing = sbu.departments or []
                        # ensure both are lists
                        if not isinstance(existing, list):
                            try:
                                existing = json.loads(existing)
                            except:
                                existing = []
                        merged = list(dict.fromkeys([*existing, *incoming_departments]))
                        sbu.departments = merged

                # Save remaining fields
                sbu.save()

            return Response({"message": "SBU updated"}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=500)

    def delete(self, request, email):
        department_id = request.query_params.get('department_id')
        if not department_id:
            return Response({"error": "Department ID required"}, status=400)

        try:
            sbu = SBU.objects.get(email=email)
            department = Department.objects.get(id=department_id)
        except (SBU.DoesNotExist, Department.DoesNotExist):
            return Response({"error": "SBU or Department not found"}, status=404)

        # ✅ Remove reviewer from Department
        updated_reviewers = [r for r in department.reviewers if r.get('email') != email]
        department.reviewers = updated_reviewers
        department.save()

        # ✅ Remove department name from SBU.departments
        sbu.departments = [d for d in sbu.departments if d != department.name]
        if sbu.departments:
            sbu.save()
        else:
            sbu.delete()  # Optionally delete SBU if no departments left

        return Response({"message": "Reviewer removed from department and SBU updated"})

class EmailTemplateListView(APIView):
    def get(self, request):
        templates = EmailTemplate.objects.all()
        serializer = EmailTemplateSerializer(templates, many=True)
        return Response(serializer.data)

class EmailTemplateDetailView(APIView):
    def get(self, request, purpose):
        try:
            template = EmailTemplate.objects.get(purpose=purpose)
        except EmailTemplate.DoesNotExist:
            return Response({"error": "Template not found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = EmailTemplateSerializer(template)
        return Response(serializer.data)

    def put(self, request, purpose):
        try:
            template = EmailTemplate.objects.get(purpose=purpose)
        except EmailTemplate.DoesNotExist:
            return Response({"error": "Template not found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = EmailTemplateSerializer(template, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class SBUListView(APIView):
    def get(self, request):
        sbus = SBU.objects.all().values('id', 'name', 'email')  # minimal info
        return Response(list(sbus), status=status.HTTP_200_OK)

