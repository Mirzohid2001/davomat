from datetime import date, timedelta, datetime
from calendar import monthrange
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.utils import timezone

from .models import Employee, Attendance, MonthlyEmployeeStat, DayOff, Team, NalivshikShiftOverride, MonthlyProduction, SalaryPayment


# Oylik hisobda ishlangan kun sifatida qabul qilinadigan davomat holatlari
WORKED_DAY_STATUSES = ('present', 'sick', 'late')

# Yillik ruxsat etilgan kelmagan kunlar (oylik hisob va kvota sahifasi)
YEARLY_ABSENCE_FREE_LIMIT = 21

# Ishlab chiqarish premiyasi (benzin, tonna → so'm)
PRODUCTION_BONUS_LOW_MIN_TONS = Decimal('1500')       # kamida shuncha — premiya boshlanadi
PRODUCTION_BONUS_HIGH_THRESHOLD_TONS = Decimal('3000')  # undan yuqori → 4.8 mln
PRODUCTION_BONUS_UP_TO_THRESHOLD = Decimal('2400000')   # 1500–3000 t
PRODUCTION_BONUS_ABOVE_THRESHOLD = Decimal('4800000')   # 3000 t dan yuqori


def production_bonus_amount_for_tons(production_tons):
    """
    1500–3000 t → 2.4 mln. 3000 t dan yuqori → 4.8 mln.
    1500 t dan kam — premiya yo'q.
    """
    tons = Decimal(str(production_tons))
    if tons < PRODUCTION_BONUS_LOW_MIN_TONS:
        return None
    if tons <= PRODUCTION_BONUS_HIGH_THRESHOLD_TONS:
        return PRODUCTION_BONUS_UP_TO_THRESHOLD
    return PRODUCTION_BONUS_ABOVE_THRESHOLD


def get_monthly_production_record(year: int, month: int):
    return MonthlyProduction.objects.filter(year=year, month=month).first()


def is_production_bonus_eligible_for_month(employee, year: int, month: int) -> bool:
    record = get_monthly_production_record(year, month)
    if not record:
        return False
    return record.eligible_employees.filter(pk=employee.pk).exists()


def get_production_bonus_eligible_ids(year: int, month: int) -> set:
    record = get_monthly_production_record(year, month)
    if not record:
        return set()
    return set(record.eligible_employees.values_list('id', flat=True))


def resolve_production_bonus(employee, year: int, month: int, currency: str, current_bonus, bonus_override: bool):
    """
    Ishlab chiqarish premiyasini qaytaradi yoki None (qo'lda saqlash kerak).
    Faqat UZS valyutadagi, shu oy ro'yxatiga kiritilgan xodimlar uchun.
    """
    if bonus_override or currency != 'UZS':
        return None
    record = get_monthly_production_record(year, month)
    if not record:
        return None
    if not record.eligible_employees.filter(pk=employee.pk).exists():
        return None
    return production_bonus_amount_for_tons(record.production_tons)


def save_production_bonus_settings(year: int, month: int, production_tons, eligible_employee_ids):
    """Oylik ishlab chiqarish va premiya oluvchi xodimlarni saqlaydi, mukofotlarni yangilaydi."""
    tons = Decimal(str(production_tons or 0))
    eligible_ids = {int(pk) for pk in eligible_employee_ids}
    if not eligible_ids:
        return

    if tons >= PRODUCTION_BONUS_LOW_MIN_TONS:
        record, _ = MonthlyProduction.objects.update_or_create(
            year=year,
            month=month,
            defaults={'production_tons': tons},
        )
        if record.production_tons != tons:
            record.production_tons = tons
            record.save(update_fields=['production_tons'])
        record.eligible_employees.set(
            Employee.objects.filter(id__in=eligible_ids, is_active=True)
        )
    else:
        MonthlyProduction.objects.filter(year=year, month=month).delete()

    MonthlyEmployeeStat.objects.filter(
        year=year,
        month=month,
        bonus_override=False,
    ).exclude(employee_id__in=eligible_ids).update(bonus=Decimal('0'))

    if tons >= PRODUCTION_BONUS_LOW_MIN_TONS:
        MonthlyEmployeeStat.objects.filter(
            year=year,
            month=month,
            employee_id__in=eligible_ids,
        ).update(bonus_override=False)

    calculate_monthly_stats(year, month)


def remove_production_bonus_for_employees(year: int, month: int, employee_ids) -> int:
    """Faqat tanlangan xodimlardan shu oy uchun ishlab chiqarish premiyasini olib tashlaydi."""
    ids = {int(pk) for pk in employee_ids}
    if not ids:
        return 0

    record = get_monthly_production_record(year, month)
    if record:
        record.eligible_employees.remove(*Employee.objects.filter(id__in=ids))

    MonthlyEmployeeStat.objects.filter(
        year=year,
        month=month,
        employee_id__in=ids,
        bonus_override=False,
    ).update(bonus=Decimal('0'))

    calculate_monthly_stats(year, month)
    return len(ids)


def clear_production_bonus_for_month(year: int, month: int):
    """Shu oy uchun barcha ishlab chiqarish premiyalarini bekor qiladi."""
    MonthlyProduction.objects.filter(year=year, month=month).delete()
    MonthlyEmployeeStat.objects.filter(
        year=year,
        month=month,
        bonus_override=False,
    ).update(bonus=Decimal('0'))
    calculate_monthly_stats(year, month)


def is_auto_production_bonus(amount) -> bool:
    return Decimal(str(amount or 0)) in (
        PRODUCTION_BONUS_UP_TO_THRESHOLD,
        PRODUCTION_BONUS_ABOVE_THRESHOLD,
    )

VALID_ATTENDANCE_STATUSES = {choice[0] for choice in Attendance.STATUS_CHOICES}
ATTENDANCE_STATUS_LABELS = {choice[1].lower(): choice[0] for choice in Attendance.STATUS_CHOICES}


def normalize_attendance_status(raw_status) -> str:
    """Import va API uchun statusni tekshiradi va kodga aylantiradi."""
    if raw_status is None:
        raise ValueError("Status bo'sh")
    status = str(raw_status).strip()
    if not status or status.lower() == "nan":
        raise ValueError("Status bo'sh")
    code = status.lower()
    if code in VALID_ATTENDANCE_STATUSES:
        return code
    label_match = ATTENDANCE_STATUS_LABELS.get(status.lower())
    if label_match:
        return label_match
    allowed = ", ".join(sorted(VALID_ATTENDANCE_STATUSES))
    raise ValueError(f"Noto'g'ri status: {raw_status}. Qabul qilinadi: {allowed}")


def get_absence_quota_for_period(employee, year: int, month: int | None = None) -> dict:
    """
    Oylik hisobdagi 21 kun kvota formulasi bilan bir xil natija.
    month berilmasa: joriy yil uchun bugungi oy, o'tgan yillar uchun dekabr.
    """
    today = date.today()
    if month is None:
        month = today.month if year == today.year else 12

    year_start = date(year, 1, 1)
    month_start = date(year, month, 1)

    absent_before = Attendance.objects.filter(
        employee=employee,
        date__gte=year_start,
        date__lt=month_start,
        status='absent',
    ).count()
    absent_this_month = Attendance.objects.filter(
        employee=employee,
        date__year=year,
        date__month=month,
        status='absent',
    ).count()
    absent_ytd = absent_before + absent_this_month
    free_left = max(0, YEARLY_ABSENCE_FREE_LIMIT - absent_before)
    forgiven_in_month = min(free_left, absent_this_month)
    affects_salary = absent_this_month - forgiven_in_month
    used = min(absent_ytd, YEARLY_ABSENCE_FREE_LIMIT)
    left = max(0, YEARLY_ABSENCE_FREE_LIMIT - used)
    over = max(0, absent_ytd - YEARLY_ABSENCE_FREE_LIMIT)

    return {
        'year': year,
        'month': month,
        'absent_before': absent_before,
        'absent_this_month': absent_this_month,
        'absent_ytd': absent_ytd,
        'forgiven_in_month': forgiven_in_month,
        'affects_salary': affects_salary,
        'used': used,
        'left': left,
        'over': over,
    }


def round_money(amount, currency: str) -> Decimal:
    """UZS uchun butun so'm, boshqa valyutalar uchun 2 xona."""
    amount = Decimal(str(amount or 0))
    if currency in ("UZS", "SUM"):
        return amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_debt_end(debt_start, accrued, paid, currency: str) -> Decimal:
    """
    Qarzdorlik oxirini hisoblaydi.
    Musbat — kompaniya xodimga qarzdor; manfiy — xodim ortiqcha olgan (avans).
    """
    debt_start = round_money(debt_start, currency)
    accrued = round_money(accrued, currency)
    paid = round_money(paid, currency)
    return round_money(debt_start + accrued - paid, currency)


def is_restricted_attendance_date(for_date: date) -> bool:
    """Yakshanba yoki yopiq kun (nalivshiklar bundan mustasno ishlaydi)."""
    if for_date.weekday() == 6:
        return True
    return DayOff.objects.filter(date=for_date).exists()


def get_restricted_day_reason(for_date: date) -> str:
    if for_date.weekday() == 6:
        return "Yakshanba"
    dayoff = DayOff.objects.filter(date=for_date).first()
    return dayoff.reason if dayoff else "Yopiq kun"


def employee_can_attend_on_date(employee, for_date: date) -> bool:
    """Oddiy xodimlar yakshanba/yopiq kunda davomat kirita olmaydi."""
    if not is_restricted_attendance_date(for_date):
        return True
    return getattr(employee, "role", None) == "nalivshik"


def get_bulk_attendance_employees(for_date: date):
    """
    Ommaviy davomat uchun xodimlar.
    Yakshanba va yopiq kunlarda faqat nalivshiklar ishlaydi.
    Qaytadi: (queryset, restricted_day bool)
    """
    active = Employee.objects.filter(is_active=True)
    restricted = is_restricted_attendance_date(for_date)
    if restricted:
        return active.filter(role='nalivshik'), True
    return active, False


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
            # Mavjud yozuvni (qo'lda absent/sick va h.k.) ustiga yozmaymiz
            Attendance.objects.get_or_create(
                employee=emp,
                date=day,
                defaults={
                    'status': 'present',
                    'comment': "Nalivshik smena jadvali bo'yicha avtomatik",
                },
            )

def create_initial_attendance_for_new_employee(employee: Employee, hire_date: date, worked_days_count: int):
    """
    Yangi xodim qo'shilganda ishga kirgan sanadan boshlab
    kelgan kunlar uchun 'present' davomat yozuvlarini yaratadi.
    """
    if worked_days_count <= 0:
        return 0

    year, month = hire_date.year, hire_date.month
    total_days = monthrange(year, month)[1]
    dayoffs = set(
        DayOff.objects.filter(date__year=year, date__month=month).values_list("date", flat=True)
    )

    created = 0
    for day in range(hire_date.day, total_days + 1):
        if created >= worked_days_count:
            break
        current_date = date(year, month, day)
        if employee.role != "nalivshik":
            if current_date.weekday() == 6 or current_date in dayoffs:
                continue
        Attendance.objects.update_or_create(
            employee=employee,
            date=current_date,
            defaults={
                "status": "present",
                "comment": "Yangi xodim qo'shilganda kiritilgan kelgan kun",
            },
        )
        created += 1
    return created


def ensure_initial_monthly_stat(employee: Employee, hire_date: date):
    """Yangi xodim uchun boshlang'ich oylik statistikasi (oylik = 0)."""
    year, month = hire_date.year, hire_date.month
    working_days, total_days = calculate_working_days_in_month(year, month)
    MonthlyEmployeeStat.objects.get_or_create(
        employee=employee,
        year=year,
        month=month,
        defaults={
            "salary": Decimal("0"),
            "bonus": Decimal("0"),
            "penalty": Decimal("0"),
            "days_in_month": total_days,
            "worked_days": 0,
            "accrued": Decimal("0"),
            "paid": Decimal("0"),
            "debt_start": Decimal("0"),
            "debt_end": Decimal("0"),
            "currency": "UZS",
            "manual_salary": employee.employee_type == "office",
        },
    )


def get_previous_month_stat(employee, year: int, month: int):
    if month > 1:
        prev_year, prev_month = year, month - 1
    else:
        prev_year, prev_month = year - 1, 12
    return MonthlyEmployeeStat.objects.filter(
        employee=employee,
        year=prev_year,
        month=prev_month,
    ).first()


def sync_salary_from_previous_month(year: int, month: int, employee=None):
    """Qo'lda belgilanmagan oyliklarni avvalgi oydan sinxronlaydi."""
    stats = MonthlyEmployeeStat.objects.filter(
        year=year,
        month=month,
        employee__is_active=True,
        salary_override=False,
    )
    if employee is not None:
        stats = stats.filter(employee=employee)

    for stat in stats.select_related('employee'):
        prev_stat = get_previous_month_stat(stat.employee, year, month)
        if not prev_stat:
            continue
        if stat.salary == prev_stat.salary and stat.currency == prev_stat.currency:
            continue
        stat.salary = prev_stat.salary
        stat.currency = prev_stat.currency
        stat.save(update_fields=['salary', 'currency'])
        calculate_monthly_stats(year, month, employee=stat.employee)


def update_future_months_salary(employee, new_salary, new_currency, current_year, current_month):
    """Oylik o'zgartirilganda keyingi oylarga yangi oylikni o'tkazish"""
    # Keyingi oylarni topish
    next_month = current_month + 1
    next_year = current_year
    
    if next_month > 12:
        next_month = 1
        next_year += 1
    
    current_date = date(next_year, next_month, 1)

    # Keyingi 12 oyga yangi oylikni ko'chirish
    for i in range(12):
        check_year = current_date.year
        check_month = current_date.month

        future_stat = MonthlyEmployeeStat.objects.filter(
            employee=employee,
            year=check_year,
            month=check_month,
        ).first()

        if future_stat:
            if future_stat.salary_override:
                pass
            else:
                future_stat.salary = new_salary
                future_stat.currency = new_currency
                future_stat.save(update_fields=['salary', 'currency'])
                calculate_monthly_stats(
                    check_year, check_month, employee=employee, preserve_salary=True
                )
        else:
            calculate_monthly_stats(check_year, check_month, employee=employee)
            future_stat = MonthlyEmployeeStat.objects.filter(
                employee=employee,
                year=check_year,
                month=check_month,
            ).first()
            if future_stat and not future_stat.salary_override:
                if future_stat.salary != new_salary or future_stat.currency != new_currency:
                    future_stat.salary = new_salary
                    future_stat.currency = new_currency
                    future_stat.save(update_fields=['salary', 'currency'])
                    calculate_monthly_stats(
                        check_year, check_month, employee=employee, preserve_salary=True
                    )

        # Keyingi oyga o'tish
        if current_date.month == 12:
            current_date = current_date.replace(year=current_date.year + 1, month=1)
        else:
            current_date = current_date.replace(month=current_date.month + 1)


def sync_stat_paid_from_payments(stat: MonthlyEmployeeStat):
    """To'lovlar jadvalidan jami summa va oxirgi sanani statistikaga yozadi."""
    from django.db.models import Sum

    total = stat.salary_payments.aggregate(total=Sum('amount'))['total'] or Decimal('0')
    stat.paid = round_money(total, stat.currency)
    latest = stat.salary_payments.order_by('-paid_at', '-pk').first()
    stat.paid_at = latest.paid_at if latest else None
    stat.save(update_fields=['paid', 'paid_at'])


def apply_salary_payment_changes(stat, delete_ids, new_amount=None, new_date=None, note=''):
    """To'lovlarni qo'shish/o'chirish va statistikani sinxronlash."""
    if delete_ids:
        stat.salary_payments.filter(pk__in=delete_ids).delete()
    if new_amount is not None and new_amount > 0 and new_date is not None:
        SalaryPayment.objects.create(
            stat=stat,
            amount=round_money(new_amount, stat.currency),
            paid_at=new_date,
            note=(note or '').strip(),
        )
    sync_stat_paid_from_payments(stat)


def calculate_monthly_stats(year, month, employee=None, preserve_salary=False):
    """
    Oylik statistikani hisoblaydi.
    employee berilsa — faqat shu xodim (modal saqlash uchun tez).
    preserve_salary=True — oylikni DB dagi qiymatda qoldiradi (keyingi oyga ko'chirishda).
    """
    working_days_in_month, total_days_in_month = calculate_working_days_in_month(year, month)
    employees = Employee.objects.filter(is_active=True)
    if employee is not None:
        employees = employees.filter(pk=employee.pk)
    for employee in employees:
        # Stat yozuvini olish (agar mavjud bo'lsa)
        stat = MonthlyEmployeeStat.objects.filter(employee=employee, year=year, month=month).first()
        if stat:
            bonus = stat.bonus
            bonus_override = stat.bonus_override
            penalty = stat.penalty
            manual_salary = stat.manual_salary
            if stat.salary_override or preserve_salary:
                salary = stat.salary
                currency = stat.currency
            else:
                prev_stat = get_previous_month_stat(employee, year, month)
                if prev_stat:
                    salary = prev_stat.salary
                    currency = prev_stat.currency
                else:
                    salary = stat.salary
                    currency = stat.currency
            if stat.salary_payments.exists():
                sync_stat_paid_from_payments(stat)
                stat.refresh_from_db()
            paid = stat.paid
            paid_at = stat.paid_at
        else:
            # Oldingi oyning ma'lumotlarini olish
            prev_stat = get_previous_month_stat(employee, year, month)
            
            # Agar oldingi oy ma'lumoti mavjud bo'lsa, undan oylikni va valyutani olish
            if prev_stat:
                salary = prev_stat.salary
                bonus = Decimal('0')  # Yangi oy uchun bonus 0 dan boshlanadi
                currency = prev_stat.currency  # Valyutani ham oldingi oydan olish
            else:
                salary = Decimal('0')  # Yangi xodim — oylikni keyin qo'lda kiritasiz
                bonus = Decimal('0')
                currency = 'UZS'  # Birinchi marta uchun default valyuta
            
            paid = Decimal('0')
            paid_at = None
            manual_salary = (employee.employee_type == 'office')
            penalty = Decimal('0')
            bonus_override = False

        eligible_this_month = is_production_bonus_eligible_for_month(employee, year, month)
        if eligible_this_month and currency == 'UZS' and not bonus_override:
            production_bonus = resolve_production_bonus(
                employee, year, month, currency, bonus, bonus_override
            )
            bonus = production_bonus if production_bonus is not None else Decimal('0')
        elif not bonus_override and not eligible_this_month:
            if is_auto_production_bonus(bonus):
                bonus = Decimal('0')

        # Ishlangan kunlar hisoblash
        worked_days = Attendance.objects.filter(
            employee=employee,
            date__year=year,
            date__month=month,
            status__in=WORKED_DAY_STATUSES,
        ).count()
        quota = get_absence_quota_for_period(employee, year, month)
        forgiven_in_month = quota['forgiven_in_month']
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

        # Pul summalarini valyutaga mos yaxlitlash (40/67 so'm qoldiqlarini kamaytirish)
        bonus = round_money(bonus, currency)
        penalty = round_money(penalty, currency)
        accrued = round_money(accrued, currency)
        paid = round_money(paid, currency)

        # Oldingi oy oxiridagi qarzdorlik
        prev_stat = get_previous_month_stat(employee, year, month)
        debt_start = round_money(prev_stat.debt_end if prev_stat else Decimal('0'), currency)
        debt_end = calculate_debt_end(debt_start, accrued, paid, currency)
        now = timezone.now()

        # Stat yozuvini yaratish yoki yangilash
        with transaction.atomic():
            stat_obj, created = MonthlyEmployeeStat.objects.get_or_create(
                employee=employee, year=year, month=month,
                defaults={
                    'salary': salary,
                    'bonus': bonus,
                    'bonus_override': bonus_override,
                    'penalty': penalty,
                    'days_in_month': total_days_in_month,
                    'worked_days': worked_days,
                    'accrued': accrued,
                    'paid': paid,
                    'paid_at': paid_at,
                    'debt_start': debt_start,
                    'debt_end': debt_end,
                    'manual_salary': manual_salary,
                    'currency': currency,
                    'calculated_at': now,
                }
            )
            if not created:
                stat_obj.salary = salary
                stat_obj.bonus = bonus
                stat_obj.bonus_override = bonus_override
                stat_obj.penalty = penalty
                stat_obj.days_in_month = total_days_in_month
                stat_obj.worked_days = worked_days
                stat_obj.accrued = accrued
                stat_obj.paid = paid
                stat_obj.paid_at = paid_at
                stat_obj.debt_start = debt_start
                stat_obj.debt_end = debt_end
                stat_obj.manual_salary = manual_salary
                stat_obj.currency = currency
                stat_obj.calculated_at = now
                update_fields = [
                    'salary', 'bonus', 'bonus_override', 'penalty', 'days_in_month',
                    'worked_days', 'accrued', 'paid', 'paid_at', 'debt_start',
                    'debt_end', 'manual_salary', 'currency', 'calculated_at',
                ]
                stat_obj.save(update_fields=update_fields)


def sync_monthly_stats_for_date(employee, day: date):
    """Davomat o'zgargach shu xodimning oylik statistikasini yangilaydi."""
    calculate_monthly_stats(day.year, day.month, employee=employee)


def sync_monthly_stats_for_month(year: int, month: int, employee=None):
    """Berilgan oy uchun oylik statistikani qayta hisoblaydi."""
    calculate_monthly_stats(year, month, employee=employee)


def ensure_monthly_stats_for_month(year: int, month: int):
    """
    Yangi oy ochilganda faqat yo'q bo'lgan xodim statlarini yaratadi.
    Mavjud yozuvlarni qayta hisoblamaydi — bu «Qayta hisoblash» tugmasi vazifasi.
    """
    active_ids = set(Employee.objects.filter(is_active=True).values_list('id', flat=True))
    if not active_ids:
        return

    existing_ids = set(
        MonthlyEmployeeStat.objects.filter(year=year, month=month).values_list('employee_id', flat=True)
    )
    missing_ids = active_ids - existing_ids
    if missing_ids:
        if missing_ids == active_ids:
            calculate_monthly_stats(year, month)
        else:
            for emp in Employee.objects.filter(id__in=missing_ids):
                calculate_monthly_stats(year, month, employee=emp)

    sync_salary_from_previous_month(year, month)