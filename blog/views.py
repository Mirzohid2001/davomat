from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib import messages
from django.db.models import Q, Count, F
from django.utils import timezone
from datetime import timedelta, date
from .models import Employee, Attendance, DayOff, AttendanceImportLog, MonthlyEmployeeStat
from .forms import EmployeeForm, AttendanceForm, BulkAttendanceForm, AttendanceImportForm, DayOffForm
from django.forms import modelformset_factory
from django.db import transaction

import pandas as pd
import openpyxl
from django.http import HttpResponse
from .services import calculate_monthly_stats
from openpyxl.utils import get_column_letter

from django import forms
from decimal import Decimal
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side, NamedStyle
from openpyxl.worksheet.dimensions import ColumnDimension
from openpyxl.comments import Comment
from openpyxl.formatting.rule import CellIsRule

class SalaryStatFilterForm(forms.Form):
    year = forms.IntegerField(label="Yil", min_value=2000, max_value=2100)
    month = forms.IntegerField(label="Oy", min_value=1, max_value=12)

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

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, "Muvaffaqiyatli tizimga kirdingiz!")
            return redirect('dashboard')
        else:
            messages.error(request, "Login yoki parol noto'g'ri!")
    else:
        form = AuthenticationForm()
    return render(request, 'attendance/login.html', {'form': form})

def logout_view(request):
    logout(request)
    messages.success(request, "Tizimdan chiqdingiz.")
    return redirect('login')

@login_required
def dashboard(request):
    today = date.today()
    employees = Employee.objects.filter(is_active=True)
    attendance_today = Attendance.objects.filter(date=today)
    not_filled = employees.exclude(id__in=attendance_today.values_list('employee', flat=True))
    stats = Attendance.objects.values('status').annotate(count=Count('id'))
    best_employees = Attendance.objects.filter(
        status='present',
        date__gte=today - timedelta(days=30)
    ).values('employee__last_name', 'employee__first_name').annotate(
        present_count=Count('id')
    ).order_by('-present_count')[:5]
    return render(request, 'attendance/dashboard.html', {
        'today': today,
        'employees': employees,
        'attendance_today': attendance_today,
        'not_filled': not_filled,
        'stats': stats,
        'best_employees': best_employees,
    })

@login_required
def employee_list(request):
    search = request.GET.get('q', '')
    employees = Employee.objects.all()
    if search:
        employees = employees.filter(
            Q(first_name__icontains=search) | 
            Q(last_name__icontains=search) | 
            Q(position__icontains=search) | 
            Q(department__icontains=search) | 
            Q(phone_number__icontains=search)
        )
    return render(request, 'attendance/employees.html', {'employees': employees, 'search': search})

@login_required
def employee_create(request):
    if request.method == 'POST':
        form = EmployeeForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Xodim muvaffaqiyatli qo'shildi!")
            return redirect('employee_list')
    else:
        form = EmployeeForm()
    return render(request, 'attendance/employee_form.html', {'form': form})

@login_required
def employee_update(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    if request.method == 'POST':
        form = EmployeeForm(request.POST, instance=employee)
        if form.is_valid():
            form.save()
            messages.success(request, "Xodim ma'lumoti yangilandi!")
            return redirect('employee_list')
    else:
        form = EmployeeForm(instance=employee)
    return render(request, 'attendance/employee_form.html', {'form': form, 'employee': employee})

@login_required
def employee_delete(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    if request.method == 'POST':
        employee.delete()
        messages.success(request, "Xodim o'chirildi!")
        return redirect('employee_list')
    return render(request, 'attendance/employee_confirm_delete.html', {'employee': employee})


@login_required
def bulk_attendance_create(request):
    employees = Employee.objects.filter(is_active=True)
    date_val = request.GET.get('date') or date.today()
    AttendanceFormSet = modelformset_factory(
        Attendance, form=AttendanceForm, can_delete=False,
        fields=['employee', 'date', 'status', 'comment', 'attachment'],
        extra=employees.count()
    )

    attendance_today = Attendance.objects.filter(date=date_val)
    initial_data = []
    employee_id_to_fio = {}
    for emp in employees:
        employee_id_to_fio[str(emp.id)] = {
            "first_name": emp.first_name,
            "last_name": emp.last_name,
        }
        rec = attendance_today.filter(employee=emp).first()
        if rec:
            initial_data.append({
                'employee': rec.employee.id,
                'date': rec.date,
                'status': rec.status,
                'comment': rec.comment,
                'attachment': rec.attachment
            })
        else:
            initial_data.append({
                'employee': emp.id,
                'date': date_val,
                'status': 'present',
            })

    if request.method == 'POST':
        formset = AttendanceFormSet(request.POST, request.FILES,
                                    queryset=Attendance.objects.none(),
                                    initial=initial_data)
        if formset.is_valid():
            formset.save()
            messages.success(request, "Davomat muvaffaqiyatli saqlandi!")
            return redirect('attendance_list')
    else:
        formset = AttendanceFormSet(queryset=Attendance.objects.none(), initial=initial_data)

    dayoff = DayOff.objects.filter(date=date_val).first() if hasattr(DayOff, 'date') else None

    return render(request, 'attendance/bulk_attendance_form.html', {
        'formset': formset,
        'employee_id_to_fio': employee_id_to_fio,
        'date_val': date_val,
        'dayoff': dayoff,
    })



@login_required
def attendance_list(request):
    day = request.GET.get('date')
    employees = Employee.objects.filter(is_active=True)
    filters = {}
    if day:
        try:
            day = date.fromisoformat(day)
            filters['date'] = day
        except Exception:
            day = date.today()
            filters['date'] = day
    else:
        day = date.today()
        filters['date'] = day
    if request.GET.get('status'):
        filters['status'] = request.GET['status']
    if request.GET.get('department'):
        filters['employee__department'] = request.GET['department']
    if request.GET.get('position'):
        filters['employee__position'] = request.GET['position']
    attendance = Attendance.objects.filter(**filters).select_related('employee')
    return render(request, 'attendance/attendance_list.html', {
        'attendance': attendance,
        'today': day,
        'employees': employees,
    })

@login_required
def attendance_update(request, pk):
    record = get_object_or_404(Attendance, pk=pk)
    if request.method == 'POST':
        form = AttendanceForm(request.POST, request.FILES, instance=record)
        if form.is_valid():
            form.save()
            messages.success(request, "Davomat yangilandi!")
            return redirect('attendance_list')
    else:
        form = AttendanceForm(instance=record)
    return render(request, 'attendance/attendance_form.html', {'form': form, 'record': record})

@login_required
def attendance_delete(request, pk):
    record = get_object_or_404(Attendance, pk=pk)
    if request.method == 'POST':
        record.delete()
        messages.success(request, "Davomat o'chirildi!")
        return redirect('attendance_list')
    return render(request, 'attendance/attendance_confirm_delete.html', {'record': record})

@login_required
def attendance_import(request):
    errors = []
    if request.method == 'POST':
        form = AttendanceImportForm(request.POST, request.FILES)
        if form.is_valid():
            file = request.FILES['file']
            ext = file.name.split('.')[-1]
            try:
                if ext in ['xls', 'xlsx']:
                    df = pd.read_excel(file)
                else:
                    df = pd.read_csv(file)
                count = 0
                for idx, row in df.iterrows():
                    try:
                        emp = Employee.objects.filter(
                            last_name=row['last_name'],
                            first_name=row['first_name']
                        ).first()
                        if not emp:
                            errors.append(f"{idx+2}-satr: Xodim topilmadi ({row.get('last_name','')} {row.get('first_name','')})")
                            continue
                        # Sana formati tekshiruvi
                        try:
                            row_date = row['date']
                            if not isinstance(row_date, str):
                                row_date = str(row_date)
                            date_obj = date.fromisoformat(row_date)
                        except Exception:
                            errors.append(f"{idx+2}-satr: Sana formati noto'g'ri ({row.get('date','')})")
                            continue
                        Attendance.objects.update_or_create(
                            employee=emp,
                            date=date_obj,
                            defaults={
                                'status': row['status'],
                                'comment': row.get('comment', ''),
                            }
                        )
                        count += 1
                    except Exception as e:
                        errors.append(f"{idx+2}-satr: {str(e)}")
                AttendanceImportLog.objects.create(
                    user=request.user,
                    file_name=file.name,
                    record_count=count,
                    success=(len(errors) == 0),
                    log='; '.join(errors) if errors else 'OK'
                )
                if count:
                    messages.success(request, f"{count} ta davomat import qilindi!")
                if errors:
                    messages.error(request, f"Quyidagi satrlarda xatoliklar: {'; '.join(errors)}")
            except Exception as e:
                AttendanceImportLog.objects.create(
                    user=request.user,
                    file_name=file.name,
                    record_count=0,
                    success=False,
                    log=str(e)
                )
                messages.error(request, f"Importda xatolik: {str(e)}")
            return redirect('attendance_import')
    else:
        form = AttendanceImportForm()
    return render(request, 'attendance/attendance_import.html', {'form': form})

@login_required
def attendance_export(request):
    if request.method == 'POST':
        # Get filter parameters
        date_from = request.POST.get('date_from')
        date_to = request.POST.get('date_to')
        department = request.POST.get('department')
        status = request.POST.get('status')
        
        # Build query
        filters = {}
        if date_from and date_to:
            try:
                date_from_obj = date.fromisoformat(date_from)
                date_to_obj = date.fromisoformat(date_to)
                filters['date__range'] = (date_from_obj, date_to_obj)
            except Exception as e:
                messages.error(request, f"Sana formatida xatolik: {str(e)}")
                return redirect('attendance_export')
        if department:
            filters['employee__department'] = department
        if status:
            filters['status'] = status
            
        # Get data
        attendances = Attendance.objects.filter(**filters).select_related('employee')
        
        # Create Excel file
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Davomat"
        # Add header row
        headers = ['Sana', 'Familiya', 'Ismi', 'Lavozim', 'Bo\'lim', 'Status', 'Izoh']
        for col_num, header in enumerate(headers, 1):
            ws.cell(row=1, column=col_num, value=header)
        
        # Add data rows
        for row_num, att in enumerate(attendances, 2):
            ws.cell(row=row_num, column=1, value=att.date)
            ws.cell(row=row_num, column=2, value=att.employee.last_name)
            ws.cell(row=row_num, column=3, value=att.employee.first_name)
            ws.cell(row=row_num, column=4, value=att.employee.position)
            ws.cell(row=row_num, column=5, value=att.employee.department)
            ws.cell(row=row_num, column=6, value=att.get_status_display())
            ws.cell(row=row_num, column=7, value=att.comment)
        
        # Create response
        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = 'attachment; filename="attendance.xlsx"'
        wb.save(response)
        return response
    else:
        # Get unique departments for filter options
        departments = Employee.objects.values_list('department', flat=True).distinct()
        # Get today and start of month for default date range
        today = timezone.now().date()
        start_of_month = today.replace(day=1)
        
        context = {
            'departments': departments,
            'statuses': Attendance.STATUS_CHOICES,
            'today': today,
            'start_of_month': start_of_month,
        }
        return render(request, 'attendance/attendance_export.html', context)

@login_required
def dayoff_list(request):
    days = DayOff.objects.order_by('-date')
    return render(request, 'attendance/dayoff_list.html', {'days': days})

@login_required
def dayoff_create(request):
    if request.method == 'POST':
        form = DayOffForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Yopiq sana qo'shildi!")
            return redirect('dayoff_list')
    else:
        form = DayOffForm()
    return render(request, 'attendance/dayoff_form.html', {'form': form})

@login_required
def dayoff_delete(request, pk):
    day = get_object_or_404(DayOff, pk=pk)
    if request.method == 'POST':
        day.delete()
        messages.success(request, "Yopiq sana o'chirildi!")
        return redirect('dayoff_list')
    return render(request, 'attendance/dayoff_confirm_delete.html', {'day': day})

@login_required
def individual_attendance_create(request, employee_id=None):
    """Har bir xodim uchun alohida davomat kiritish"""
    if employee_id:
        employee = get_object_or_404(Employee, pk=employee_id)
    else:
        # Agar employee_id ko'rsatilmagan bo'lsa, xodimni tanlash uchun forma ko'rsatiladi
        if request.method == 'POST':
            employee_id = request.POST.get('employee')
            if employee_id:
                return redirect('individual_attendance_create', employee_id=employee_id)
            else:
                messages.error(request, "Xodimni tanlang!")
        
        employees = Employee.objects.filter(is_active=True).order_by('location', 'department', 'last_name')
        locations = Employee.LOCATION_CHOICES
        return render(request, 'attendance/select_employee.html', {
            'employees': employees,
            'locations': locations
        })
    
    # Tanlangan xodim uchun davomat kiritish
    try:
        date_val = request.GET.get('date')
        if date_val:
            date_val = date.fromisoformat(date_val)
        else:
            date_val = date.today()
    except ValueError:
        date_val = date.today()
        messages.warning(request, "Noto'g'ri sana formati. Bugungi sana ishlatilmoqda.")
    
    attendance = Attendance.objects.filter(employee=employee, date=date_val).first()
    
    if request.method == 'POST':
        # Form ma'lumotlarini olish
        status = request.POST.get('status')
        comment = request.POST.get('comment', '')
        
        # Validatsiya
        if not status:
            messages.error(request, "Davomat holatini tanlang!")
            form = AttendanceForm(instance=attendance) if attendance else AttendanceForm(initial={'status': 'present'})
            return render(request, 'attendance/individual_attendance_form.html', {
                'form': form,
                'employee': employee,
                'date_val': date_val,
                'dayoff': DayOff.objects.filter(date=date_val).first()
            })
        
        # Agar status absent, sick yoki vacation bo'lsa, izoh majburiy
        if status in ['absent', 'sick', 'vacation'] and not comment.strip():
            messages.error(request, "Izoh/sabab kiritish majburiy!")
            form = AttendanceForm(instance=attendance) if attendance else AttendanceForm(initial={'status': status})
            return render(request, 'attendance/individual_attendance_form.html', {
                'form': form,
                'employee': employee,
                'date_val': date_val,
                'dayoff': DayOff.objects.filter(date=date_val).first()
            })
        
        # Davomat ma'lumotlarini saqlash
        try:
            if attendance:
                # Mavjud davomatni yangilash
                attendance.status = status
                attendance.comment = comment
                attendance.save()
            else:
                # Yangi davomat yaratish
                attendance = Attendance.objects.create(
                    employee=employee,
                    date=date_val,
                    status=status,
                    comment=comment
                )
            
            messages.success(request, f"{employee} uchun davomat saqlandi!")
            
            # Keyingi xodimga o'tish yoki ro'yxatga qaytish
            next_action = request.POST.get('next_action')
            if next_action == 'next_employee':
                # Xodimlar ro'yxatidan keyingi xodimni topish
                next_employee = Employee.objects.filter(
                    is_active=True,
                    location=employee.location
                ).filter(
                    Q(last_name__gt=employee.last_name) | 
                    (Q(last_name=employee.last_name) & Q(first_name__gt=employee.first_name))
                ).order_by('last_name', 'first_name').first()
                
                if next_employee:
                    return redirect('individual_attendance_create', employee_id=next_employee.id)
                else:
                    messages.info(request, "Siz ushbu joylashuvdagi oxirgi xodimga davomat kiritdingiz.")
                    return redirect('attendance_list')
            
            return redirect('attendance_list')
            
        except Exception as e:
            messages.error(request, f"Xatolik yuz berdi: {str(e)}")
    
    # GET so'rovi uchun forma tayyorlash
    form = AttendanceForm(instance=attendance) if attendance else AttendanceForm(initial={'status': 'present'})
    
    # Ish kuni emas kunini tekshirish
    dayoff = DayOff.objects.filter(date=date_val).first()
    
    return render(request, 'attendance/individual_attendance_form.html', {
        'form': form,
        'employee': employee,
        'date_val': date_val,
        'dayoff': dayoff
    })

@login_required
def attendance_statistics(request):
    period = request.GET.get('period', 'month')
    today = timezone.now().date()
    date_from, date_to = None, None

    if period == 'day':
        date_from = today
        date_to = today
    elif period == 'week':
        date_from = today - timedelta(days=today.weekday())
        date_to = date_from + timedelta(days=6)
    elif period == 'month':
        date_from = today.replace(day=1)
        next_month = (date_from.replace(day=28) + timedelta(days=4)).replace(day=1)
        date_to = next_month - timedelta(days=1)
    elif period == 'quarter':
        month = (today.month - 1) // 3 * 3 + 1
        date_from = date(today.year, month, 1)
        if month == 10:
            date_to = date(today.year, 12, 31)
        else:
            date_to = date(today.year, month + 3, 1) - timedelta(days=1)
    elif period == 'halfyear':
        if today.month <= 6:
            date_from = date(today.year, 1, 1)
            date_to = date(today.year, 6, 30)
        else:
            date_from = date(today.year, 7, 1)
            date_to = date(today.year, 12, 31)
    elif period == 'year':
        date_from = date(today.year, 1, 1)
        date_to = date(today.year, 12, 31)
    elif period == 'custom':
        try:
            date_from = date.fromisoformat(request.GET.get('date_from'))
            date_to = date.fromisoformat(request.GET.get('date_to'))
        except Exception:
            messages.error(request, "Sana formatida xatolik!")
            date_from = today.replace(day=1)
            date_to = today
    else:
        date_from = today.replace(day=1)
        date_to = today

    attendances = Attendance.objects.filter(date__range=[date_from, date_to])

    stats_by_status = attendances.values('status').annotate(count=Count('id')).order_by('status')
    
    # Calculate total for percentage calculations
    total_attendance = attendances.count()
    if total_attendance > 0:
        for item in stats_by_status:
            item['percentage'] = (item['count'] / total_attendance) * 100
    else:
        for item in stats_by_status:
            item['percentage'] = 0
    stats_by_employee = attendances.values(
        'employee__last_name', 'employee__first_name'
    ).annotate(
        total=Count('id'),
        present=Count('id', filter=Q(status='present')),
        absent=Count('id', filter=Q(status='absent')),
        late=Count('id', filter=Q(status='late')),
        vacation=Count('id', filter=Q(status='vacation')),
        sick=Count('id', filter=Q(status='sick')),
        business=Count('id', filter=Q(status='business')),
    ).order_by('-present', 'employee__last_name')

    stats_by_department = attendances.values(
        'employee__department'
    ).annotate(
        total=Count('id'),
        present=Count('id', filter=Q(status='present')),
        absent=Count('id', filter=Q(status='absent')),
        late=Count('id', filter=Q(status='late')),
        vacation=Count('id', filter=Q(status='vacation')),
        sick=Count('id', filter=Q(status='sick')),
        business=Count('id', filter=Q(status='business')),
    ).order_by('-present')
    
    # Joylashuv bo'yicha statistika
    stats_by_location = attendances.values(
        'employee__location'
    ).annotate(
        total=Count('id'),
        present=Count('id', filter=Q(status='present')),
        absent=Count('id', filter=Q(status='absent')),
        late=Count('id', filter=Q(status='late')),
        vacation=Count('id', filter=Q(status='vacation')),
        sick=Count('id', filter=Q(status='sick')),
        business=Count('id', filter=Q(status='business')),
    ).order_by('-present')

    trend = attendances.values('date', 'status').annotate(count=Count('id')).order_by('date')

    # QuerySet obyektlarini list formatiga o'tkazish
    stats_by_status_list = list(stats_by_status)
    stats_by_employee_list = list(stats_by_employee)
    stats_by_department_list = list(stats_by_department)
    stats_by_location_list = list(stats_by_location)
    trend_list = list(trend)
    
    # Kunlar bo'yicha statistika
    dates = attendances.values('date').annotate(count=Count('id')).order_by('date')
    stats_by_date = []
    for date_item in dates:
        date_stats = {
            'date': date_item['date'],
            'statuses': {}
        }
        for status in ['present', 'absent', 'late', 'vacation', 'sick', 'business']:
            count = attendances.filter(date=date_item['date'], status=status).count()
            date_stats['statuses'][status] = count
        stats_by_date.append(date_stats)
    
    # Prepare JSON-serialized data for charts
    import json
    
    # Status labels and counts for pie chart
    status_labels = [item['status'].title() for item in stats_by_status_list]
    status_counts = [item['count'] for item in stats_by_status_list]
    
    # Department data for bar chart
    department_labels = [item['employee__department'] for item in stats_by_department_list if item['employee__department']]
    department_present = [item['present'] for item in stats_by_department_list if item['employee__department']]
    department_absent = [item['absent'] for item in stats_by_department_list if item['employee__department']]
    department_late = [item['late'] for item in stats_by_department_list if item['employee__department']]
    
    # Location data for bar chart
    location_labels = [dict(Employee.LOCATION_CHOICES).get(item['employee__location'], item['employee__location']) 
                      for item in stats_by_location_list if item['employee__location']]
    location_present = [item['present'] for item in stats_by_location_list if item['employee__location']]
    location_absent = [item['absent'] for item in stats_by_location_list if item['employee__location']]
    location_late = [item['late'] for item in stats_by_location_list if item['employee__location']]
    
    # Trend data for line chart
    trend_dates = sorted(set(item['date'].strftime('%Y-%m-%d') for item in trend_list))
    trend_data = {}
    for status in ['present', 'absent', 'late', 'vacation', 'sick', 'business']:
        trend_data[status] = []
        for date_str in trend_dates:
            date_obj = date.fromisoformat(date_str)
            count = next((item['count'] for item in trend_list if item['date'] == date_obj and item['status'] == status), 0)
            trend_data[status].append(count)
    
    context = {
        'date_from': date_from,
        'date_to': date_to,
        'stats_by_status': stats_by_status_list,
        'stats_by_employee': stats_by_employee_list,
        'stats_by_department': stats_by_department_list,
        'stats_by_location': stats_by_location_list,
        'trend': trend_list,
        'stats_by_date': stats_by_date,
        'period': period,
        'location_choices': dict(Employee.LOCATION_CHOICES),
        # JSON-serialized data for charts
        'status_labels': json.dumps(status_labels),
        'status_counts': json.dumps(status_counts),
        'department_labels': json.dumps(department_labels),
        'department_present': json.dumps(department_present),
        'department_absent': json.dumps(department_absent),
        'department_late': json.dumps(department_late),
        'location_labels': json.dumps(location_labels),
        'location_present': json.dumps(location_present),
        'location_absent': json.dumps(location_absent),
        'location_late': json.dumps(location_late),
        'trend_dates': json.dumps(trend_dates),
        'trend_data': json.dumps(trend_data),
    }
    return render(request, 'attendance/attendance_statistics.html', context)

@login_required
def salary_statistics_view(request):
    import datetime
    today = datetime.date.today()
    year = int(request.GET.get('year', today.year))
    month = int(request.GET.get('month', today.month))
    # Statistikani hisoblash (agar kerak bo'lsa)
    calculate_monthly_stats(year, month)
    stats = MonthlyEmployeeStat.objects.filter(year=year, month=month).select_related('employee')
    form = SalaryStatFilterForm(initial={'year': year, 'month': month})
    # Kelmagan kunlar soni va sanalari
    absent_days = {}
    for stat in stats:
        absents = Attendance.objects.filter(
            employee=stat.employee,
            date__year=year,
            date__month=month,
            status='absent'
        ).values_list('date', flat=True)
        stat.absent_count = len(absents)
        stat.absent_dates = list(absents)
    # Umumiy summalar
    total_salary = sum([s.salary for s in stats])
    total_bonus = sum([s.bonus for s in stats])
    total_penalty = sum([s.penalty for s in stats])
    total_accrued = sum([s.accrued for s in stats])
    total_paid = sum([s.paid for s in stats])
    total_debt_start = sum([s.debt_start for s in stats])
    total_debt_end = sum([s.debt_end for s in stats])
    total_absent = sum([s.absent_count for s in stats])
    currency_set = set([s.currency for s in stats])
    total_currency = currency_set.pop() if len(currency_set) == 1 else '...'
    # Valyuta bo'yicha jami qiymatlar
    currency_totals = {}
    for stat in stats:
        cur = stat.currency
        if cur not in currency_totals:
            currency_totals[cur] = {
                'salary': 0, 'bonus': 0, 'penalty': 0, 'accrued': 0, 'paid': 0, 'debt_start': 0, 'debt_end': 0
            }
        currency_totals[cur]['salary'] += float(stat.salary)
        currency_totals[cur]['bonus'] += float(stat.bonus)
        currency_totals[cur]['penalty'] += float(stat.penalty)
        currency_totals[cur]['accrued'] += float(stat.accrued)
        currency_totals[cur]['paid'] += float(stat.paid)
        currency_totals[cur]['debt_start'] += float(stat.debt_start)
        currency_totals[cur]['debt_end'] += float(stat.debt_end)
    return render(request, 'attendance/salary_statistics.html', {
        'stats': stats,
        'form': form,
        'year': year,
        'month': month,
        'total_salary': total_salary,
        'total_bonus': total_bonus,
        'total_penalty': total_penalty,
        'total_accrued': total_accrued,
        'total_paid': total_paid,
        'total_debt_start': total_debt_start,
        'total_debt_end': total_debt_end,
        'absent_days': absent_days,
        'total_absent': total_absent,
        'total_currency': total_currency,
        'currency_totals': currency_totals,
    })

@login_required
def export_salary_statistics_excel(request):
    import datetime
    today = datetime.date.today()
    year = int(request.GET.get('year', today.year))
    month = int(request.GET.get('month', today.month))
    calculate_monthly_stats(year, month)
    stats = MonthlyEmployeeStat.objects.filter(year=year, month=month).select_related('employee')
    # Absentlarni har bir stat obyektiga biriktiramiz
    for stat in stats:
        absents = Attendance.objects.filter(
            employee=stat.employee,
            date__year=year,
            date__month=month,
            status='absent'
        ).values_list('date', flat=True)
        stat.absent_count = len(absents)
        stat.absent_dates = list(absents)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"{year}-{month:02d}"
    headers = [
        '№', 'F I O xodim', 'Oylik', 'Valyuta', 'Mukofot', 'Jarima', 'Oy kunlari',
        'Ishlangan kunlar', 'Kelmagan kunlar soni', 'Kelmagan kunlar sanalari',
        'Hisoblangan', "To'langan", 'Qarzdorlik (boshl.)', 'Qarzdorlik (oxiri)'
    ]
    ws.append(headers)
    total_salary = total_bonus = total_penalty = total_accrued = total_paid = total_debt_start = total_debt_end = total_absent = 0
    # Valyuta bo'yicha jami qiymatlar (Excel uchun)
    currency_totals = {}
    for stat in stats:
        cur = stat.currency
        if cur not in currency_totals:
            currency_totals[cur] = {
                'salary': 0, 'bonus': 0, 'penalty': 0, 'accrued': 0, 'paid': 0, 'debt_start': 0, 'debt_end': 0
            }
        currency_totals[cur]['salary'] += float(stat.salary)
        currency_totals[cur]['bonus'] += float(stat.bonus)
        currency_totals[cur]['penalty'] += float(stat.penalty)
        currency_totals[cur]['accrued'] += float(stat.accrued)
        currency_totals[cur]['paid'] += float(stat.paid)
        currency_totals[cur]['debt_start'] += float(stat.debt_start)
        currency_totals[cur]['debt_end'] += float(stat.debt_end)
    # Jami qatorlari har bir valyuta uchun alohida
    for cur, vals in currency_totals.items():
        ws.append([
            '', f'Jami ({cur})', vals['salary'], cur, vals['bonus'], vals['penalty'], '', '', '', '', vals['accrued'], vals['paid'], vals['debt_start'], vals['debt_end']
        ])
    for idx, stat in enumerate(stats, 1):
        ws.append([
            idx,
            f"{stat.employee.last_name} {stat.employee.first_name}",
            float(stat.salary),
            stat.currency,
            float(stat.bonus),
            float(stat.penalty),
            stat.days_in_month,
            stat.worked_days,
            stat.absent_count,
            ', '.join([str(d) for d in stat.absent_dates]),
            float(stat.accrued),
            float(stat.paid),
            float(stat.debt_start),
            float(stat.debt_end),
        ])
        total_salary += float(stat.salary)
        total_bonus += float(stat.bonus)
        total_penalty += float(stat.penalty)
        total_accrued += float(stat.accrued)
        total_paid += float(stat.paid)
        total_debt_start += float(stat.debt_start)
        total_debt_end += float(stat.debt_end)
        total_absent += stat.absent_count
    # Eski jami qatorini olib tashlab, har bir valyuta uchun alohida jami qatorini yozaman
    for cur, vals in currency_totals.items():
        ws.append([
            '', f'Jami ({cur})', vals['salary'], cur, vals['bonus'], vals['penalty'], '', '', '', '', vals['accrued'], vals['paid'], vals['debt_start'], vals['debt_end']
        ])
    # Ustunlarni kengaytirish
    # Sarlavha uchun style
    header_font = Font(bold=True, size=12, color='FFFFFF')
    header_fill = PatternFill(start_color='4cc9f0', end_color='4361ee', fill_type='solid')
    for col in range(1, len(headers)+1):
        cell = ws.cell(row=1, column=col)
        cell.font = header_font
        cell.fill = PatternFill(start_color='4cc9f0', end_color='4361ee', fill_type='solid')
        cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.column_dimensions[get_column_letter(col)].width = 18
    # Jadvalga border
    thin = Side(border_style="thin", color="AAAAAA")
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=len(headers)):
        for cell in row:
            cell.border = Border(top=thin, left=thin, right=thin, bottom=thin)
    # Jami qatorlari uchun style
    for i in range(ws.max_row-len(currency_totals)+1, ws.max_row+1):
        for j in range(1, len(headers)+1):
            cell = ws.cell(row=i, column=j)
            cell.font = Font(bold=True, color='222222')
            cell.fill = PatternFill(start_color='b2f7ef', end_color='4cc9f0', fill_type='solid')
            cell.alignment = Alignment(horizontal='center', vertical='center')
    # Kompaniya va oy sarlavhasi
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
    title_cell = ws.cell(row=1, column=1)
    title_cell.value = f"ISOMER OIL Davomat - Oylik xodim statistikasi ({year}-{month:02d})"
    title_cell.font = Font(bold=True, size=14, color='222222')
    title_cell.alignment = Alignment(horizontal='center', vertical='center')
    title_cell.fill = PatternFill(start_color='b2f7ef', end_color='4cc9f0', fill_type='solid')
    # Header row (2)
    for col in range(1, len(headers)+1):
        cell = ws.cell(row=2, column=col)
        cell.value = headers[col-1]
        cell.font = Font(bold=True, size=12, color='FFFFFF')
        cell.fill = PatternFill(start_color='4cc9f0', end_color='4361ee', fill_type='solid')
        cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.column_dimensions[get_column_letter(col)].width = 18
    # Jadvalga border va format
    thin = Side(border_style="thin", color="AAAAAA")
    number_style = NamedStyle(name="number_style", number_format="# ##0.00")
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=len(headers)):
        for cell in row:
            cell.border = Border(top=thin, left=thin, right=thin, bottom=thin)
            if isinstance(cell.value, (int, float)):
                cell.style = number_style
    # Jami qatorlari uchun style (oxirgi qatorlar)
    for i in range(ws.max_row-len(currency_totals)+1, ws.max_row+1):
        for j in range(1, len(headers)+1):
            cell = ws.cell(row=i, column=j)
            cell.font = Font(bold=True, color='222222')
            cell.fill = PatternFill(start_color='b2f7ef', end_color='4cc9f0', fill_type='solid')
            cell.alignment = Alignment(horizontal='center', vertical='center')
    # Jadval ustunlarini optimal kenglikka moslash
    for col in ws.columns:
        max_length = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            try:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            except:
                pass
        ws.column_dimensions[col_letter].width = max(12, min(max_length+2, 30))
    # Jadvalga filter qo‘shish
    ws.auto_filter.ref = ws.dimensions
    # Ustunlarga comment (ixtiyoriy, misol uchun)
    ws.cell(row=3, column=3).comment = Comment("Xodimning oylik stavkasi", "AI")
    ws.cell(row=3, column=4).comment = Comment("Oylik valyutasi", "AI")
    ws.cell(row=3, column=7).comment = Comment("Xodim oy davomida ishlagan kunlar soni", "AI")
    ws.cell(row=3, column=8).comment = Comment("Kelmagan kunlar soni", "AI")
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    filename = f"salary_statistics_{year}_{month:02d}.xlsx"
    response['Content-Disposition'] = f'attachment; filename={filename}'
    wb.save(response)
    return response

@login_required
def edit_salary_stat(request, stat_id):
    stat = MonthlyEmployeeStat.objects.get(id=stat_id)
    if request.method == 'POST':
        form = SalaryStatEditForm(request.POST, instance=stat)
        if form.is_valid():
            form.save()
            return redirect(f"{request.GET.get('next', '/statistics/salary/')}")
    else:
        form = SalaryStatEditForm(instance=stat)
    return render(request, 'attendance/edit_salary_stat.html', {'form': form, 'stat': stat})
