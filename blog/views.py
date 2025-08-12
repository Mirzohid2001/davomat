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
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.styles.differential import DifferentialStyle
    from openpyxl.formatting.rule import Rule
    from openpyxl.utils import get_column_letter
    
    today = datetime.date.today()
    year = int(request.GET.get('year', today.year))
    month = int(request.GET.get('month', today.month))
    calculate_monthly_stats(year, month)
    stats = MonthlyEmployeeStat.objects.filter(year=year, month=month).select_related('employee')
    
    # Excel faylini yaratish
    wb = Workbook()
    
    # Ishchi kunlarni hisoblash
    working_days_in_month, total_days_in_month = calculate_working_days_in_month(year, month)
    
    # Ishchi kunlar har bir stat obyektiga biriktiriladi
    for stat in stats:
        stat.working_days_in_month = working_days_in_month

    # Xodimlarni turlariga qarab guruhlash
    half_stats = [s for s in stats if s.employee.employee_type == 'half']
    full_stats = [s for s in stats if s.employee.employee_type == 'full']
    office_stats = [s for s in stats if s.employee.employee_type == 'office']
    weekly_stats = [s for s in stats if s.employee.employee_type == 'weekly']
    guard_stats = [s for s in stats if s.employee.employee_type == 'guard']
    
    # Chegara va ramkalar stili
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    header_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='medium')
    )
    
    # Sodda va toza worksheet yaratish funksiyasi
    def create_worksheet(worksheet, title, data, color_bg='4A90E2', color_accent='2E5C8A'):
        # Sodda sarlavha
        worksheet.merge_cells('A1:H2')
        title_cell = worksheet.cell(row=1, column=1)
        title_cell.value = f"ISOMER OIL - {title} ({year}-{month:02d})"
        title_cell.font = Font(name='Arial', bold=True, size=14, color='FFFFFF')
        title_cell.alignment = Alignment(horizontal='center', vertical='center')
        title_cell.fill = PatternFill(start_color=color_bg, end_color=color_bg, fill_type='solid')
        
        # Sarlavha uchun oddiy ramka
        for col in range(1, 9):
            for row in range(1, 3):
                cell = worksheet.cell(row=row, column=col)
                cell.fill = PatternFill(start_color=color_bg, end_color=color_bg, fill_type='solid')
                cell.border = Border(
                    left=Side(style='thin', color='000000'),
                    right=Side(style='thin', color='000000'),
                    top=Side(style='thin', color='000000'),
                    bottom=Side(style='thin', color='000000')
                )
        
        # Sodda sarlavhalar
        headers = [
            "Xodim", "Oylik", "Valyuta", "Kelgan/Jami", 
            "Foiz", "Hisoblangan", "To'langan", "Bonus"
        ]
        
        for col, header in enumerate(headers, 1):
            cell = worksheet.cell(row=4, column=col)
            cell.value = header
            cell.font = Font(name='Arial', bold=True, size=11, color='000000')
            cell.fill = PatternFill(start_color='E8E8E8', end_color='E8E8E8', fill_type='solid')
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border = Border(
                left=Side(style='thin', color='000000'),
                right=Side(style='thin', color='000000'),
                top=Side(style='thin', color='000000'),
                bottom=Side(style='thin', color='000000')
            )
        
        # Sodda ma'lumotlar
        for row, stat in enumerate(data, 5):
            # Kelish foizini hisoblash
            if hasattr(stat, 'working_days_in_month') and stat.working_days_in_month > 0:
                percentage = (stat.worked_days / stat.working_days_in_month) * 100
            else:
                percentage = 0
                
            # Ma'lumotlarni formatlash
            row_data = [
                f"{stat.employee.last_name} {stat.employee.first_name}",
                float(stat.salary),
                stat.currency.upper() if stat.currency else 'UZS',
                f"{stat.worked_days}/{stat.working_days_in_month}",
                f"{percentage:.1f}%",
                float(stat.accrued),
                float(stat.paid),
                float(stat.bonus) if stat.bonus else 0
            ]
            
            for col, value in enumerate(row_data, 1):
                cell = worksheet.cell(row=row, column=col)
                cell.value = value
                
                # Oddiy ramka
                cell.border = Border(
                    left=Side(style='thin', color='000000'),
                    right=Side(style='thin', color='000000'),
                    top=Side(style='thin', color='000000'),
                    bottom=Side(style='thin', color='000000')
                )
                
                # Sodda stillar
                if col == 1:  # Ism
                    cell.font = Font(name='Arial', size=10)
                    cell.alignment = Alignment(horizontal='left', vertical='center')
                elif col == 3:  # Valyuta
                    cell.font = Font(name='Arial', bold=True, size=10)
                    cell.alignment = Alignment(horizontal='center', vertical='center')
                elif col == 4:  # Kelgan/Jami
                    cell.font = Font(name='Arial', size=10)
                    cell.alignment = Alignment(horizontal='center', vertical='center')
                elif col == 5:  # Foiz
                    cell.font = Font(name='Arial', bold=True, size=10)
                    cell.alignment = Alignment(horizontal='center', vertical='center')
                    # Foiz uchun oddiy rang berish
                    if percentage >= 80:
                        cell.fill = PatternFill(start_color='E8F5E8', end_color='E8F5E8', fill_type='solid')
                    elif percentage >= 60:
                        cell.fill = PatternFill(start_color='FFF8DC', end_color='FFF8DC', fill_type='solid')
                    else:
                        cell.fill = PatternFill(start_color='FFE4E1', end_color='FFE4E1', fill_type='solid')
                elif col in [2, 6, 7, 8]:  # Pul ustunlari
                    cell.font = Font(name='Arial', size=10)
                    cell.alignment = Alignment(horizontal='right', vertical='center')
                    
                    # Oddiy raqam formati
                    currency = stat.currency.upper() if stat.currency else 'UZS'
                    if currency == 'USD':
                        cell.number_format = '"$" #,##0'
                    elif currency in ['UZS', 'SUM']:
                        cell.number_format = '#,##0 "so\'m"'
                    else:
                        cell.number_format = f'#,##0 "{currency}"'
        
        # Oddiy ustun kengliklari
        column_widths = [25, 15, 10, 15, 12, 18, 15, 12]
        for col, width in enumerate(column_widths, 1):
            column_letter = get_column_letter(col)
            worksheet.column_dimensions[column_letter].width = width
        
        # Oddiy zebra chiziqlar
        data_end_row = worksheet.max_row
        for row in range(5, data_end_row + 1):
            if row % 2 == 0:  # Juft qatorlar
                for col in range(1, 9):
                    cell = worksheet.cell(row=row, column=col)
                    if not cell.fill or cell.fill.start_color.rgb == '00000000':  # Agar rang berilmagan bo'lsa
                        cell.fill = PatternFill(start_color='F8F8F8', end_color='F8F8F8', fill_type='solid')
        
        # Sodda valyuta umumiy hisob-kitobi
        if data:
            # Valyutalar bo'yicha guruhlash
            currency_totals = {}
            for stat in data:
                currency = stat.currency.upper() if stat.currency else 'UZS'
                if currency not in currency_totals:
                    currency_totals[currency] = {'count': 0, 'salary': 0, 'accrued': 0, 'paid': 0, 'bonus': 0}
                
                currency_totals[currency]['count'] += 1
                currency_totals[currency]['salary'] += float(stat.salary)
                currency_totals[currency]['accrued'] += float(stat.accrued)
                currency_totals[currency]['paid'] += float(stat.paid)
                currency_totals[currency]['bonus'] += float(stat.bonus) if stat.bonus else 0
            
            # Umumiy ma'lumotlar sarlavhasi
            summary_start_row = data_end_row + 2
            worksheet.merge_cells(f'A{summary_start_row}:H{summary_start_row}')
            summary_header = worksheet.cell(row=summary_start_row, column=1)
            summary_header.value = "VALYUTA BO'YICHA JAMI"
            summary_header.font = Font(name='Arial', bold=True, size=12, color='FFFFFF')
            summary_header.fill = PatternFill(start_color=color_bg, end_color=color_bg, fill_type='solid')
            summary_header.alignment = Alignment(horizontal='center', vertical='center')
            summary_header.border = Border(
                left=Side(style='thin', color='000000'),
                right=Side(style='thin', color='000000'),
                top=Side(style='thin', color='000000'),
                bottom=Side(style='thin', color='000000')
            )
            
            # Valyuta sarlavhalari
            headers = ["Valyuta", "Soni", "Jami oylik", "Hisoblangan", "To'langan", "Bonus", "Qarzdorlik", ""]
            
            header_row = summary_start_row + 1
            for col, header in enumerate(headers, 1):
                cell = worksheet.cell(row=header_row, column=col)
                cell.value = header
                cell.font = Font(name='Arial', bold=True, size=10, color='000000')
                cell.fill = PatternFill(start_color='D0D0D0', end_color='D0D0D0', fill_type='solid')
                cell.alignment = Alignment(horizontal='center', vertical='center')
                cell.border = Border(
                    left=Side(style='thin', color='000000'),
                    right=Side(style='thin', color='000000'),
                    top=Side(style='thin', color='000000'),
                    bottom=Side(style='thin', color='000000')
                )
            
            # Har bir valyuta uchun ma'lumotlar
            current_row = header_row + 1
            for currency, totals in sorted(currency_totals.items()):
                debt_amount = totals['accrued'] - totals['paid']
                
                currency_data = [
                    currency, totals['count'], totals['salary'], totals['accrued'],
                    totals['paid'], totals['bonus'], debt_amount, ""
                ]
                
                for col, value in enumerate(currency_data, 1):
                    cell = worksheet.cell(row=current_row, column=col)
                    cell.value = value
                    cell.font = Font(name='Arial', size=10)
                    cell.alignment = Alignment(
                        horizontal='center' if col in [1, 2] else 'right' if col <= 7 else 'left', 
                        vertical='center'
                    )
                    cell.border = Border(
                        left=Side(style='thin', color='000000'),
                        right=Side(style='thin', color='000000'),
                        top=Side(style='thin', color='000000'),
                        bottom=Side(style='thin', color='000000')
                    )
                    
                    # Pul ustunlari uchun formatlash
                    if col in [3, 4, 5, 6, 7] and isinstance(value, (int, float)):
                        if currency == 'USD':
                            cell.number_format = '"$" #,##0'
                        elif currency in ['UZS', 'SUM']:
                            cell.number_format = '#,##0 "so\'m"'
                        else:
                            cell.number_format = f'#,##0 "{currency}"'
                
                current_row += 1
        
        # ❄️ Freeze panes
        worksheet.freeze_panes = 'A5'
    
    # Xodim turlariga qarab worksheetlar yaratish
    # Avval default worksheet o'chirish
    wb.remove(wb.active)
    
    # Kerakli worksheetlarni tartib bilan yaratish
    worksheets_to_create = []
    
    # 1. Umumiy ma'lumot (birinchi bo'lsin)
    non_office_stats = [s for s in stats if s.employee.employee_type != 'office']
    if non_office_stats:
        worksheets_to_create.append(("Umumiy", "Umumiy ma'lumot", non_office_stats, '4A90E2', '2E5C8A'))
    
    # 2. Xodim turlari bo'yicha
    if full_stats:
        worksheets_to_create.append(("To'liq stavka", "To'liq stavka xodimlar", full_stats, '3D5A80', '293241'))
    
    if half_stats:
        worksheets_to_create.append(("15 kunlik", "15 kunlik xodimlar", half_stats, 'FF6B35', 'E55D2B'))
    
    if weekly_stats:
        worksheets_to_create.append(("Haftada 1 kun", "Haftada 1 kun xodimlar", weekly_stats, '6C757D', '495057'))
    
    if guard_stats:
        worksheets_to_create.append(("Qorovul", "Qorovul xodimlar", guard_stats, 'DC3545', 'C82333'))
    
    if office_stats:
        worksheets_to_create.append(("Ofis", "Ofis xodimlari", office_stats, '7209B7', '560BAD'))
    
    # Worksheetlarni yaratish
    for i, (sheet_name, title, data, bg_color, accent_color) in enumerate(worksheets_to_create):
        if i == 0:
            # Birinchi worksheet uchun yangi active sheet yaratish
            ws = wb.create_sheet(sheet_name)
            wb.active = ws
        else:
            ws = wb.create_sheet(sheet_name)
        
        create_worksheet(ws, title, data, bg_color, accent_color)
    
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
