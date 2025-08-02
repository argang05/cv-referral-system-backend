from django.shortcuts import render
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.views import APIView
from .utils import upload_to_supabase, get_role_and_departments
from rest_framework import status
from .models import User
from .serializers import UserRegisterSerializer, UserLoginSerializer, UserResponseSerializer
from django.contrib.auth.hashers import check_password
from django.contrib.auth.hashers import make_password
import secrets
import os
from rest_framework_simplejwt.tokens import RefreshToken
from django.http import JsonResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.utils.timezone import now
from datetime import timedelta
from django.utils import timezone
from api.models import Department
from rest_framework.parsers import MultiPartParser, FormParser
import re

# Mapping logic from SBU-email table (can move this to DB later)
REVIEWER_SBU_MAPPING = {
    "Software Development": [
        "aditya.kelkar@tor.ai",
        "jatin.bhole@tor.ai",
        "shweta.kulkarni@tor.ai"
    ],
    "Hardware Development": [
        "aditya.kelkar@tor.ai",
        "milind.vaze@tor.ai",
        "shweta.kulkarni@tor.ai"
    ],
    "Firmware Development": [
        "aditya.kelkar@tor.ai",
        "hrishikesh.limaye@tor.ai",
        "shweta.kulkarni@tor.ai"
    ],
    "Finance & Legal": [
        "aditya.paranjpe@tor.ai",
        "priyanka.agarwal@tor.ai",
        "shweta.kulkarni@tor.ai"
    ],
    "Support-IOT": [
        "swati.chavare@tor.ai",
        "makarand.jadhav@tor.ai",
        "shweta.kulkarni@tor.ai"
    ],
    "Strategic Partnership and SEA": [
        "rajesh.kulkarni@tor.ai",
        "omkar.pant@tor.ai",
        "shweta.kulkarni@tor.ai"
    ],
    "Quality Assurance": [
        "aditya.kelkar@tor.ai",
        "milind.vaze@tor.ai",
        "ravindra.barbade@tor.ai",
        "shweta.kulkarni@tor.ai"
    ],
    "Production": [
        "swati.chavare@tor.ai",
        "nilesh.mungase@tor.ai",
        "shweta.kulkarni@tor.ai"
    ],
    "Implementation": [
        "swati.chavare@tor.ai",
        "makarand.jadhav@tor.ai",
        "shweta.kulkarni@tor.ai"
    ],
    "Supply Chain Management": [
        "swati.chavare@tor.ai",
        "siddhi.phatak@tor.ai",
        "shweta.kulkarni@tor.ai"
    ],
    "Business Development": [
        "rajesh.kulkarni@tor.ai",
        "ashish.bharadwaj@tor.ai",
        "ganesh.kamble@tor.ai",
        "shweta.kulkarni@tor.ai"
    ],
    "Product Management": [
        "aditya.paranjpe@tor.ai",
        "rohit.pandita@tor.ai",
        "shweta.kulkarni@tor.ai"
    ],
    "Marketing": [
        "rajesh.kulkarni@tor.ai",
        "ashish.bharadwaj@tor.ai",
        "ganesh.kamble@tor.ai",
        "shweta.kulkarni@tor.ai"
    ],
    "Sales": [
        "rajesh.kulkarni@tor.ai",
        "vaibhav.dhole@tor.ai",
        "shweta.kulkarni@tor.ai"
    ],
    "Human Resource Management": [
        "aditya.paranjpe@tor.ai",
        "abhishek.ganguly@tor.ai",
        "shweta.kulkarni@tor.ai"
    ],
    "Systems Management": [
        "aditya.kelkar@tor.ai",
        "jatin.bhole@tor.ai",
        "shweta.kulkarni@tor.ai"
    ]
}



# Create your views here.
class HelloWorldView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({'message': 'Hello from Django!'})


class UploadCVView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        file = request.FILES.get('cv')

        if not file:
            return Response({"error": "No file provided"}, status=400)

        try:
            timestamp = now().strftime('%Y%m%d%H%M%S')
            file_name = f"cvs/{timestamp}_{file.name}"

            public_url = upload_to_supabase(file, file_name)

            return Response({"url": public_url})
        except Exception as e:
            return Response({"error": str(e)}, status=500)

class RegisterView(APIView):
    def post(self, request):
        data = request.data
        emp_id = data.get("emp_id")
        email = data.get("email", "").lower()
        name = data.get("name")
        password = data.get("password") or data.get("password_og")

        if not password:
            return Response({"error": "Password cannot be empty."}, status=400)

        role = "EMPLOYEE"
        departments = []

        for dept, reviewers in REVIEWER_SBU_MAPPING.items():
            if email in [r.lower() for r in reviewers]:
                departments.append(dept)
                role = "REVIEWER"
                if "human resource" in dept.lower():
                    role = "HR"

        user = User.objects.create(
            emp_id=emp_id,
            name=name,
            email=email,
            password_og=password,
            password_hash=make_password(password),
            role=role,
            department=departments
        )
        return Response({
            "message": "User registered",
            "role": role,
            "departments": departments
        })

class BulkUserRegisterView(APIView):
    def post(self, request):
        users_data = request.data.get("users", [])

        created = []
        failed = []

        for user in users_data:
            try:
                emp_id = user["emp_id"]
                name = user["name"]
                email = user["email"]
                password_og = user["password"]
                password_hash = make_password(password_og)

                role, department, is_hr = get_role_and_departments(email)

                if User.objects.filter(emp_id=emp_id).exists():
                    failed.append({"email": email, "error": f"emp_id {emp_id} already exists"})
                    continue

                User.objects.create(
                    emp_id=emp_id,
                    name=name,
                    email=email,
                    password_og=password_og,
                    password_hash=password_hash,
                    role=role,
                    department=department,
                    is_active=True,
                    is_hr=is_hr
                )
                created.append(email)
            except Exception as e:
                failed.append({"email": user.get("email"), "error": str(e)})

        return Response({"created": created, "failed": failed}, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    def set_jwt_cookie(self, response, token):
        max_age = 60 * 60 * 24 * 7  # 7 days
        secure_cookie = not os.environ.get("DEBUG", "true").lower() in ["1", "true"]

        response.set_cookie(
            key='access_token',
            value=token,
            httponly=True,
            secure=secure_cookie,    # 🔐 Set to False only for local dev
            samesite='None',         # 🔄 Required for cross-origin cookies
            max_age=max_age,
        )
        return response

    def post(self, request):
        serializer = UserLoginSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        emp_id = serializer.validated_data['emp_id']
        password = serializer.validated_data['password']

        try:
            user = User.objects.get(emp_id=emp_id)
        except User.DoesNotExist:
            return Response({"error": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)

        if not check_password(password, user.password_hash):
            return Response({"error": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)

        if not user.is_active:
            return Response({"error": "Account is inactive"}, status=status.HTTP_403_FORBIDDEN)

        # ✅ Generate tokens
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)

        # ✅ Serialize user
        user_data = UserResponseSerializer(user).data

        # ✅ Send access token in cookie
        response = Response(user_data)
        self.set_jwt_cookie(response, access_token)
        return response

class ProtectedDashboard(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"message": "Welcome to the protected dashboard!"})

class LogoutView(APIView):
    def post(self, request):
        response = JsonResponse({"message": "Logged out"})
        response.delete_cookie('access_token')
        response.delete_cookie('refresh_token')
        return response

class CookieJWTAuthentication(JWTAuthentication):
    def get_raw_token(self, header):
        # First try normal Authorization header
        raw_token = super().get_raw_token(header)
        if raw_token:
            return raw_token

        # Fallback to cookie named "access_token"
        request = self.request
        cookie_token = request.COOKIES.get("access_token")
        if cookie_token:
            return cookie_token

        return None

class MeView(APIView):
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserResponseSerializer(request.user)
        return Response(serializer.data)

class DepartmentListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        departments = Department.objects.all()
        data = [
            {
                "id": str(dept.id),
                "name": dept.name,
                "reviewers": dept.reviewers,
            }
            for dept in departments
        ]
        return Response(data, status=status.HTTP_200_OK)

class UpdateUserProfile(APIView):
    permission_classes = [AllowAny]

    def put(self, request):
        data = request.data
        emp_id = data.get("emp_id")

        try:
            user = User.objects.get(emp_id=emp_id)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=404)

        # Update name and email
        user.name = data.get("name", user.name)
        user.email = data.get("email", user.email)

        # Only update password if changed
        new_password = data.get("password")
        if new_password:
            user.password_og = new_password
            user.password_hash = make_password(new_password)

        user.save()

        return Response({
            "message": "Profile updated successfully.",
            "user": {
                "emp_id": user.emp_id,
                "name": user.name,
                "email": user.email,
                "role": user.role,
                "is_hr": user.is_hr
            }
        })

class GetUserByEmpIDView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        emp_id = request.query_params.get("emp_id")
        if not emp_id:
            return Response({"error": "emp_id is required"}, status=400)

        try:
            user = User.objects.get(emp_id=emp_id)
            return Response(UserResponseSerializer(user).data)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=404)