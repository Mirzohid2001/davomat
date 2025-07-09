from datetime import date, timedelta
from calendar import monthrange
from decimal import Decimal
from .models import Employee, Attendance, MonthlyEmployeeStat, DayOff
from django.db import transaction

def calculate_working_days_in_month(year, month):
    """Oy ichidagi ишчи кунларни ҳисоблайди (якшанбаларни ва ёпиқ кунларни чиқариб)"""
    total_days = monthrange(year, month)[1]
    start_date = date(year, month, 1)
    
    working_days = 0
    dayoffs = set(DayOff.objects.filter(
        date__year=year, 
        date__month=month
    ).values_list('date', flat=True))
    
    for day in range(1, total_days + 1):
        current_date = date(year, month, day)
        # Якшанба = 6 (Python'да)
        if current_date.weekday() != 6 and current_date not in dayoffs:
            working_days += 1
    
    return working_days, total_days

def calculate_monthly_stats(year, month):
    working_days_in_month, total_days_in_month = calculate_working_days_in_month(year, month)
    employees = Employee.objects.filter(is_active=True)
    for employee in employees:
        # Stat yozuvini olish (agar mavjud bo'lsa)
        stat = MonthlyEmployeeStat.objects.filter(employee=employee, year=year, month=month).first()
        if stat:
            salary = stat.salary
            bonus = stat.bonus
            paid = stat.paid
            manual_salary = stat.manual_salary
        else:
            salary = Decimal('1000')
            bonus = Decimal('0')
            paid = Decimal('0')
            manual_salary = (employee.employee_type == 'office')
        penalty = Decimal('0')
        
        # Ishlangan kunlar hisoblash
        worked_days = Attendance.objects.filter(
            employee=employee,
            date__year=year,
            date__month=month,
            status='present'
        ).count()
        
        # Hisoblangan summa - turi bo'yicha
        if employee.employee_type == 'office' or manual_salary:
            # Ofis xodimlari to'liq oylik oladi (davomati umuman hisobga olinmaydi)
            accrued = salary + bonus - penalty
        elif employee.employee_type == 'half':
            # 15 kunlik xodimlar har kuni ishlaydi, ularga dam olish yo'q (maksimal 15 kun)
            max_days = 15  # Har doim 15 kun
            effective_worked_days = min(worked_days, max_days)
            if max_days > 0:
                proportion = Decimal(str(effective_worked_days)) / Decimal(str(max_days))
                accrued = (salary + bonus - penalty) * proportion
            else:
                accrued = Decimal('0')
        else:
            # To'liq stavka xodimlar uchun (full) - faqat ишчи kunlarga proporsional
            # Yakshanbalar va bayramlarni hisobga olib
            if working_days_in_month > 0:
                proportion = Decimal(str(worked_days)) / Decimal(str(working_days_in_month))
                accrued = (salary + bonus - penalty) * proportion
            else:
                accrued = Decimal('0')
        
        # Oldingi oy oxiridagi qarzdorlik
        prev_stat = MonthlyEmployeeStat.objects.filter(
            employee=employee,
            year=year if month > 1 else year-1,
            month=month-1 if month > 1 else 12
        ).first()
        debt_start = prev_stat.debt_end if prev_stat else Decimal('0')
        debt_end = debt_start + accrued - paid
        
        # Stat yozuvini yaratish yoki yangilash
        with transaction.atomic():
            stat_obj, created = MonthlyEmployeeStat.objects.get_or_create(
                employee=employee, year=year, month=month,
                defaults={
                    'salary': salary,
                    'bonus': bonus,
                    'penalty': penalty,
                    'days_in_month': total_days_in_month,
                    'worked_days': worked_days,
                    'accrued': accrued,
                    'paid': paid,
                    'debt_start': debt_start,
                    'debt_end': debt_end,
                    'manual_salary': manual_salary,
                }
            )
            if not created:
                stat_obj.salary = salary
                stat_obj.bonus = bonus
                stat_obj.penalty = penalty
                stat_obj.days_in_month = total_days_in_month
                stat_obj.worked_days = worked_days
                stat_obj.accrued = accrued
                stat_obj.paid = paid
                stat_obj.debt_start = debt_start
                stat_obj.debt_end = debt_end
                stat_obj.manual_salary = manual_salary
                stat_obj.save() 