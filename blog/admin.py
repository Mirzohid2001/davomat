from django.contrib import admin
from import_export.admin import ImportExportModelAdmin

from .models import (
    Employee,
    Attendance,
    DayOff,
    AttendanceImportLog,
    Team,
    MonthlyEmployeeStat,
)


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("code", "name")
    search_fields = ("name",)
    ordering = ("code",)


@admin.register(Employee)
class EmployeeAdmin(ImportExportModelAdmin):
    list_display = (
        "last_name",
        "first_name",
        "position",
        "department",
        "location",
        "phone_number",
        "is_active",
        "role",
        "team",
    )
    search_fields = ("first_name", "last_name", "position", "department", "phone_number")
    list_filter = ("is_active", "department", "position", "location", "role", "team")


@admin.register(Attendance)
class AttendanceAdmin(ImportExportModelAdmin):
    list_display = ("date", "employee", "status", "comment")
    list_filter = ("date", "status", "employee__department")
    search_fields = ("employee__first_name", "employee__last_name", "comment")
    autocomplete_fields = ["employee"]


@admin.register(DayOff)
class DayOffAdmin(admin.ModelAdmin):
    list_display = ("date", "reason")


@admin.register(AttendanceImportLog)
class AttendanceImportLogAdmin(admin.ModelAdmin):
    list_display = ("file_name", "imported_at", "record_count", "success")
    readonly_fields = ("imported_at",)


@admin.register(MonthlyEmployeeStat)
class MonthlyEmployeeStatAdmin(ImportExportModelAdmin):
    list_display = (
        "employee",
        "year",
        "month",
        "salary",
        "bonus",
        "accrued",
        "paid",
        "debt_start",
        "debt_end",
        "currency",
    )
    list_filter = ("year", "month", "currency", "employee__department", "employee__employee_type")
    search_fields = ("employee__first_name", "employee__last_name")

# Add admin for EmployeeType
