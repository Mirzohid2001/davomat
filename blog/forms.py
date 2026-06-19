from django import forms
from .models import Attendance, Employee, DayOff, NalivshikShiftOverride, Team
import datetime
import os
from .models import MonthlyEmployeeStat

class BulkAttendanceForm(forms.Form):
    date = forms.DateField(initial=datetime.date.today)
    default_status = forms.ChoiceField(choices=Attendance.STATUS_CHOICES, required=False)

class AttendanceForm(forms.ModelForm):
    class Meta:
        model = Attendance
        fields = ['employee', 'date', 'status', 'comment']
        widgets = {
            'status': forms.Select(attrs={'class': 'form-select'}),
            'comment': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'employee': forms.Select(attrs={'class': 'form-select'})
        }

    def __init__(self, *args, **kwargs):
        self.attendance_employee = kwargs.pop('attendance_employee', None)
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        att_date = cleaned_data.get('date')
        employee = cleaned_data.get('employee') or self.attendance_employee
        status = cleaned_data.get('status')

        if att_date and employee:
            from .services import employee_can_attend_on_date, get_restricted_day_reason
            if not employee_can_attend_on_date(employee, att_date):
                reason = get_restricted_day_reason(att_date)
                raise forms.ValidationError(
                    f"{att_date.strftime('%d.%m.%Y')} — {reason}. "
                    "Bu kunda faqat nalivshiklar davomat kiritishi mumkin."
                )
        elif att_date and DayOff.objects.filter(date=att_date).exists() and status != 'offday':
            raise forms.ValidationError("Bu sana yopiq kun. Faqat 'Ish kuni emas' holatini tanlang!")

        if status in ['absent', 'sick', 'vacation']:
            if not cleaned_data.get('comment'):
                raise forms.ValidationError("Sabab yoki izoh kiritilishi shart!")
        return cleaned_data

class AttendanceImportForm(forms.Form):
    file = forms.FileField(label="Excel yoki CSV fayl")

    def clean_file(self):
        file = self.cleaned_data['file']
        allowed_types = ['.csv', '.xls', '.xlsx']
        max_size = 5 * 1024 * 1024  # 5 MB
        ext = os.path.splitext(file.name)[-1].lower()
        if ext not in allowed_types:
            raise forms.ValidationError("Faqat .csv, .xls yoki .xlsx fayllar yuklash mumkin!")
        if file.size > max_size:
            raise forms.ValidationError("Fayl hajmi 5MB dan oshmasligi kerak!")
        return file

class DayOffForm(forms.ModelForm):
    class Meta:
        model = DayOff
        fields = ['date', 'reason']

class EmployeeForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = [
            'first_name',
            'last_name',
            'position',
            'department',
            'location',
            'phone_number',
            'hire_date',
            'is_active',
            'employee_type',
            'role',
            'team',
        ]
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'position': forms.TextInput(attrs={'class': 'form-control'}),
            'department': forms.TextInput(attrs={'class': 'form-control'}),
            'location': forms.Select(attrs={'class': 'form-select'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control'}),
            'hire_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'employee_type': forms.Select(attrs={'class': 'form-select'}),
            'role': forms.Select(attrs={'class': 'form-select'}),
            'team': forms.Select(attrs={'class': 'form-select'}),
        }


class EmployeeCreateForm(EmployeeForm):
    """Faqat yangi xodim qo'shishda: ishga kirish sanasi va kelgan kunlar."""

    worked_days_count = forms.IntegerField(
        label="Kelgan kunlar soni (shu oydan)",
        required=True,
        min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
        help_text="Ishga kirgan sanadan boshlab shu oyda necha kun kelganini kiriting.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['hire_date'].required = True
        if not self.instance.pk:
            self.fields['hire_date'].initial = datetime.date.today

    def clean(self):
        cleaned_data = super().clean()
        hire_date = cleaned_data.get("hire_date")
        worked_days_count = cleaned_data.get("worked_days_count")
        if hire_date is None or worked_days_count is None:
            return cleaned_data

        from calendar import monthrange

        days_left = monthrange(hire_date.year, hire_date.month)[1] - hire_date.day + 1
        if worked_days_count > days_left:
            raise forms.ValidationError(
                f"Kelgan kunlar soni shu oyda maksimal {days_left} bo'lishi mumkin "
                f"(ishga kirgan sanadan oy oxirigacha)."
            )
        return cleaned_data


class NalivshikShiftOverrideForm(forms.ModelForm):
    class Meta:
        model = NalivshikShiftOverride
        fields = ["date", "day_team", "night_team", "comment"]
        widgets = {
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "day_team": forms.Select(attrs={"class": "form-select"}),
            "night_team": forms.Select(attrs={"class": "form-select"}),
            "comment": forms.TextInput(attrs={"class": "form-control"}),
        }

class SalaryStatEditForm(forms.ModelForm):
    class Meta:
        model = MonthlyEmployeeStat
        fields = ['salary', 'currency', 'paid', 'paid_at', 'bonus', 'penalty']
        widgets = {
            'salary': forms.NumberInput(attrs={'class': 'form-control', 'step': 'any'}),
            'currency': forms.Select(attrs={'class': 'form-select'}),
            'paid': forms.NumberInput(attrs={'class': 'form-control', 'step': 'any'}),
            'paid_at': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'bonus': forms.NumberInput(attrs={'class': 'form-control', 'step': 'any'}),
            'penalty': forms.NumberInput(attrs={'class': 'form-control', 'step': 'any', 'min': '0'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        from decimal import Decimal

        paid = Decimal(str(cleaned_data.get('paid') or 0))
        paid_at = cleaned_data.get('paid_at')
        if paid > 0 and not paid_at:
            raise forms.ValidationError(
                "To'lov summasi kiritilsa, to'lov sanasini ham kiriting."
            )
        if paid <= 0:
            cleaned_data['paid_at'] = None
        return cleaned_data