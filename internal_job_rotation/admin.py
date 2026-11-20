from django.contrib import admin
from api.models import JobRotationNomination

@admin.register(JobRotationNomination)
class JobRotationNominationAdmin(admin.ModelAdmin):
    list_display = ('id', 'employee', 'nominated_by', 'status', 'effective_date', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('employee__emp_id', 'employee__name', 'nominated_by__emp_id', 'nominated_by__name')
    readonly_fields = ('id', 'created_at', 'updated_at')
    ordering = ('-created_at',)