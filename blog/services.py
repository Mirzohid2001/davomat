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

def update_future_months_salary(employee, new_salary, new_currency, current_year, current_month):
    """Oylik o'zgartirilganda keyingi oylarga yangi oylikni o'tkazish"""
    from datetime import date
    from calendar import monthrange
    
    # Keyingi oylarni topish
    next_month = current_month + 1
    next_year = current_year
    
    if next_month > 12:
        next_month = 1
        next_year += 1
    
    # Hozirgi sanadan keyingi barcha oylarni yangilash
    current_date = date(next_year, next_month, 1)
    today = date.today()
    
    # Keyingi 12 oyga qarab tekshirish
    for i in range(12):
        check_year = current_date.year
        check_month = current_date.month
        
        # Bu oy uchun stat mavjudmi?
        future_stat = MonthlyEmployeeStat.objects.filter(
            employee=employee,
            year=check_year,
            month=check_month
        ).first()
        
        if future_stat:
            # Agar bu oy uchun stat mavjud bo'lsa, oylik va valyutani yangilash
            future_stat.salary = new_salary
            future_stat.currency = new_currency
            future_stat.save()
        
        # Keyingi oyga o'tish
        if current_date.month == 12:
            current_date = current_date.replace(year=current_date.year + 1, month=1)
        else:
            current_date = current_date.replace(month=current_date.month + 1)
        
        # Agar kelajakdagi sana hozirgi sanadan katta bo'lsa, to'xtash
        if current_date > today.replace(day=1):
            break

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
            currency = stat.currency
        else:
            # Oldingi oyning ma'lumotlarini olish
            prev_stat = MonthlyEmployeeStat.objects.filter(
                employee=employee,
                year=year if month > 1 else year-1,
                month=month-1 if month > 1 else 12
            ).first()
            
            # Agar oldingi oy ma'lumoti mavjud bo'lsa, undan oylikni va valyutani olish
            if prev_stat:
                salary = prev_stat.salary
                bonus = Decimal('0')  # Yangi oy uchun bonus 0 dan boshlanadi
                currency = prev_stat.currency  # Valyutani ham oldingi oydan olish
            else:
                salary = Decimal('1000')  # Faqat birinchi marta
                bonus = Decimal('0')
                currency = 'UZS'  # Birinchi marta uchun default valyuta
            
            paid = Decimal('0')
            manual_salary = (employee.employee_type == 'office')
        penalty = Decimal('0')
        
        # Ishlangan kunlar hisoblash (kelganlar VA kasal bo'lganlar)
        worked_days = Attendance.objects.filter(
            employee=employee,
            date__year=year,
            date__month=month,
            status__in=['present', 'sick']
        ).count()
        
        # Hisoblangan summa - turi bo'yicha
        if employee.employee_type == 'office' or manual_salary:
            # Ofis xodimlari to'liq oylik oladi (davomati umuman hisobga olinmaydi)
            # Bonus to'liq beriladi, oylik ham to'liq
            accrued = salary + bonus - penalty
        elif employee.employee_type == 'half':
            # 15 kunlik xodimlar har kuni ishlaydi, ularga dam olish yo'q (maksimal 15 kun)
            max_days = 15  # Har doim 15 kun
            effective_worked_days = min(worked_days, max_days)
            if max_days > 0:
                # Oylik proporsional hisoblanadi, bonus to'liq beriladi
                salary_proportion = Decimal(str(effective_worked_days)) / Decimal(str(max_days))
                accrued_salary = salary * salary_proportion
                accrued = accrued_salary + bonus - penalty
            else:
                accrued = bonus - penalty  # Faqat bonus
        elif employee.employee_type == 'weekly':
            # Haftada 1 kun ishlaydigan xodimlar (to'liq stavka)
            # Optimal holat: oyda 4 kun
            optimal_days = 4  # Bir oyda taxminan 4 hafta
            # Ishlagan kunlarni optimal kunlarga proporsional hisoblash
            proportion = Decimal(str(worked_days)) / Decimal(str(optimal_days))
            # Agar xodim kerakli kundan ko'p ishlasa, to'liq stavka berish
            if proportion > Decimal('1'):
                proportion = Decimal('1')
            # Oylik proporsional hisoblanadi, bonus to'liq beriladi
            accrued_salary = salary * proportion
            accrued = accrued_salary + bonus - penalty
        elif employee.employee_type == 'guard':
            # Qorovullar (oyda 10 kun ishlashi optimal)
            optimal_days = 10
            # Ishlagan kunlarni optimal kunlarga proporsional hisoblash
            proportion = Decimal(str(worked_days)) / Decimal(str(optimal_days))
            # Agar xodim kerakli kundan ko'p ishlasa, to'liq stavka berish
            if proportion > Decimal('1'):
                proportion = Decimal('1')
            # Oylik proporsional hisoblanadi, bonus to'liq beriladi
            accrued_salary = salary * proportion
            accrued = accrued_salary + bonus - penalty
        else:
            # To'liq stavka xodimlar uchun (full) - faqat ишчи kunlarga proporsional
            # Yakshanbalar va bayramlarni hisobga olib
            if working_days_in_month > 0:
                # Oylik proporsional hisoblanadi, bonus to'liq beriladi
                salary_proportion = Decimal(str(worked_days)) / Decimal(str(working_days_in_month))
                accrued_salary = salary * salary_proportion
                accrued = accrued_salary + bonus - penalty
            else:
                accrued = bonus - penalty  # Faqat bonus
        
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
                    'currency': currency,
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
                stat_obj.currency = currency
                stat_obj.save() 