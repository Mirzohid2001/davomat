from datetime import date
from calendar import monthrange
from decimal import Decimal
from .models import Employee, Attendance, MonthlyEmployeeStat
from django.db import transaction

def calculate_monthly_stats(year, month):
    days_in_month = monthrange(year, month)[1]
    employees = Employee.objects.filter(is_active=True)
    for employee in employees:
        # Stat yozuvini olish (agar mavjud bo'lsa)
        stat = MonthlyEmployeeStat.objects.filter(employee=employee, year=year, month=month).first()
        if stat:
            salary = stat.salary
            bonus = stat.bonus
            paid = stat.paid
        else:
            salary = Decimal('1000')
            bonus = Decimal('0')
            paid = Decimal('0')
        penalty = Decimal('0')
        # Ishlangan kunlar
        worked_days = Attendance.objects.filter(
            employee=employee,
            date__year=year,
            date__month=month,
            status='present'
        ).count()
        # Hisoblangan summa (proportsional)
        if days_in_month:
            proportion = Decimal(str(worked_days)) / Decimal(str(days_in_month))
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
                    'days_in_month': days_in_month,
                    'worked_days': worked_days,
                    'accrued': accrued,
                    'paid': paid,
                    'debt_start': debt_start,
                    'debt_end': debt_end,
                }
            )
            if not created:
                stat_obj.salary = salary
                stat_obj.bonus = bonus
                stat_obj.penalty = penalty
                stat_obj.days_in_month = days_in_month
                stat_obj.worked_days = worked_days
                stat_obj.accrued = accrued
                stat_obj.paid = paid
                stat_obj.debt_start = debt_start
                stat_obj.debt_end = debt_end
                stat_obj.save() 