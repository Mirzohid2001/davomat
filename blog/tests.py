from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from blog.models import Attendance, Employee, MonthlyEmployeeStat
from blog.services import (
    calculate_debt_end,
    calculate_monthly_stats,
    create_initial_attendance_for_new_employee,
    ensure_initial_monthly_stat,
    round_money,
)


class RoundMoneyTests(TestCase):
    def test_uzs_rounds_to_whole_som(self):
        self.assertEqual(round_money(Decimal("7999960.4"), "UZS"), Decimal("7999960"))
        self.assertEqual(round_money(Decimal("7999960.6"), "UZS"), Decimal("7999961"))

    def test_usd_keeps_two_decimals(self):
        self.assertEqual(round_money(Decimal("1000.456"), "USD"), Decimal("1000.46"))


class CalculateDebtEndTests(TestCase):
    def test_monthly_salary_only_paid_leaves_previous_debt(self):
        """Faqat shu oy hisoblangan to'langan — oldingi qarz qoladi."""
        debt_end = calculate_debt_end(
            debt_start=Decimal("1000"),
            accrued=Decimal("15000000"),
            paid=Decimal("15000000"),
            currency="UZS",
        )
        self.assertEqual(debt_end, Decimal("1000"))

    def test_full_settlement_clears_debt(self):
        """Hisoblangan + boshlang'ich qarz to'liq to'lansa — oxirgi qarz 0."""
        debt_end = calculate_debt_end(
            debt_start=Decimal("1000"),
            accrued=Decimal("15000000"),
            paid=Decimal("15001000"),
            currency="UZS",
        )
        self.assertEqual(debt_end, Decimal("0"))

    def test_no_debt_when_paid_equals_accrued_and_no_start_debt(self):
        debt_end = calculate_debt_end(
            debt_start=Decimal("0"),
            accrued=Decimal("8000000"),
            paid=Decimal("8000000"),
            currency="UZS",
        )
        self.assertEqual(debt_end, Decimal("0"))

    def test_partial_payment_creates_debt(self):
        debt_end = calculate_debt_end(
            debt_start=Decimal("0"),
            accrued=Decimal("8000000"),
            paid=Decimal("6000000"),
            currency="UZS",
        )
        self.assertEqual(debt_end, Decimal("2000000"))

    def test_fractional_accrued_rounded_before_debt(self):
        """Kasrli hisoblangan yaxlitlanadi — kichik phantom qarz bo'lmasin."""
        debt_end = calculate_debt_end(
            debt_start=Decimal("0"),
            accrued=Decimal("7999960.49"),
            paid=Decimal("7999960"),
            currency="UZS",
        )
        self.assertEqual(debt_end, Decimal("0"))


class NewEmployeeTests(TestCase):
    def test_ensure_initial_monthly_stat_salary_zero(self):
        emp = Employee.objects.create(
            first_name="Yangi",
            last_name="Ishchi",
            position="Test",
            employee_type="full",
        )
        hire = date(2026, 3, 10)
        ensure_initial_monthly_stat(emp, hire)
        stat = MonthlyEmployeeStat.objects.get(employee=emp, year=2026, month=3)
        self.assertEqual(stat.salary, Decimal("0"))

    def test_create_initial_attendance_from_hire_date(self):
        emp = Employee.objects.create(
            first_name="Yangi",
            last_name="Ishchi",
            position="Test",
            employee_type="full",
        )
        hire = date(2026, 3, 10)
        created = create_initial_attendance_for_new_employee(emp, hire, 3)
        self.assertEqual(created, 3)
        self.assertEqual(
            Attendance.objects.filter(
                employee=emp, date__year=2026, date__month=3, status="present"
            ).count(),
            3,
        )

    def test_new_employee_default_salary_not_1000(self):
        emp = Employee.objects.create(
            first_name="Birinchi",
            last_name="Stat",
            position="Test",
            employee_type="full",
        )
        calculate_monthly_stats(2026, 4)
        stat = MonthlyEmployeeStat.objects.get(employee=emp, year=2026, month=4)
        self.assertEqual(stat.salary, Decimal("0"))

    def test_full_flow_hire_date_and_worked_days_reflect_in_stats(self):
        """Kelgan kunlar → davomat → oylik statistikada worked_days mos kelishi."""
        emp = Employee.objects.create(
            first_name="Ali",
            last_name="Testov",
            position="Operator",
            employee_type="full",
            role="other",
        )
        hire = date(2026, 2, 2)  # 2026-02-02 — dushanba
        worked = 10

        ensure_initial_monthly_stat(emp, hire)
        created = create_initial_attendance_for_new_employee(emp, hire, worked)
        calculate_monthly_stats(2026, 2)

        self.assertEqual(created, worked)
        self.assertEqual(
            Attendance.objects.filter(
                employee=emp, date__year=2026, date__month=2, status__in=["present", "sick"]
            ).count(),
            worked,
        )
        stat = MonthlyEmployeeStat.objects.get(employee=emp, year=2026, month=2)
        self.assertEqual(stat.salary, Decimal("0"))
        self.assertEqual(stat.worked_days, worked)
        # Oylik 0 bo'lgani uchun hisoblangan ham 0; kelgan kunlar worked_days da aks etadi
        self.assertEqual(stat.accrued, Decimal("0"))

    def test_skips_sunday_for_regular_employee(self):
        """Oddiy xodim: yakshanba o'tkazib yuboriladi, kelgan kunlar ish kunlarida."""
        emp = Employee.objects.create(
            first_name="Sun",
            last_name="Test",
            position="Op",
            employee_type="full",
        )
        # 2026-02-08 yakshanba
        hire = date(2026, 2, 7)  # shanba
        create_initial_attendance_for_new_employee(emp, hire, 2)
        dates = list(
            Attendance.objects.filter(employee=emp).values_list("date", flat=True)
        )
        self.assertNotIn(date(2026, 2, 8), dates)
        self.assertEqual(len(dates), 2)


class EmployeeCreateViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="admin_test", password="pass12345")
        self.client = Client()
        self.client.login(username="admin_test", password="pass12345")

    def test_create_employee_via_form_post(self):
        response = self.client.post(
            reverse("employee_create"),
            {
                "first_name": "Yangi",
                "last_name": "Xodim",
                "position": "Haydovchi",
                "department": "Zavod",
                "location": "factory",
                "phone_number": "",
                "is_active": "on",
                "employee_type": "full",
                "role": "other",
                "team": "",
                "hire_date": "2026-03-10",
                "worked_days_count": "5",
            },
        )
        self.assertEqual(response.status_code, 302)

        emp = Employee.objects.get(last_name="Xodim", first_name="Yangi")
        self.assertEqual(
            Attendance.objects.filter(employee=emp, status="present").count(), 5
        )
        stat = MonthlyEmployeeStat.objects.get(employee=emp, year=2026, month=3)
        self.assertEqual(stat.salary, Decimal("0"))
        self.assertEqual(stat.worked_days, 5)

    def test_create_page_shows_hire_and_worked_fields(self):
        response = self.client.get(reverse("employee_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ishga kirgan sana")
        self.assertContains(response, "Kelgan kunlar soni")


class CalculateMonthlyStatsDebtIntegrationTests(TestCase):
    def setUp(self):
        self.year = 2026
        self.month = 2

    def _create_full_employee(self, **kwargs):
        defaults = {
            "first_name": "Test",
            "last_name": "Worker",
            "position": "Operator",
            "employee_type": "full",
            "role": "other",
            "is_active": True,
        }
        defaults.update(kwargs)
        return Employee.objects.create(**defaults)

    def _fill_working_days(self, employee, year, month, count):
        """Ish kunlarini present qilib to'ldirish (yakshanba va dayoff dan tashqari)."""
        from calendar import monthrange

        total = monthrange(year, month)[1]
        added = 0
        for day in range(1, total + 1):
            if added >= count:
                break
            d = date(year, month, day)
            if d.weekday() == 6:
                continue
            Attendance.objects.create(employee=employee, date=d, status="present")
            added += 1

    def test_office_employee_full_pay_zero_debt(self):
        emp = self._create_full_employee(
            last_name="Office",
            employee_type="office",
        )
        MonthlyEmployeeStat.objects.create(
            employee=emp,
            year=self.year,
            month=self.month,
            salary=Decimal("15000000"),
            bonus=Decimal("0"),
            paid=Decimal("15000000"),
            accrued=Decimal("15000000"),
            currency="UZS",
            manual_salary=True,
            days_in_month=28,
            worked_days=0,
            debt_start=Decimal("0"),
            debt_end=Decimal("0"),
        )

        calculate_monthly_stats(self.year, self.month)
        stat = MonthlyEmployeeStat.objects.get(employee=emp, year=self.year, month=self.month)
        self.assertEqual(stat.debt_end, Decimal("0"))

    def test_paid_accrued_only_keeps_debt_start(self):
        """Faqat shu oy oyligi to'lansa, oldingi 1000 so'm qarz qolishi kerak."""
        emp = self._create_full_employee(last_name="Aziz", employee_type="office")
        MonthlyEmployeeStat.objects.create(
            employee=emp,
            year=self.year,
            month=1,
            salary=Decimal("15000000"),
            bonus=Decimal("0"),
            paid=Decimal("15000000"),
            accrued=Decimal("15000000"),
            currency="UZS",
            manual_salary=True,
            days_in_month=31,
            worked_days=0,
            debt_start=Decimal("0"),
            debt_end=Decimal("1000"),
        )
        MonthlyEmployeeStat.objects.create(
            employee=emp,
            year=self.year,
            month=self.month,
            salary=Decimal("15000000"),
            bonus=Decimal("0"),
            paid=Decimal("0"),
            accrued=Decimal("0"),
            currency="UZS",
            manual_salary=True,
            days_in_month=28,
            worked_days=0,
            debt_start=Decimal("0"),
            debt_end=Decimal("0"),
        )

        calculate_monthly_stats(self.year, self.month)
        stat = MonthlyEmployeeStat.objects.get(employee=emp, year=self.year, month=self.month)
        self.assertEqual(stat.debt_start, Decimal("1000"))
        stat.paid = stat.accrued
        stat.save()

        calculate_monthly_stats(self.year, self.month)
        stat.refresh_from_db()
        self.assertEqual(stat.debt_end, Decimal("1000"))

    def test_full_settlement_clears_debt_on_recalc(self):
        emp = self._create_full_employee(last_name="Toza")
        MonthlyEmployeeStat.objects.create(
            employee=emp,
            year=self.year,
            month=1,
            salary=Decimal("15000000"),
            bonus=Decimal("0"),
            paid=Decimal("15000000"),
            accrued=Decimal("15000000"),
            currency="UZS",
            days_in_month=31,
            worked_days=24,
            debt_start=Decimal("0"),
            debt_end=Decimal("1000"),
        )
        MonthlyEmployeeStat.objects.create(
            employee=emp,
            year=self.year,
            month=self.month,
            salary=Decimal("15000000"),
            bonus=Decimal("0"),
            paid=Decimal("15001000"),
            accrued=Decimal("15000000"),
            currency="UZS",
            days_in_month=28,
            worked_days=24,
            debt_start=Decimal("1000"),
            debt_end=Decimal("1000"),
        )

        calculate_monthly_stats(self.year, self.month)
        stat = MonthlyEmployeeStat.objects.get(employee=emp, year=self.year, month=self.month)
        self.assertEqual(stat.debt_end, Decimal("0"))

    def test_proportional_full_pay_no_phantom_debt(self):
        """To'liq ishlangan oy — to'langan = hisoblangan bo'lsa qarz 0."""
        emp = self._create_full_employee(last_name="Proportional")
        salary = Decimal("8000000")
        self._fill_working_days(emp, self.year, self.month, 24)

        MonthlyEmployeeStat.objects.create(
            employee=emp,
            year=self.year,
            month=self.month,
            salary=salary,
            bonus=Decimal("0"),
            paid=Decimal("0"),
            accrued=Decimal("0"),
            currency="UZS",
            days_in_month=28,
            worked_days=0,
            debt_start=Decimal("0"),
            debt_end=Decimal("0"),
        )

        calculate_monthly_stats(self.year, self.month)
        stat = MonthlyEmployeeStat.objects.get(employee=emp, year=self.year, month=self.month)
        self.assertGreater(stat.accrued, Decimal("0"))
        stat.paid = stat.accrued
        stat.save()

        calculate_monthly_stats(self.year, self.month)
        stat.refresh_from_db()
        self.assertEqual(stat.debt_end, Decimal("0"))
