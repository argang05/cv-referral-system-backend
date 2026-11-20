from rest_framework import serializers
from api.models import User, JobRotationNomination

class IJREmployeeSerializer(serializers.ModelSerializer):
    label = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('emp_id', 'name', 'email', 'designation', 'band', 'sub_bu', 'label')

    def get_label(self, obj):
        return f'{obj.name} ({obj.emp_id}) — {obj.designation or "No Designation"}'

class IJREmployeeDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('emp_id', 'name', 'email', 'designation', 'band', 'sub_bu', 'reporting_manager_emp_id', 'reporting_manager_name')

class IJRManagerSerializer(serializers.ModelSerializer):
    label = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('emp_id', 'name', 'email', 'designation', 'sub_bu', 'label')

    def get_label(self, obj):
        return f'{obj.name} ({obj.emp_id}) — {obj.designation or "No Designation"}'

class IJRNominationCreateSerializer(serializers.Serializer):
    employee_emp_id = serializers.CharField(max_length=20)
    proposed_sub_bu = serializers.CharField(max_length=100)
    proposed_reporting_manager_emp_id = serializers.CharField(max_length=20, required=False, allow_blank=True)
    proposed_designation = serializers.CharField(max_length=100, required=False, allow_blank=True)
    proposed_band = serializers.CharField(max_length=10, required=False, allow_blank=True)
    reason = serializers.CharField()
    remarks = serializers.CharField(required=False, allow_blank=True, default='')
    effective_date = serializers.DateField(required=False, allow_null=True)

    def validate(self, attrs):
        employee = User.objects.filter(emp_id=attrs['employee_emp_id'], is_active=True).first()
        if not employee:
            raise serializers.ValidationError({'employee_emp_id': 'Active employee not found.'})

        proposed_sbu = attrs['proposed_sub_bu'].strip()
        current_sbu = (employee.sub_bu or '').strip()
        sbu_changed = proposed_sbu.casefold() != current_sbu.casefold()

        if not User.objects.filter(is_active=True, sub_bu__iexact=proposed_sbu).exists():
            raise serializers.ValidationError({'proposed_sub_bu': 'Selected SBU does not exist among active employees.'})

        proposed_manager_id = attrs.get('proposed_reporting_manager_emp_id', '').strip()
        current_manager_id = employee.reporting_manager_emp_id or (employee.manager.emp_id if employee.manager_id else '')

        if sbu_changed and not proposed_manager_id:
            raise serializers.ValidationError({'proposed_reporting_manager_emp_id': 'Changing SBU requires selecting a new reporting manager.'})

        if not proposed_manager_id:
            proposed_manager_id = current_manager_id

        manager = None
        if proposed_manager_id:
            manager = User.objects.filter(emp_id=proposed_manager_id, is_active=True).first()
            if not manager:
                raise serializers.ValidationError({'proposed_reporting_manager_emp_id': 'Selected reporting manager is inactive or does not exist.'})
            if manager.emp_id == employee.emp_id:
                raise serializers.ValidationError({'proposed_reporting_manager_emp_id': 'An employee cannot report to themselves.'})
            if (manager.sub_bu or '').strip().casefold() != proposed_sbu.casefold():
                raise serializers.ValidationError({'proposed_reporting_manager_emp_id': 'Reporting manager must belong to the proposed SBU.'})
            if sbu_changed and manager.emp_id == current_manager_id:
                raise serializers.ValidationError({'proposed_reporting_manager_emp_id': 'A new reporting manager must be selected when changing SBU.'})

        if JobRotationNomination.objects.filter(employee=employee, status__in=['PENDING', 'APPROVED']).exists():
            raise serializers.ValidationError({'employee_emp_id': 'This employee already has an active IJR nomination.'})

        attrs['employee'] = employee
        attrs['manager'] = manager
        attrs['proposed_sub_bu'] = proposed_sbu
        return attrs

class IJRNominationSerializer(serializers.ModelSerializer):
    employee_emp_id = serializers.CharField(source='employee.emp_id', read_only=True)
    employee_name = serializers.CharField(source='employee.name', read_only=True)
    nominated_by_emp_id = serializers.CharField(source='nominated_by.emp_id', read_only=True)
    nominated_by_name = serializers.CharField(source='nominated_by.name', read_only=True)

    class Meta:
        model = JobRotationNomination
        fields = ('id', 'employee_emp_id', 'employee_name', 'nominated_by_emp_id', 'nominated_by_name', 'current_details', 'proposed_details', 'reason', 'remarks', 'effective_date', 'status', 'created_at', 'updated_at')