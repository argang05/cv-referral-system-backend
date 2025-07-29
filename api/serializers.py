# api/serializers.py
from rest_framework import serializers
from .models import User
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
        fields = ['id','emp_id', 'name', 'email', 'role', 'is_hr']
