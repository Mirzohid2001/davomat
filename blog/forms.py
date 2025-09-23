from django import forms
from .models import Attendance, Employee, DayOff
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

    def clean(self):
        cleaned_data = super().clean()
        if DayOff.objects.filter(date=cleaned_data.get('date')).exists() and cleaned_data.get('status') != 'offday':
            raise forms.ValidationError("Bu sana yopiq kun. Faqat 'Ish kuni emas' holatini tanlang!")
        if cleaned_data.get('status') in ['absent', 'sick', 'vacation']:
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
        fields = ['first_name', 'last_name', 'position', 'department', 'location', 'phone_number', 'is_active', 'employee_type']

class SalaryStatEditForm(forms.ModelForm):
    class Meta:
        model = MonthlyEmployeeStat
        fields = ['salary', 'currency', 'paid', 'bonus']
        widgets = {
            'salary': forms.NumberInput(attrs={'class': 'form-control', 'step': 'any'}),
            'currency': forms.Select(attrs={'class': 'form-select'}),
            'paid': forms.NumberInput(attrs={'class': 'form-control', 'step': 'any'}),
            'bonus': forms.NumberInput(attrs={'class': 'form-control', 'step': 'any'}),
        }