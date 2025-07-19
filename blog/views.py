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
from .services import calculate_monthly_stats, calculate_working_days_in_month
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
    
    # Бугун ёпиқ кун ёки якшанбами текшириш
    is_dayoff = DayOff.objects.filter(date=today).exists()
    is_sunday = today.weekday() == 6
    
    # Офис ходимларини ва ёпиқ кунларда барчани чиқариш
    if is_dayoff or is_sunday:
        # Ёпиқ кунларда ҳеч кимни "киритилмаган"га чиқармаслик
        not_filled = Employee.objects.none()
    else:
        # Фақат офис ходимларидан бошқаларни текшириш (office емас ходимлар)
        employees_need_attendance = employees.exclude(employee_type='office')
        not_filled = employees_need_attendance.exclude(id__in=attendance_today.values_list('employee', flat=True))
    
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
    today = date.today()
    # Бугун ёпиқ кун ёки якшанбами текшириш
    is_dayoff = DayOff.objects.filter(date=today).exists()
    is_sunday = today.weekday() == 6
    
    if is_dayoff or is_sunday:
        dayoff_reason = DayOff.objects.filter(date=today).first()
        reason = dayoff_reason.reason if dayoff_reason else "Якшанба"
        messages.error(request, f"Бугун {reason} - давомат киритиб бўлмайди!")
        return redirect('dashboard')
    
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
    
    # Танланган санани текшириш
    is_dayoff = DayOff.objects.filter(date=date_val).exists()
    is_sunday = date_val.weekday() == 6
    
    if is_dayoff or is_sunday:
        dayoff_reason = DayOff.objects.filter(date=date_val).first()
        reason = dayoff_reason.reason if dayoff_reason else "Якшанба"
        messages.error(request, f"{date_val.strftime('%d.%m.%Y')} - {reason} кунида давомат киритиб бўлмайди!")
        return redirect('dashboard')
    
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
    
    # Ишчи кунларни ҳисоблаш
    working_days_in_month, total_days_in_month = calculate_working_days_in_month(year, month)
    
    # Ҳар бир stat объектига ишчи кунлар сонини қўшиш
    for stat in stats:
        stat.working_days_in_month = working_days_in_month
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
    
    # Ишчи кунларни ҳисоблаш
    working_days_in_month, total_days_in_month = calculate_working_days_in_month(year, month)
    
    # Absentlarni va ишчи кунларни har bir stat obyektiga biriktiramiz
    for stat in stats:
        stat.working_days_in_month = working_days_in_month
        absents = Attendance.objects.filter(
            employee=stat.employee,
            date__year=year,
            date__month=month,
            status='absent'
        ).values_list('date', flat=True)
        stat.absent_count = len(absents)
        stat.absent_dates = list(absents)
    
    # Xodimlarni turlari bo'yicha guruhlash
    half_stats = [s for s in stats if s.employee.employee_type == 'half']
    full_stats = [s for s in stats if s.employee.employee_type == 'full']
    office_stats = [s for s in stats if s.employee.employee_type == 'office']
    
    wb = openpyxl.Workbook()
    
    # Standart headers
    headers = [
        '№', 'F I O xodim', 'Oylik', 'Valyuta', 'Mukofot', 'Jarima', 'Oy kunlari', 'Ishchi kunlari',
        'Ishlangan kunlar', 'Kelmagan kunlar soni', 'Kelmagan sanalari',
        'Hisoblangan', "To'langan", 'Qarzdorlik (boshl.)', 'Qarzdorlik (oxiri)'
    ]
    
    def create_worksheet(worksheet, title, employee_stats, bg_color='4CC9F0', accent_color='3A0CA3'):
        """Har bir sheet uchun umumiy funksiya - yangi dizayn bilan"""
        worksheet.title = title
        
        # 🎨 Yangi ranglar palitasi
        colors = {
            'half': {'bg': 'FF6B35', 'accent': 'E55D2B', 'light': 'FFE5DF'},
            'full': {'bg': '3D5A80', 'accent': '293241', 'light': 'E8ECF0'},
            'office': {'bg': '7209B7', 'accent': '560BAD', 'light': 'F3E8FF'},
            'summary': {'bg': '2B9348', 'accent': '1E6933', 'light': 'E8F5E8'}
        }
        
        # Rang tanlash
        if '15 kunlik' in title:
            color_scheme = colors['half']
        elif "To'liq stavka" in title:
            color_scheme = colors['full']
        elif 'Ofis' in title:
            color_scheme = colors['office']
        else:
            color_scheme = colors['summary']
        
        # 🏆 TITLE qatori - gradient effekt uchun 2 qator
        worksheet.merge_cells(start_row=1, start_column=1, end_row=2, end_column=len(headers))
        title_cell = worksheet.cell(row=1, column=1)
        
        # Title matnini emoji bilan boyitish
        title_icons = {
            '15 kunlik': '⏰ ',
            "To'liq stavka": '👔 ',
            'Ofis': '💼 ',
            'Umumiy': '📊 '
        }
        icon = next((icon for key, icon in title_icons.items() if key in title), '🏢 ')
        
        title_cell.value = f"{icon}ISOMER OIL - {title.upper()}\n📅 {year}-yil {month:02d}-oy"
        title_cell.font = Font(name='Calibri', bold=True, size=18, color='FFFFFF')
        title_cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        title_cell.fill = PatternFill(start_color=color_scheme['bg'], end_color=color_scheme['bg'], fill_type='solid')
        
        # Qo'shimcha stil uchun title cellni balandlashtirish
        worksheet.row_dimensions[1].height = 45
        worksheet.row_dimensions[2].height = 15
        
        # 📋 Headers qatori - gradient effekt
        for col, header in enumerate(headers, 1):
            cell = worksheet.cell(row=3, column=col)
            
            # Header matnini yanada tushunarli qilish
            header_translations = {
                'F I O xodim': '👤 F.I.O',
                'Oylik': '💰 Oylik',
                'Valyuta': '💱 Valyuta',
                'Mukofot': '🎁 Bonus',
                'Jarima': '⚠️ Jarima',
                'Oy kunlari': '📅 Oy kunlari',
                'Ishchi kunlari': '⚡ Ish kunlari',
                'Ishlangan kunlar': '✅ Ishlangan',
                'Kelmagan kunlar soni': '❌ Yo\'q',
                'Kelmagan sanalari': '📋 Yo\'q sanalar',
                'Hisoblangan': '🧮 Hisoblangan',
                "To'langan": '💸 To\'langan',
                'Qarzdorlik (boshl.)': '📉 Qarz (bosh)',
                'Qarzdorlik (oxiri)': '📈 Qarz (oxir)'
            }
            
            display_header = header_translations.get(header, header)
            cell.value = display_header
            cell.font = Font(name='Calibri', bold=True, size=11, color='FFFFFF')
            cell.fill = PatternFill(start_color=color_scheme['accent'], end_color=color_scheme['accent'], fill_type='solid')
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        
        # Headers qatorini balandlashtirish
        worksheet.row_dimensions[3].height = 35
        
        # 📊 Ma'lumotlar qatorlari - alternativ ranglar bilan
        row_num = 4
        currency_totals = {}
        
        for idx, stat in enumerate(employee_stats, 1):
            cur = stat.currency
            if cur not in currency_totals:
                currency_totals[cur] = {
                    'salary': 0, 'bonus': 0, 'penalty': 0, 'accrued': 0, 
                    'paid': 0, 'debt_start': 0, 'debt_end': 0, 'count': 0
                }
            
            currency_totals[cur]['salary'] += float(stat.salary)
            currency_totals[cur]['bonus'] += float(stat.bonus)
            currency_totals[cur]['penalty'] += float(stat.penalty)
            currency_totals[cur]['accrued'] += float(stat.accrued)
            currency_totals[cur]['paid'] += float(stat.paid)
            currency_totals[cur]['debt_start'] += float(stat.debt_start)
            currency_totals[cur]['debt_end'] += float(stat.debt_end)
            currency_totals[cur]['count'] += 1
            
            row_data = [
                idx,
                f"{stat.employee.last_name} {stat.employee.first_name}",
                float(stat.salary),
                stat.currency,
                float(stat.bonus),
                float(stat.penalty),
                stat.days_in_month,
                working_days_in_month if stat.employee.employee_type != 'half' else 15,
                stat.worked_days,
                stat.absent_count,
                ', '.join([str(d.strftime('%d.%m')) for d in stat.absent_dates]),
                float(stat.accrued),
                float(stat.paid),
                float(stat.debt_start),
                float(stat.debt_end),
            ]
            
            # ✨ Har bir qator uchun ranglar - zebra effekt
            is_even_row = idx % 2 == 0
            row_bg_color = color_scheme['light'] if is_even_row else 'FFFFFF'
            
            for col, value in enumerate(row_data, 1):
                cell = worksheet.cell(row=row_num, column=col)
                cell.value = value
                
                # 🎨 Qiymatga qarab ranglar
                if isinstance(value, (int, float)) and col > 2:
                    cell.number_format = '#,##0.00'
                    # Musbat/manfiy qiymatlar uchun ranglar
                    if col in [12, 13]:  # Hisoblangan, To'langan
                        if value > 0:
                            cell.font = Font(name='Calibri', size=10, color='2D5016', bold=True)
                        else:
                            cell.font = Font(name='Calibri', size=10, color='8B0000')
                    elif col in [14, 15]:  # Qarzdorlik
                        if value > 0:
                            cell.font = Font(name='Calibri', size=10, color='D63031', bold=True)
                        elif value < 0:
                            cell.font = Font(name='Calibri', size=10, color='00B894', bold=True)
                        else:
                            cell.font = Font(name='Calibri', size=10, color='636E72')
                    else:
                        cell.font = Font(name='Calibri', size=10, color='2D3436')
                else:
                    cell.font = Font(name='Calibri', size=10, color='2D3436')
                
                # ⚠️ Kelmagan kunlar uchun maxsus rang
                if col == 10 and isinstance(value, int) and value > 0:  # Kelmagan kunlar soni
                    cell.font = Font(name='Calibri', size=10, color='D63031', bold=True)
                    cell.fill = PatternFill(start_color='FFE5E5', end_color='FFE5E5', fill_type='solid')
                elif col == 11 and value and str(value).strip():  # Kelmagan sanalar
                    cell.font = Font(name='Calibri', size=9, color='E17055')
                    cell.fill = PatternFill(start_color='FFE5E5', end_color='FFE5E5', fill_type='solid')
                else:
                    cell.fill = PatternFill(start_color=row_bg_color, end_color=row_bg_color, fill_type='solid')
                
                # Alignment
                if col == 1:  # №
                    cell.alignment = Alignment(horizontal='center', vertical='center')
                elif col == 2:  # F.I.O
                    cell.alignment = Alignment(horizontal='left', vertical='center', indent=1)
                elif col in [4, 7, 8, 9, 10]:  # Valyuta, kunlar
                    cell.alignment = Alignment(horizontal='center', vertical='center')
                elif col == 11:  # Sanalar
                    cell.alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)
                else:  # Raqamlar
                    cell.alignment = Alignment(horizontal='right', vertical='center')
            
            # Qatorni balandlashtirish
            worksheet.row_dimensions[row_num].height = 25
            row_num += 1
        
        # 🏆 JAMI qatorlari - gradient effekt bilan
        row_num += 2  # Bo'sh qator + separator
        
        # Separator qatori
        separator_row = row_num - 1
        worksheet.merge_cells(start_row=separator_row, start_column=1, end_row=separator_row, end_column=len(headers))
        separator_cell = worksheet.cell(row=separator_row, column=1)
        separator_cell.value = "═" * 50
        separator_cell.font = Font(name='Calibri', size=8, color=color_scheme['accent'])
        separator_cell.alignment = Alignment(horizontal='center')
        separator_cell.fill = PatternFill(start_color='F8F9FA', end_color='F8F9FA', fill_type='solid')
        worksheet.row_dimensions[separator_row].height = 8
        
        for cur, vals in currency_totals.items():
            # 💰 Currency icon
            currency_icons = {'UZS': '🇺🇿', 'USD': '🇺🇸', 'EUR': '🇪🇺'}
            currency_icon = currency_icons.get(cur, '💱')
            
            jami_row = [
                '📊', f'{currency_icon} JAMI ({cur})', vals['salary'], cur, vals['bonus'], vals['penalty'], 
                '', '', '', '', '', vals['accrued'], vals['paid'], vals['debt_start'], vals['debt_end']
            ]
            
            for col, value in enumerate(jami_row, 1):
                cell = worksheet.cell(row=row_num, column=col)
                cell.value = value
                
                # 🌟 Gradient effekt uchun ranglar
                if col == 1:  # Icon
                    cell.font = Font(name='Calibri', bold=True, size=16, color=color_scheme['bg'])
                    cell.fill = PatternFill(start_color='FFFFFF', end_color='FFFFFF', fill_type='solid')
                elif col == 2:  # Label
                    cell.font = Font(name='Calibri', bold=True, size=13, color='FFFFFF')
                    cell.fill = PatternFill(start_color=color_scheme['bg'], end_color=color_scheme['bg'], fill_type='solid')
                else:
                    cell.font = Font(name='Calibri', bold=True, size=11, color='FFFFFF')
                    cell.fill = PatternFill(start_color=color_scheme['accent'], end_color=color_scheme['accent'], fill_type='solid')
                    
                if isinstance(value, (int, float)) and col > 2:
                    cell.number_format = '#,##0.00'
                    # Qiymat bo'yicha rang
                    if col in [12, 13] and value > 0:  # Hisoblangan, To'langan
                        cell.font = Font(name='Calibri', bold=True, size=11, color='90EE90')
                    elif col in [14, 15]:  # Qarzdorlik
                        if value > 0:
                            cell.font = Font(name='Calibri', bold=True, size=11, color='FFCCCB')
                        elif value < 0:
                            cell.font = Font(name='Calibri', bold=True, size=11, color='90EE90')
                
                cell.alignment = Alignment(horizontal='center', vertical='center')
            
            # JAMI qatorini balandlashtirish
            worksheet.row_dimensions[row_num].height = 35
            row_num += 1
        
        # 🎨 Advanced Borders va Professional Formatting
        # Title borders - qalin
        thick_border = Side(border_style="thick", color=color_scheme['bg'])
        medium_border = Side(border_style="medium", color=color_scheme['accent'])
        thin_border = Side(border_style="thin", color="CCCCCC")
        dotted_border = Side(border_style="dotted", color="DDDDDD")
        
        # Title qatori uchun
        for col in range(1, len(headers) + 1):
            for row in [1, 2]:
                cell = worksheet.cell(row=row, column=col)
                cell.border = Border(
                    top=thick_border if row == 1 else thin_border,
                    bottom=thick_border if row == 2 else thin_border,
                    left=thick_border if col == 1 else thin_border,
                    right=thick_border if col == len(headers) else thin_border
                )
        
        # Headers qatori uchun
        for col in range(1, len(headers) + 1):
            cell = worksheet.cell(row=3, column=col)
            cell.border = Border(
                top=medium_border, bottom=medium_border,
                left=medium_border if col == 1 else thin_border,
                right=medium_border if col == len(headers) else thin_border
            )
        
        # Ma'lumotlar qatorlari uchun
        data_start_row = 4
        data_end_row = row_num - len(currency_totals) - 2
        
        for row in range(data_start_row, data_end_row):
            for col in range(1, len(headers) + 1):
                cell = worksheet.cell(row=row, column=col)
                # Alternativ qatorlar uchun turli xil borderlar
                if (row - data_start_row) % 2 == 0:
                    cell.border = Border(
                        top=dotted_border, bottom=dotted_border,
                        left=thin_border, right=thin_border
                    )
                else:
                    cell.border = Border(
                        top=thin_border, bottom=thin_border,
                        left=thin_border, right=thin_border
                    )
        
        # JAMI qatorlari uchun qalin borderlar
        jami_start_row = row_num - len(currency_totals)
        for row in range(jami_start_row, row_num):
            for col in range(1, len(headers) + 1):
                cell = worksheet.cell(row=row, column=col)
                cell.border = Border(
                    top=thick_border, bottom=thick_border,
                    left=thick_border if col == 1 else medium_border,
                    right=thick_border if col == len(headers) else medium_border
                )
        
        # 📏 Ustunlar kengligini professional sozlash
        column_widths = [6, 28, 15, 10, 14, 14, 12, 14, 14, 14, 25, 18, 18, 18, 18]
        for col, width in enumerate(column_widths, 1):
            worksheet.column_dimensions[get_column_letter(col)].width = width
        
        # 🔍 Advanced Auto filter
        worksheet.auto_filter.ref = f"A3:{get_column_letter(len(headers))}{data_end_row-1}"
        
        # ❄️ Freeze panes - Headers ni muzlatish
        worksheet.freeze_panes = 'A4'
        
        return currency_totals
    
    # 🎯 1. 15 kunlik xodimlar - Qizil/Olov rang
    if half_stats:
        ws_half = wb.active
        create_worksheet(ws_half, "15 kunlik xodimlar", half_stats)
    
    # 🎯 2. To'liq stavka xodimlar - Havo kuchlar rangi 
    if full_stats:
        ws_full = wb.create_sheet("To'liq stavka")
        create_worksheet(ws_full, "To'liq stavka xodimlar", full_stats)
    
    # 🎯 3. Ofis xodimlari - Binafsha rang
    if office_stats:
        ws_office = wb.create_sheet("Ofis xodimlari")
        create_worksheet(ws_office, "Ofis xodimlari", office_stats)
    
    # 🏆 4. UMUMIY ma'lumot - Premium dizayn
    ws_summary = wb.create_sheet("📊 Umumiy")
    ws_summary.title = "📊 Umumiy"
    
    # 🎨 Professional Summary Layout
    # Company logo va title (virtual logo)
    ws_summary.merge_cells(start_row=1, start_column=1, end_row=3, end_column=6)
    logo_cell = ws_summary.cell(row=1, column=1)
    logo_cell.value = f"🏢 ISOMER OIL\n📊 OYLIK STATISTIKA\n📅 {year}-yil {month:02d}-oy"
    logo_cell.font = Font(name='Calibri', bold=True, size=20, color='FFFFFF')
    logo_cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    logo_cell.fill = PatternFill(start_color='2B9348', end_color='1E6933', fill_type='solid')
    ws_summary.row_dimensions[1].height = 25
    ws_summary.row_dimensions[2].height = 25
    ws_summary.row_dimensions[3].height = 25
    
    # Summary headers
    summary_headers = [
        "🏷️ Xodim turlari", "👥 Soni", "💰 Jami oylik (UZS)", 
        "🧮 Jami hisoblangan (UZS)", "💸 Jami to'langan (UZS)", "📈 Foiz"
    ]
    
    for col, header in enumerate(summary_headers, 1):
        cell = ws_summary.cell(row=5, column=col)
        cell.value = header
        cell.font = Font(name='Calibri', bold=True, size=12, color='FFFFFF')
        cell.fill = PatternFill(start_color='1E6933', end_color='1E6933', fill_type='solid')
        cell.alignment = Alignment(horizontal='center', vertical='center')
    
    ws_summary.row_dimensions[5].height = 30
    
    # Har bir tur bo'yicha hisoblash va ranglar
    type_colors = {
        "15 kunlik xodimlar": {'bg': 'FFE5DF', 'text': 'E55D2B', 'icon': '⏰'},
        "To'liq stavka xodimlar": {'bg': 'E8ECF0', 'text': '293241', 'icon': '👔'},
        "Ofis xodimlari": {'bg': 'F3E8FF', 'text': '560BAD', 'icon': '💼'},
    }
    
    grand_total_salary = grand_total_accrued = grand_total_paid = 0
    grand_total_count = 0
    current_row = 6
    
    for type_name, type_stats in [("15 kunlik xodimlar", half_stats), ("To'liq stavka xodimlar", full_stats), ("Ofis xodimlari", office_stats)]:
        if type_stats:
            # Faqat UZS valyutasidagi summalarni hisoblash
            uzs_stats = [s for s in type_stats if s.currency == 'UZS']
            count = len(type_stats)
            total_salary = sum(float(s.salary) for s in uzs_stats)
            total_accrued = sum(float(s.accrued) for s in uzs_stats)
            total_paid = sum(float(s.paid) for s in uzs_stats)
            
            # Foizni hisoblash
            percentage = (total_accrued / total_salary * 100) if total_salary > 0 else 0
            
            # Color scheme
            colors = type_colors[type_name]
            icon = colors['icon']
            
            row_data = [
                f"{icon} {type_name}", count, total_salary, total_accrued, total_paid, f"{percentage:.1f}%"
            ]
            
            for col, value in enumerate(row_data, 1):
                cell = ws_summary.cell(row=current_row, column=col)
                cell.value = value
                cell.font = Font(name='Calibri', size=11, color=colors['text'], bold=True)
                cell.fill = PatternFill(start_color=colors['bg'], end_color=colors['bg'], fill_type='solid')
                cell.alignment = Alignment(horizontal='center' if col in [2, 6] else 'left', vertical='center')
                
                if isinstance(value, (int, float)) or (isinstance(value, str) and value.replace('.','').replace(',','').isdigit()):
                    if col in [3, 4, 5]:  # Money columns
                        cell.number_format = '#,##0.00'
                        cell.alignment = Alignment(horizontal='right', vertical='center')
            
            ws_summary.row_dimensions[current_row].height = 25
            current_row += 1
            
            grand_total_count += count
            grand_total_salary += total_salary
            grand_total_accrued += total_accrued
            grand_total_paid += total_paid
    
    # Grand total row
    current_row += 1
    grand_percentage = (grand_total_accrued / grand_total_salary * 100) if grand_total_salary > 0 else 0
    grand_total_data = [
        "🏆 UMUMIY JAMI", grand_total_count, grand_total_salary, 
        grand_total_accrued, grand_total_paid, f"{grand_percentage:.1f}%"
    ]
    
    # Grand total styling
    for col, value in enumerate(grand_total_data, 1):
        cell = ws_summary.cell(row=current_row, column=col)
        cell.value = value
        cell.font = Font(name='Calibri', bold=True, size=14, color='FFFFFF')
        cell.fill = PatternFill(start_color='2B9348', end_color='1E6933', fill_type='solid')
        cell.alignment = Alignment(horizontal='center' if col in [2, 6] else 'left', vertical='center')
        
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.replace('.','').replace(',','').isdigit()):
            if col in [3, 4, 5]:  # Money columns
                cell.number_format = '#,##0.00'
                cell.alignment = Alignment(horizontal='right', vertical='center')
    
    ws_summary.row_dimensions[current_row].height = 35
    
    # 📊 Additional Statistics Box
    stats_start_row = current_row + 3
    
    # Statistics header
    ws_summary.merge_cells(start_row=stats_start_row, start_column=1, end_row=stats_start_row, end_column=6)
    stats_header = ws_summary.cell(row=stats_start_row, column=1)
    stats_header.value = "📈 QO'SHIMCHA STATISTIKA"
    stats_header.font = Font(name='Calibri', bold=True, size=14, color='FFFFFF')
    stats_header.fill = PatternFill(start_color='6C5CE7', end_color='A29BFE', fill_type='solid')
    stats_header.alignment = Alignment(horizontal='center', vertical='center')
    ws_summary.row_dimensions[stats_start_row].height = 30
    
    # Statistics data
    avg_salary = grand_total_salary / grand_total_count if grand_total_count > 0 else 0
    efficiency = (grand_total_paid / grand_total_accrued * 100) if grand_total_accrued > 0 else 0
    debt_ratio = ((grand_total_accrued - grand_total_paid) / grand_total_accrued * 100) if grand_total_accrued > 0 else 0
    
    additional_stats = [
        ["📊 Ko'rsatkich", "📈 Qiymat"],
        ["💰 O'rtacha oylik", f"{avg_salary:,.0f} UZS"],
        ["⚡ To'lov samaradorligi", f"{efficiency:.1f}%"],
        ["⚠️ Qarzdorlik nisbati", f"{debt_ratio:.1f}%"],
        ["👥 Jami xodimlar", f"{grand_total_count} kishi"],
    ]
    
    for row_offset, (label, value) in enumerate(additional_stats):
        row = stats_start_row + 1 + row_offset
        
        # Label
        label_cell = ws_summary.cell(row=row, column=1)
        label_cell.value = label
        if row_offset == 0:  # Header
            label_cell.font = Font(name='Calibri', bold=True, size=11, color='FFFFFF')
            label_cell.fill = PatternFill(start_color='74B9FF', end_color='0984E3', fill_type='solid')
        else:
            label_cell.font = Font(name='Calibri', bold=True, size=10, color='2D3436')
            label_cell.fill = PatternFill(start_color='DDDDDD', end_color='DDDDDD', fill_type='solid')
        label_cell.alignment = Alignment(horizontal='left', vertical='center')
        
        # Value
        value_cell = ws_summary.cell(row=row, column=2)
        value_cell.value = value
        if row_offset == 0:  # Header
            value_cell.font = Font(name='Calibri', bold=True, size=11, color='FFFFFF')
            value_cell.fill = PatternFill(start_color='74B9FF', end_color='0984E3', fill_type='solid')
        else:
            value_cell.font = Font(name='Calibri', bold=True, size=10, color='2D3436')
            # Color coding based on value
            if "%" in str(value):
                percentage_val = float(str(value).replace('%',''))
                if percentage_val >= 80:
                    value_cell.fill = PatternFill(start_color='D1F2EB', end_color='D1F2EB', fill_type='solid')
                elif percentage_val >= 60:
                    value_cell.fill = PatternFill(start_color='FDEAA7', end_color='FDEAA7', fill_type='solid')
                else:
                    value_cell.fill = PatternFill(start_color='FAB1A0', end_color='FAB1A0', fill_type='solid')
            else:
                value_cell.fill = PatternFill(start_color='F8F9FA', end_color='F8F9FA', fill_type='solid')
        value_cell.alignment = Alignment(horizontal='right', vertical='center')
        
        ws_summary.row_dimensions[row].height = 22
    
    # 🎨 Professional column widths for summary
    summary_widths = [30, 12, 20, 22, 20, 12]
    for col, width in enumerate(summary_widths, 1):
        ws_summary.column_dimensions[get_column_letter(col)].width = width
    
    # 🖼️ Advanced borders for summary
    thick_border = Side(border_style="thick", color="2B9348")
    medium_border = Side(border_style="medium", color="1E6933")
    thin_border = Side(border_style="thin", color="BDC3C7")
    
    # Logo area borders
    for row in range(1, 4):
        for col in range(1, 7):
            cell = ws_summary.cell(row=row, column=col)
            cell.border = Border(
                top=thick_border if row == 1 else thin_border,
                bottom=thick_border if row == 3 else thin_border,
                left=thick_border if col == 1 else thin_border,
                right=thick_border if col == 6 else thin_border
            )
    
    # Main table borders
    for row in range(5, current_row + 1):
        for col in range(1, 7):
            cell = ws_summary.cell(row=row, column=col)
            if row == 5:  # Headers
                cell.border = Border(top=medium_border, bottom=medium_border, left=thin_border, right=thin_border)
            elif row == current_row:  # Grand total
                cell.border = Border(top=thick_border, bottom=thick_border, left=thin_border, right=thin_border)
            else:  # Data rows
                cell.border = Border(top=thin_border, bottom=thin_border, left=thin_border, right=thin_border)
    
    # Statistics box borders
    for row in range(stats_start_row, stats_start_row + 6):
        for col in range(1, 3):
            cell = ws_summary.cell(row=row, column=col)
            cell.border = Border(top=thin_border, bottom=thin_border, left=thin_border, right=thin_border)
    
    # ❄️ Freeze panes for summary
    ws_summary.freeze_panes = 'A6'
    
    # Agar 15 kunlik xodimlar yo'q bo'lsa, birinchi sheetni o'chirish
    if not half_stats and len(wb.worksheets) > 1:
        wb.remove(wb.active)
    
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    filename = f"💰_ISOMER_OIL_Oylik_Statistika_{year}_{month:02d}_Professional.xlsx"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
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
