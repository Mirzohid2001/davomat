from datetime import date, timedelta, datetime
from calendar import monthrange
from decimal import Decimal
from django.db import transaction

from .models import Employee, Attendance, MonthlyEmployeeStat, DayOff, Team, NalivshikShiftOverride


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


def get_nalivshik_team_for_datetime(dt: datetime):
    """
    Berilgan sana/vaqt uchun qaysi komanda (1, 2 yoki 3) ishlashini hisoblaydi.

    Aylanish qoidasi (uzluksiz sikl):
    1-kun: 1-kom (kun 09:00–21:00), 2-kom (tun 21:00–09:00)
    2-kun: 3-kom (kun 09:00–21:00), 1-kom (tun 21:00–09:00)
    3-kun: 2-kom (kun 09:00–21:00), 3-kom (tun 21:00–09:00)
    va shu tartib 1-2-3 bo'lib davom etadi (kun: K[i], tun: K[i+1]).

    Bu funksiya faqat qaysi komanda ekanini qaytaradi (1/2/3).
    """
    if not isinstance(dt, datetime):
        # Agar faqat sana berilsa, uni 12:00 ga qo'yib yuboramiz
        dt = datetime.combine(dt, datetime.min.time()) + timedelta(hours=12)

    # Siklni boshlash nuqtasi (boshlanish sanasini o'zgaruvchan qilish uchun)
    # Hozircha: 2026-01-01 ni 1-kun deb qabul qilamiz
    cycle_start = datetime(2026, 1, 1, 0, 0, 0)

    # Kun boshlanishini 09:00 deb olamiz (09:00–21:00 kun, 21:00–09:00 tun)
    # Lekin komanda tanlash uchun biz faqat "smena raqami"ni hisoblaymiz.

    # Necha soat/smena o'tganini topish
    delta_hours = int((dt - cycle_start).total_seconds() // 3600)

    # Har bir smena 12 soat: [09:00–21:00], [21:00–09:00]
    shift_index = delta_hours // 12  # 0,1,2,3,...

    # 0-chi smena: 1-kun kunduz (1-kom), 1-chi smena: 1-kun tun (2-kom),
    # 2-chi smena: 2-kun kunduz (3-kom), 3-chi smena: 2-kun tun (1-kom), ...
    # Ketma-ketlik: [1, 2, 3, 1, 2, 3, ...]
    team_cycle = [1, 2, 3]
    team_code = team_cycle[shift_index % len(team_cycle)]

    # Ma'lumot uchun Team obyektini qaytarmoqchi bo'lsak, shu yerda olamiz,
    # lekin hozircha faqat raqamni qaytaramiz.
    return team_code


def get_nalivshik_teams_for_date(day: date):
    """
    Bitta sana uchun:
      - kunduzgi smena (09:00–21:00) komandasini
      - tungi smena (21:00–ertasi 09:00) komandasini
    hisoblab qaytaradi.

    Natija: (day_team_code, night_team_code) -> (1/2/3, 1/2/3)
    """
    # Avval qo'lda kiritilgan override mavjudmi, tekshiramiz
    override = NalivshikShiftOverride.objects.filter(date=day).select_related("day_team", "night_team").first()
    if override:
        day_team_code = override.day_team.code if override.day_team else None
        night_team_code = override.night_team.code if override.night_team else None
        # Agar faqat bittasi to'ldirilgan bo'lsa, qolganini avtomatik sikldan olamiz
        if day_team_code is not None and night_team_code is not None:
            return day_team_code, night_team_code

        day_start = datetime.combine(day, datetime.min.time()) + timedelta(hours=9)   # 09:00
        night_start = datetime.combine(day, datetime.min.time()) + timedelta(hours=21)  # 21:00

        auto_day = get_nalivshik_team_for_datetime(day_start)
        auto_night = get_nalivshik_team_for_datetime(night_start)

        return day_team_code or auto_day, night_team_code or auto_night

    # Override bo'lmasa, avtomatik sikl bo'yicha hisoblaymiz
    day_start = datetime.combine(day, datetime.min.time()) + timedelta(hours=9)   # 09:00
    night_start = datetime.combine(day, datetime.min.time()) + timedelta(hours=21)  # 21:00

    day_team = get_nalivshik_team_for_datetime(day_start)
    night_team = get_nalivshik_team_for_datetime(night_start)

    return day_team, night_team


def calculate_nalivshik_planned_days(year: int, month: int, employee: Employee) -> int:
    """
    Berilgan oyda ma'lum nalivshik uchun NECHTA navbatchilik kuni reja bo'yicha
    to'g'ri kelishini hisoblaydi.

    Maqsad: agar u barcha rejalashtirilgan kunlarda kelgan bo'lsa,
    oyligi 100% bo'lsin.
    """
    if not employee.team:
        return monthrange(year, month)[1]

    total_days = monthrange(year, month)[1]
    planned_days = 0
    for day_num in range(1, total_days + 1):
        current_date = date(year, month, day_num)
        day_team, night_team = get_nalivshik_teams_for_date(current_date)
        if employee.team.code in (day_team, night_team):
            planned_days += 1
    return planned_days or total_days


def generate_nalivshik_attendance_for_day(day: date):
    """
    Berilgan sana uchun nalivshiklar komanda asosida avtomatik davomat yozib beradi.

    MUHIM: Nalivshiklar uchun yakshanba va yopiq kunlar yo'q – ular
    oy davomida uzluksiz navbatchilik asosida ishlaydi. Shuning uchun
    bu funksiyada yakshanba/yopiq kunlarga qarab filtrlash qilinmaydi.

    - ROLE_CHOICES = 'nalivshik' bo'lgan xodimlarni olamiz
    - Ularning `team.code` bo'yicha:
        * kunduzgi komanda uchun `present (09:00–21:00)` deb belgilaymiz,
        * tungi komanda uchun ham `present (tun)` deb belgilashimiz mumkin.
      Hozircha Attendance modelida vaqt yo'qligi uchun, ikkala smena ham
      bitta kunga "keldi" sifatida yoziladi (keyin kerak bo'lsa kengaytiramiz).
    """

    day_team_code, night_team_code = get_nalivshik_teams_for_date(day)

    # Kun va tun komandalarini topish
    day_team = Team.objects.filter(code=day_team_code).first()
    night_team = Team.objects.filter(code=night_team_code).first()

    if not day_team and not night_team:
        # Komandalar hali yaratilmagan bo'lsa, hech narsa qilmaymiz
        return

    nalivshiks = Employee.objects.filter(is_active=True, role='nalivshik').select_related('team')

    for emp in nalivshiks:
        if not emp.team:
            continue

        if emp.team == day_team or emp.team == night_team:
            Attendance.objects.update_or_create(
                employee=emp,
                date=day,
                defaults={
                    'status': 'present',
                    'comment': "Nalivshik smena jadvali bo'yicha avtomatik",
                },
            )

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
        # Bir yildagi kelmagan kunlar chegarasi: 21 kun
        # 1-yil davomida 21 martagacha "absent" oylikka ta'sir qilmaydi.
        # Avval shu yilning hozirgi oygacha bo'lgan JAMI kelmagan kunlarni topamiz.
        from datetime import date as _date
        from calendar import monthrange as _monthrange

        year_start = _date(year, 1, 1)
        current_month_start = _date(year, month, 1)
        # Joriy oyga qadar bo'lgan (oldingi oylar) kelmaganlar
        absent_before = Attendance.objects.filter(
            employee=employee,
            date__gte=year_start,
            date__lt=current_month_start,
            status='absent'
        ).count()
        # Joriy oy ichidagi kelmaganlar
        absent_this_month = Attendance.objects.filter(
            employee=employee,
            date__year=year,
            date__month=month,
            status='absent'
        ).count()
        free_limit = 21
        free_left = max(0, free_limit - absent_before)
        forgiven_in_month = min(free_left, absent_this_month)
        # Rejada bo'lgan, lekin 21 kun kvotaga kiradigan kelmaganlar
        # ish kunlari sifatida hisoblanadi:
        effective_worked_days_for_full = worked_days + forgiven_in_month
        
        # Hisoblangan summa - turi bo'yicha
        if employee.employee_type == 'office' or manual_salary:
            # Ofis xodimlari to'liq oylik oladi (davomati umuman hisobga olinmaydi)
            # Bonus to'liq beriladi, oylik ham to'liq
            accrued = salary + bonus - penalty
        elif employee.employee_type == 'half':
            # 15 kunlik xodimlar har kuni ishlaydi, ularga dam olish yo'q (maksimal 15 kun)
            max_days = 15  # Har doim 15 kun
            effective_worked_days = min(effective_worked_days_for_full, max_days)
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
            proportion = Decimal(str(effective_worked_days_for_full)) / Decimal(str(optimal_days))
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
            proportion = Decimal(str(effective_worked_days_for_full)) / Decimal(str(optimal_days))
            # Agar xodim kerakli kundan ko'p ishlasa, to'liq stavka berish
            if proportion > Decimal('1'):
                proportion = Decimal('1')
            # Oylik proporsional hisoblanadi, bonus to'liq beriladi
            accrued_salary = salary * proportion
            accrued = accrued_salary + bonus - penalty
        else:
            # To'liq stavka xodimlar uchun (full)
            # Oddiy xodimlar uchun ishchi kunlarga proporsional,
            # nalivshiklar uchun esa o'z navbatchilik rejasi (komandaga to'g'ri keladigan kunlar)
            # bo'yicha proporsional hisoblaymiz.
            if employee.role == 'nalivshik':
                denominator_days = calculate_nalivshik_planned_days(year, month, employee)
            else:
                denominator_days = working_days_in_month

            if denominator_days > 0:
                salary_proportion = Decimal(str(effective_worked_days_for_full)) / Decimal(str(denominator_days))
                # Agar worked_days kunlardan ko'p bo'lsa,
                # stavka 100% dan oshib ketmasligi uchun 1 bilan cheklaymiz.
                if salary_proportion > Decimal('1'):
                    salary_proportion = Decimal('1')
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