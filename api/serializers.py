# api/serializers.py
from rest_framework import serializers
from .models import User, Department, SBU, EmailTemplate
from django.contrib.auth.hashers import check_password, make_password

class UserRegisterSerializer(serializers.ModelSerializer):
    department = serializers.ListField(child=serializers.CharField(), default=list)
    class Meta:
        model = User
        fields = ['emp_id', 'name', 'email', 'password_og', 'role']

    def create(self, validated_data):
        validated_data['password_hash'] = make_password(validated_data['password_og'])
        return User.objects.create(**validated_data)

class UserLoginSerializer(serializers.Serializer):
    emp_id = serializers.CharField()
    password = serializers.CharField()

class UserResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'emp_id', 'name', 'email', 'personal_email', 'role', 'is_hr', 'department']

class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ['id', 'name', 'reviewers']

class SBUSerializer(serializers.ModelSerializer):
    class Meta:
        model = SBU
        fields = ['id', 'name', 'email', 'departments']

class EmailTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailTemplate
        fields = ['purpose', 'subject', 'html_body']

