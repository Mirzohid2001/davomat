from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from blog.models import Attendance, Employee, MonthlyEmployeeStat, Team, AttendanceImportLog
from blog.services import (
    calculate_debt_end,
    calculate_monthly_stats,
    create_initial_attendance_for_new_employee,
    ensure_initial_monthly_stat,
    generate_nalivshik_attendance_for_day,
    get_absence_quota_for_period,
    normalize_attendance_status,
    round_money,
    sync_monthly_stats_for_date,
    YEARLY_ABSENCE_FREE_LIMIT,
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
        self.assertEqual(emp.hire_date, date(2026, 3, 10))
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

    def test_employee_list_shows_hire_date(self):
        Employee.objects.create(
            first_name="Test",
            last_name="User",
            position="Haydovchi",
            hire_date=date(2025, 6, 15),
        )
        response = self.client.get(reverse("employee_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ishga kirgan")
        self.assertContains(response, "15.06.2025")

    def test_employee_list_has_export_button(self):
        response = self.client.get(reverse("employee_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Excelga eksport")

    def test_employee_export_returns_xlsx(self):
        Employee.objects.create(
            first_name="Export",
            last_name="Testov",
            position="Operator",
            department="Zavod",
            employee_type="full",
        )
        response = self.client.get(reverse("employee_list_export"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "spreadsheetml",
            response["Content-Type"],
        )
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertGreater(len(response.content), 1000)

    def test_employee_export_respects_search_filter(self):
        Employee.objects.create(
            first_name="Ali", last_name="Top", position="A", employee_type="full"
        )
        Employee.objects.create(
            first_name="Boshqa", last_name="Yashirin", position="B", employee_type="full"
        )
        response = self.client.get(reverse("employee_list_export"), {"q": "Top"})
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.content), 500)


class BulkAttendanceViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="bulk_admin", password="pass12345")
        self.client = Client()
        self.client.login(username="bulk_admin", password="pass12345")
        Employee.objects.create(
            first_name="Test",
            last_name="Worker",
            position="Op",
            employee_type="full",
        )

    def test_bulk_attendance_page_loads(self):
        response = self.client.get(reverse("bulk_attendance_create"))
        self.assertEqual(response.status_code, 200)

    def test_bulk_blocks_selected_sunday_when_no_nalivshik(self):
        """Yakshanba: nalivshik bo'lmasa bloklanadi."""
        sunday = date(2026, 6, 7)
        response = self.client.get(
            reverse("bulk_attendance_create"),
            {"date": sunday.isoformat()},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard"))

    def test_bulk_allows_sunday_for_nalivshik(self):
        team = Team.objects.create(code=1, name="1-komanda")
        Employee.objects.create(
            first_name="Nav",
            last_name="Batchi",
            position="Nalivshik",
            role="nalivshik",
            team=team,
        )
        sunday = date(2026, 6, 7)
        response = self.client.get(
            reverse("bulk_attendance_create"),
            {"date": sunday.isoformat()},
        )
        self.assertEqual(response.status_code, 200)

    def test_bulk_allows_weekday_when_today_is_sunday(self):
        """Bugun yakshanba bo'lsa ham ish kuniga ?date= orqali kirish mumkin emas — faqat ish kuni."""
        wednesday = date(2026, 6, 3)
        response = self.client.get(
            reverse("bulk_attendance_create"),
            {"date": wednesday.isoformat()},
        )
        self.assertEqual(response.status_code, 200)


class GenerateNalivshikAttendanceTests(TestCase):
    def test_does_not_overwrite_existing_manual_status(self):
        team = Team.objects.create(code=1, name="1-komanda")
        emp = Employee.objects.create(
            first_name="Nav",
            last_name="Batchi",
            position="Nalivshik",
            role="nalivshik",
            team=team,
        )
        day = date(2026, 6, 3)
        Attendance.objects.create(
            employee=emp,
            date=day,
            status="absent",
            comment="Kasallik",
        )
        generate_nalivshik_attendance_for_day(day)
        att = Attendance.objects.get(employee=emp, date=day)
        self.assertEqual(att.status, "absent")
        self.assertEqual(att.comment, "Kasallik")


class AbsenceQuotaTests(TestCase):
    def setUp(self):
        self.emp = Employee.objects.create(
            first_name="Kvota",
            last_name="Test",
            position="Op",
            employee_type="full",
        )
        self.year = 2026

    def _absent(self, month, day):
        Attendance.objects.create(
            employee=self.emp,
            date=date(self.year, month, day),
            status="absent",
        )

    def test_quota_matches_monthly_salary_formula(self):
        for day in range(1, 16):
            self._absent(1, day)
        for day in range(1, 11):
            self._absent(2, day)

        quota = get_absence_quota_for_period(self.emp, self.year, 2)
        self.assertEqual(quota["absent_before"], 15)
        self.assertEqual(quota["absent_this_month"], 10)
        self.assertEqual(quota["forgiven_in_month"], 6)
        self.assertEqual(quota["affects_salary"], 4)
        self.assertEqual(quota["used"], 21)
        self.assertEqual(quota["over"], 4)

    def test_yearly_free_limit_constant(self):
        self.assertEqual(YEARLY_ABSENCE_FREE_LIMIT, 21)


class PenaltyPreservationTests(TestCase):
    def test_penalty_preserved_on_recalc(self):
        emp = Employee.objects.create(
            first_name="Jarima",
            last_name="Test",
            position="Op",
            employee_type="full",
        )
        MonthlyEmployeeStat.objects.create(
            employee=emp,
            year=2026,
            month=6,
            salary=Decimal("9000000"),
            bonus=Decimal("0"),
            penalty=Decimal("500000"),
            paid=Decimal("0"),
            accrued=Decimal("0"),
            currency="UZS",
        )
        Attendance.objects.create(employee=emp, date=date(2026, 6, 3), status="present")
        calculate_monthly_stats(2026, 6, employee=emp)
        stat = MonthlyEmployeeStat.objects.get(employee=emp, year=2026, month=6)
        self.assertEqual(stat.penalty, Decimal("500000"))
        self.assertLess(stat.accrued, stat.salary)


class PaidAtTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="paid_admin", password="pass12345")
        self.client = Client()
        self.client.login(username="paid_admin", password="pass12345")
        self.emp = Employee.objects.create(
            first_name="Pay",
            last_name="Test",
            position="Op",
            employee_type="office",
        )
        self.stat = MonthlyEmployeeStat.objects.create(
            employee=self.emp,
            year=2026,
            month=6,
            salary=Decimal("5000000"),
            bonus=Decimal("0"),
            penalty=Decimal("0"),
            paid=Decimal("0"),
            accrued=Decimal("5000000"),
            currency="UZS",
            manual_salary=True,
        )

    def test_paid_without_date_rejected(self):
        url = reverse("edit_salary_stat", args=[self.stat.id])
        response = self.client.post(
            url,
            {
                "salary": "5000000",
                "currency": "UZS",
                "paid": "3000000",
                "paid_at": "",
                "bonus": "0",
                "penalty": "0",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])
        self.stat.refresh_from_db()
        self.assertEqual(self.stat.paid, Decimal("0"))

    def test_paid_with_date_saved_and_preserved_on_recalc(self):
        url = reverse("edit_salary_stat", args=[self.stat.id])
        response = self.client.post(
            url,
            {
                "salary": "5000000",
                "currency": "UZS",
                "paid": "3000000",
                "paid_at": "2026-06-15",
                "bonus": "0",
                "penalty": "0",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["stat"]["paid_at"], "2026-06-15")
        self.stat.refresh_from_db()
        self.assertEqual(self.stat.paid, Decimal("3000000"))
        self.assertEqual(self.stat.paid_at, date(2026, 6, 15))
        calculate_monthly_stats(2026, 6, employee=self.emp)
        self.stat.refresh_from_db()
        self.assertEqual(self.stat.paid_at, date(2026, 6, 15))


class ImportStatusValidationTests(TestCase):
    def test_normalize_valid_status(self):
        self.assertEqual(normalize_attendance_status("present"), "present")
        self.assertEqual(normalize_attendance_status("Keldi"), "present")

    def test_normalize_invalid_status_raises(self):
        with self.assertRaises(ValueError):
            normalize_attendance_status("not_a_status")


class IndividualAttendanceViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="ind_admin", password="pass12345")
        self.client = Client()
        self.client.login(username="ind_admin", password="pass12345")
        self.sunday = date(2026, 6, 7)
        self.regular = Employee.objects.create(
            first_name="Ali",
            last_name="Oddiy",
            position="Op",
            employee_type="full",
        )
        self.team = Team.objects.create(code=1, name="1-komanda")
        self.nalivshik = Employee.objects.create(
            first_name="Nav",
            last_name="Batchi",
            position="Nalivshik",
            role="nalivshik",
            team=self.team,
        )

    def test_regular_employee_blocked_on_sunday(self):
        url = reverse("individual_attendance_create", args=[self.regular.id])
        response = self.client.get(url, {"date": self.sunday.isoformat()})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard"))

    def test_nalivshik_allowed_on_sunday(self):
        url = reverse("individual_attendance_create", args=[self.nalivshik.id])
        response = self.client.get(url, {"date": self.sunday.isoformat()})
        self.assertEqual(response.status_code, 200)

    def test_nalivshik_can_save_on_sunday(self):
        url = reverse("individual_attendance_create", args=[self.nalivshik.id])
        response = self.client.post(
            url + f"?date={self.sunday.isoformat()}",
            {
                "status": "present",
                "comment": "",
                "date": self.sunday.isoformat(),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Attendance.objects.filter(
                employee=self.nalivshik, date=self.sunday, status="present"
            ).exists()
        )


class AttendanceSyncMonthlyStatsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="sync_admin", password="pass12345")
        self.client = Client()
        self.client.login(username="sync_admin", password="pass12345")
        self.emp = Employee.objects.create(
            first_name="Mirzohid",
            last_name="Kenjayev",
            position="Direktor",
            department="Ofis",
            employee_type="full",
        )
        self.att_date = date(2026, 6, 3)
        MonthlyEmployeeStat.objects.create(
            employee=self.emp,
            year=2026,
            month=6,
            salary=Decimal("9000000"),
            bonus=Decimal("0"),
            paid=Decimal("0"),
            accrued=Decimal("0"),
            currency="UZS",
            days_in_month=30,
            worked_days=0,
            debt_start=Decimal("0"),
            debt_end=Decimal("0"),
        )

    def test_present_attendance_syncs_monthly_stats(self):
        Attendance.objects.create(
            employee=self.emp,
            date=self.att_date,
            status="present",
        )
        sync_monthly_stats_for_date(self.emp, self.att_date)
        stat = MonthlyEmployeeStat.objects.get(employee=self.emp, year=2026, month=6)
        self.assertEqual(stat.worked_days, 1)
        self.assertGreater(stat.accrued, Decimal("0"))

    def test_late_counts_as_worked_day(self):
        Attendance.objects.create(
            employee=self.emp,
            date=self.att_date,
            status="late",
        )
        sync_monthly_stats_for_date(self.emp, self.att_date)
        stat = MonthlyEmployeeStat.objects.get(employee=self.emp, year=2026, month=6)
        self.assertEqual(stat.worked_days, 1)
        self.assertGreater(stat.accrued, Decimal("0"))


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


class LogicIntegrationTests(TestCase):
    """Asosiy biznes logikalari o'zaro mos kelishini tekshiradi."""

    def test_quota_forgiven_affects_monthly_accrued(self):
        """Kvota kechirilgan kunlar oylik hisoblangan summaga aks etishi kerak."""
        from blog.services import calculate_working_days_in_month

        emp = Employee.objects.create(
            first_name="Integr",
            last_name="Test",
            position="Op",
            employee_type="full",
        )
        year, month = 2026, 2
        for day in range(1, 16):
            Attendance.objects.create(
                employee=emp, date=date(2026, 1, day), status="absent"
            )
        Attendance.objects.create(employee=emp, date=date(2026, 2, 3), status="present")
        for day in (4, 5, 6, 7):
            Attendance.objects.create(
                employee=emp, date=date(2026, 2, day), status="absent"
            )

        quota = get_absence_quota_for_period(emp, year, month)
        self.assertEqual(quota["forgiven_in_month"], 4)
        self.assertEqual(quota["affects_salary"], 0)

        MonthlyEmployeeStat.objects.create(
            employee=emp,
            year=year,
            month=month,
            salary=Decimal("9000000"),
            bonus=Decimal("0"),
            penalty=Decimal("0"),
            paid=Decimal("0"),
            accrued=Decimal("0"),
            currency="UZS",
        )
        calculate_monthly_stats(year, month, employee=emp)
        stat = MonthlyEmployeeStat.objects.get(employee=emp, year=year, month=month)

        working_days, _ = calculate_working_days_in_month(year, month)
        effective_days = stat.worked_days + quota["forgiven_in_month"]
        expected = (Decimal("9000000") * Decimal(str(effective_days)) / Decimal(str(working_days))).quantize(
            Decimal("1")
        )
        self.assertEqual(stat.worked_days, 1)
        self.assertEqual(stat.accrued, expected)

    def test_penalty_reduces_accrued_amount(self):
        emp = Employee.objects.create(
            first_name="Pen",
            last_name="Test",
            position="Op",
            employee_type="office",
        )
        year, month = 2026, 3
        MonthlyEmployeeStat.objects.create(
            employee=emp,
            year=year,
            month=month,
            salary=Decimal("9000000"),
            bonus=Decimal("100000"),
            penalty=Decimal("200000"),
            paid=Decimal("0"),
            accrued=Decimal("0"),
            currency="UZS",
            manual_salary=True,
        )
        calculate_monthly_stats(year, month, employee=emp)
        stat = MonthlyEmployeeStat.objects.get(employee=emp, year=year, month=month)
        self.assertEqual(stat.accrued, Decimal("8900000"))

    def test_restricted_day_helpers_consistent(self):
        from blog.services import employee_can_attend_on_date, is_restricted_attendance_date

        sunday = date(2026, 6, 7)
        regular = Employee.objects.create(
            first_name="R", last_name="Eg", position="Op", employee_type="full"
        )
        naliv = Employee.objects.create(
            first_name="N", last_name="Al", position="Nv", role="nalivshik"
        )
        self.assertTrue(is_restricted_attendance_date(sunday))
        self.assertFalse(employee_can_attend_on_date(regular, sunday))
        self.assertTrue(employee_can_attend_on_date(naliv, sunday))

    def test_bulk_formset_without_attachment_field(self):
        from django.forms import modelformset_factory
        from blog.forms import AttendanceForm

        FS = modelformset_factory(
            Attendance,
            form=AttendanceForm,
            fields=["employee", "date", "status", "comment"],
        )
        self.assertIsNotNone(FS)

    def test_import_invalid_status_skipped(self):
        User = get_user_model()
        user = User.objects.create_user(username="imp", password="pass12345")
        client = Client()
        client.login(username="imp", password="pass12345")
        emp = Employee.objects.create(
            first_name="Imp", last_name="Test", position="Op", employee_type="full"
        )
        import io

        csv_content = (
            "last_name,first_name,date,status,comment\n"
            f"Test,Imp,2026-06-03,BOGUS,\n"
        )
        csv_file = io.BytesIO(csv_content.encode("utf-8"))
        csv_file.name = "bad.csv"
        response = client.post(
            reverse("attendance_import"),
            {"file": csv_file},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            Attendance.objects.filter(employee=emp, date=date(2026, 6, 3)).exists()
        )
        log = AttendanceImportLog.objects.latest("imported_at")
        self.assertIn("Noto'g'ri status", log.log or "")

