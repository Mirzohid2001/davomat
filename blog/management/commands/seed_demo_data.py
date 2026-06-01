"""
Demo ma'lumotlar: xodimlar, davomat, oylik statistika.
Ishlatish: python manage.py seed_demo_data
"""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from blog.models import Attendance, DayOff, Employee, MonthlyEmployeeStat, Team
from blog.services import (
    calculate_monthly_stats,
    calculate_working_days_in_month,
    create_initial_attendance_for_new_employee,
    ensure_initial_monthly_stat,
)


class Command(BaseCommand):
    help = "Bazaga demo xodimlar, davomat va oylik statistikani qo'shadi"

    def add_arguments(self, parser):
        parser.add_argument(
            "--year",
            type=int,
            default=2026,
            help="Davomat va statistika yili (default: 2026)",
        )
        parser.add_argument(
            "--month",
            type=int,
            default=5,
            help="Davomat va statistika oyi (default: 5)",
        )

    def handle(self, *args, **options):
        year = options["year"]
        month = options["month"]

        months = sorted({month, 2} if year == 2026 and month != 2 else {month})

        with transaction.atomic():
            teams = self._ensure_teams()
            created_employees = self._ensure_employees(teams, year, month)
            att_total = 0
            for m in months:
                att_total += self._seed_attendance(year, m)
                calculate_monthly_stats(year, m)
                self._seed_salaries(year, m)
                calculate_monthly_stats(year, m)

        self.stdout.write(self.style.SUCCESS(
            f"Tayyor: +{created_employees} xodim, {att_total} davomat yozuvi, "
            f"oylik statistika: {', '.join(f'{year}-{m:02d}' for m in months)}."
        ))

    def _ensure_teams(self):
        data = [
            (1, "Alfa", "1-komanda"),
            (2, "Betta", "2-komanda"),
            (3, "Sirius", "3-komanda"),
        ]
        teams = {}
        for code, name, desc in data:
            t, _ = Team.objects.get_or_create(
                code=code, defaults={"name": name, "description": desc}
            )
            teams[code] = t
        return teams

    def _ensure_employees(self, teams, year, month):
        """Yangi demo xodimlar (mavjud bo'lsa o'tkazib yuboriladi)."""
        roster = [
            # full stavka — zavod
            ("Sharipov", "Mirshodbek", "Operator", "Ishlab chiqarish", "factory", "full", "other", None, 14_400_000),
            ("Shurofiddinov", "Kamil", "Mexanik", "Ishlab chiqarish", "factory", "full", "other", None, 9_600_000),
            ("Rahimov", "Jasur", "Haydovchi", "Logistika", "factory", "full", "other", None, 8_000_000),
            ("Karimov", "Sardor", "Usta", "Ishlab chiqarish", "factory", "full", "other", None, 12_000_000),
            ("Toshmatov", "Bekzod", "Elektrik", "Texnik xizmat", "factory", "full", "other", None, 11_000_000),
            # nalivshik
            ("Yusupov", "Farhod", "Nalivshik", "Naliv", "factory", "full", "nalivshik", 1, 10_000_000),
            ("Ergashev", "Dilshod", "Nalivshik", "Naliv", "factory", "full", "nalivshik", 2, 10_000_000),
            ("Normatov", "Sherzod", "Nalivshik", "Naliv", "factory", "full", "nalivshik", 3, 10_000_000),
            # 15 kunlik
            ("Xolmatov", "Rustam", "Ishchi", "Ishlab chiqarish", "factory", "half", "other", None, 6_000_000),
            ("Ismoilov", "Bobur", "Ishchi", "Ishlab chiqarish", "factory", "half", "other", None, 6_000_000),
            # ofis
            ("Aziz", "Xodjayev", "Buxgalter", "Moliya", "office", "office", "other", None, 15_000_000),
            ("Saidova", "Malika", "Kadrlar", "HR", "office", "office", "other", None, 12_000_000),
            ("Raxmonov", "Timur", "Direktor yordamchisi", "Boshqaruv", "office", "office", "other", None, 18_000_000),
            # qorovul / haftalik
            ("Qodirov", "Otabek", "Qorovul", "Xavfsizlik", "factory", "guard", "other", None, 4_000_000),
            ("Abdurahmonov", "Ilhom", "Texnik", "Texnik xizmat", "factory", "weekly", "other", None, 8_000_000),
        ]

        created = 0
        hire = date(year, month, 1)

        for row in roster:
            last, first, pos, dept, loc, etype, role, team_code, salary = row
            if Employee.objects.filter(last_name=last, first_name=first).exists():
                continue
            emp = Employee.objects.create(
                last_name=last,
                first_name=first,
                position=pos,
                department=dept,
                location=loc,
                phone_number="+998901234567",
                employee_type=etype,
                role=role,
                team=teams.get(team_code) if team_code else None,
                is_active=True,
            )
            ensure_initial_monthly_stat(emp, hire)
            stat = MonthlyEmployeeStat.objects.get(employee=emp, year=hire.year, month=hire.month)
            stat.salary = Decimal(str(salary))
            stat.currency = "UZS"
            stat.save(update_fields=["salary", "currency"])
            # Oy boshidan ~80% ish kunlari kelgan deb belgilaymiz
            working_days, _ = calculate_working_days_in_month(hire.year, hire.month)
            worked = max(1, int(working_days * 0.85)) if etype != "office" else 0
            if etype != "office" and worked > 0:
                create_initial_attendance_for_new_employee(emp, hire, worked)
            created += 1

        return created

    def _seed_attendance(self, year, month):
        """Barcha aktiv xodimlar uchun shu oy davomatini to'ldirish."""
        from calendar import monthrange

        working_days, _ = calculate_working_days_in_month(year, month)
        dayoffs = set(
            DayOff.objects.filter(date__year=year, date__month=month).values_list("date", flat=True)
        )
        total_days = monthrange(year, month)[1]
        count = 0

        for emp in Employee.objects.filter(is_active=True):
            if emp.employee_type == "office":
                continue

            present_target = working_days
            if emp.employee_type == "half":
                present_target = min(15, working_days)
            elif emp.employee_type == "guard":
                present_target = min(10, working_days)
            elif emp.employee_type == "weekly":
                present_target = min(4, working_days)

            present_created = 0
            for day in range(1, total_days + 1):
                if present_created >= present_target:
                    break
                d = date(year, month, day)
                if emp.role != "nalivshik":
                    if d.weekday() == 6 or d in dayoffs:
                        continue
                status = "present"
                # Oxirgi 1-2 ish kuni kelmagan (kvota testi)
                if present_created >= present_target - 1 and emp.employee_type == "full":
                    status = "absent"
                Attendance.objects.update_or_create(
                    employee=emp,
                    date=d,
                    defaults={"status": status, "comment": "Demo ma'lumot"},
                )
                count += 1
                if status == "present":
                    present_created += 1

        return count

    def _seed_salaries(self, year, month):
        """Ba'zi xodimlarga to'langan summani demo qilib qo'yish."""
        for stat in MonthlyEmployeeStat.objects.filter(year=year, month=month):
            if stat.paid > 0:
                continue
            if stat.employee.employee_type == "office":
                stat.paid = stat.accrued
            elif stat.accrued > 0:
                stat.paid = stat.accrued
            stat.save(update_fields=["paid"])
