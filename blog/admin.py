from django.contrib import admin
from .models import Employee, Attendance, DayOff, AttendanceImportLog
from import_export.admin import ImportExportModelAdmin

@admin.register(Employee)
class EmployeeAdmin(ImportExportModelAdmin):
    list_display = ('last_name', 'first_name', 'position', 'department', 'location', 'phone_number', 'is_active')
    search_fields = ('first_name', 'last_name', 'position', 'department', 'phone_number')
    list_filter = ('is_active', 'department', 'position', 'location')

@admin.register(Attendance)
class AttendanceAdmin(ImportExportModelAdmin):
    list_display = ('date', 'employee', 'status', 'comment')
    list_filter = ('date', 'status', 'employee__department')
    search_fields = ('employee__first_name', 'employee__last_name', 'comment')
    autocomplete_fields = ['employee']

@admin.register(DayOff)
class DayOffAdmin(admin.ModelAdmin):
    list_display = ('date', 'reason')

@admin.register(AttendanceImportLog)
class AttendanceImportLogAdmin(admin.ModelAdmin):
    list_display = ('file_name', 'imported_at', 'record_count', 'success')
    readonly_fields = ('imported_at',)
