from rest_framework import serializers
from api.models import HREvaluation, User
from api.serializers import UserResponseSerializer

class HREvaluationSerializer(serializers.ModelSerializer):
    updated_by = UserResponseSerializer(read_only=True)
    updated_by_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        source='updated_by',
        write_only=True
    )

    class Meta:
        model = HREvaluation
        fields = [
            'id',
            'referral',
            'stage',
            'status',
            'comment',
            'updated_by',
            'updated_by_id',
            'updated_at',
        ]
        read_only_fields = ['id', 'updated_at', 'updated_by']
