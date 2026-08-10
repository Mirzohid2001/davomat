from django.contrib.auth import get_user_model
from datetime import date

from django.urls import reverse
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from blog.models import Attendance, Employee, MonthlyEmployeeStat, SalaryPayment

User = get_user_model()


class ApiIntegrationTests(APITestCase):
    def setUp(self):
        self.username = "apitester"
        self.password = "StrongPass123!"
        self.user = User.objects.create_user(
            username=self.username,
            password=self.password,
            email="api@example.com",
            first_name="Api",
            last_name="Tester",
        )

    def test_health_endpoint_is_public(self):
        response = self.client.get(reverse("api-health"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data.get("status"), "ok")

    def test_me_endpoint_requires_authentication(self):
        response = self.client.get(reverse("api-me"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_obtain_token_returns_token_for_valid_credentials(self):
        response = self.client.post(
            reverse("api-token"),
            {"username": self.username, "password": self.password},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("token", response.data)
        self.assertTrue(Token.objects.filter(key=response.data["token"], user=self.user).exists())

    def test_me_endpoint_with_token_auth(self):
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        response = self.client.get(reverse("api-me"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["username"], self.user.username)
        self.assertEqual(response.data["email"], self.user.email)

    def test_me_endpoint_with_session_auth(self):
        self.client.login(username=self.username, password=self.password)
        response = self.client.get(reverse("api-me"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["username"], self.user.username)

    def test_salary_statistics_endpoint_requires_authentication(self):
        response = self.client.get(reverse("api-salary-statistics"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_salary_statistics_endpoint_returns_employees_json(self):
        employee = Employee.objects.create(
            first_name="Ali",
            last_name="Valiyev",
            position="Operator",
            employee_type="office",
            role="other",
            is_active=True,
        )
        MonthlyEmployeeStat.objects.create(
            employee=employee,
            year=2026,
            month=4,
            salary=7000000,
            bonus=500000,
            penalty=100000,
            accrued=7400000,
            paid=5000000,
            currency="UZS",
            manual_salary=True,
            bonus_override=True,
            salary_override=True,
        )
        Attendance.objects.create(employee=employee, date=date(2026, 4, 1), status="present")
        Attendance.objects.create(employee=employee, date=date(2026, 4, 2), status="absent")

        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        response = self.client.get(f"{reverse('api-salary-statistics')}?year=2026&month=4")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("employees", response.data)
        self.assertIn("summary", response.data)
        first = next(e for e in response.data["employees"] if e["worker_code"] == str(employee.id))
        self.assertIn("worker_code", first)
        self.assertIn("full_name", first)
        self.assertIn("present_days", first)
        self.assertIn("absent_days", first)
        self.assertIn("salary", first)
        self.assertIn("currency", first)
        self.assertIn("davomat_id", first)
        self.assertEqual(first["oklad"], 7000000.0)
        self.assertEqual(first["bonus"], 500000.0)
        self.assertEqual(first["penalty"], 100000.0)
        self.assertEqual(first["accrued"], 7400000.0)
        self.assertEqual(first["paid"], 5000000.0)
        self.assertTrue(first["has_bonus"])
        self.assertTrue(first["has_penalty"])
        self.assertTrue(first["is_paid"])
        self.assertFalse(first["is_fully_paid"])
        self.assertEqual(first["payment_status"], "partial")
        self.assertEqual(response.data["summary"]["employees_with_bonus"], 1)
        self.assertEqual(response.data["summary"]["employees_with_penalty"], 1)

    def test_salary_statistics_includes_payment_breakdown(self):
        employee = Employee.objects.create(
            first_name="Dilshod",
            last_name="Karimov",
            position="Haydovchi",
            employee_type="full",
            role="other",
            is_active=True,
        )
        stat = MonthlyEmployeeStat.objects.create(
            employee=employee,
            year=2026,
            month=5,
            salary=10000000,
            accrued=10000000,
            paid=10000000,
            currency="UZS",
        )
        SalaryPayment.objects.create(stat=stat, amount=6000000, paid_at=date(2026, 5, 10))
        SalaryPayment.objects.create(stat=stat, amount=4000000, paid_at=date(2026, 5, 25), note="qoldiq")

        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        response = self.client.get(f"{reverse('api-salary-statistics')}?year=2026&month=5")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emp = next(e for e in response.data["employees"] if e["worker_code"] == str(employee.id))
        self.assertEqual(emp["payment_status"], "paid")
        self.assertTrue(emp["is_fully_paid"])
        self.assertEqual(len(emp["payments"]), 2)
        self.assertEqual(emp["payments"][0]["amount"], 6000000.0)
        self.assertEqual(emp["payments"][1]["note"], "qoldiq")
        self.assertIn("UZS", response.data["summary"]["totals_by_currency"])

