from datetime import date
from decimal import Decimal

from django.db.models import Count, Prefetch, Q
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from blog.models import Attendance, MonthlyEmployeeStat, SalaryPayment
from blog.services import (
    aggregate_salary_currency_totals,
    calculate_monthly_stats,
    get_active_loan_remaining_total,
)

from .serializers import SalaryStatisticsItemSerializer, UserInfoSerializer


def _money(value) -> float:
    return float(value or 0)


def _payment_status(accrued: Decimal, paid: Decimal) -> str:
    accrued = accrued or Decimal("0")
    paid = paid or Decimal("0")
    if paid <= 0:
        return "unpaid"
    if accrued > 0 and paid < accrued:
        return "partial"
    if accrued > 0 and paid > accrued:
        return "overpaid"
    return "paid"


class HealthCheckAPIView(APIView):
    """
    Ochiq endpoint: API ishlayotganini tekshirish.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "ok", "message": "API is working"})


class MeAPIView(APIView):
    """
    Himoyalangan endpoint: Session yoki Token auth bilan ishlaydi.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserInfoSerializer(request.user)
        return Response(serializer.data)


class SalaryStatisticsAPIView(APIView):
    """
    ERP integratsiyasi uchun oylik statistikani to'liq JSON ko'rinishida qaytaradi.
    URL: /api/statistics/salary/?year=2026&month=4

    Har bir xodim: oklad, premiya, jarima, hisoblangan, to'langan,
    to'lov holati, ushlab qolish, qarzdorlik va alohida to'lovlar.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = date.today()
        try:
            year = int(request.GET.get("year", today.year))
            month = int(request.GET.get("month", today.month))
        except (TypeError, ValueError):
            return Response({"detail": "year/month noto'g'ri formatda."}, status=400)

        if month < 1 or month > 12:
            return Response({"detail": "month 1 dan 12 gacha bo'lishi kerak."}, status=400)

        # Statlar bo'lmasa ham endpoint bo'sh ro'yxat qaytarmasligi uchun hisoblaymiz.
        calculate_monthly_stats(year, month)

        stats = (
            MonthlyEmployeeStat.objects.filter(year=year, month=month)
            .select_related("employee")
            .prefetch_related(
                Prefetch(
                    "salary_payments",
                    queryset=SalaryPayment.objects.order_by("paid_at", "pk"),
                )
            )
            .order_by("employee__last_name", "employee__first_name", "employee_id")
        )

        employee_ids = [s.employee_id for s in stats]
        attendance_counts = Attendance.objects.filter(
            date__year=year,
            date__month=month,
            employee_id__in=employee_ids,
        ).values("employee_id").annotate(
            present_days=Count("id", filter=Q(status__in=["present", "sick", "late"])),
            absent_days=Count("id", filter=Q(status="absent")),
        )
        attendance_map = {row["employee_id"]: row for row in attendance_counts}

        data = []
        for stat in stats:
            emp = stat.employee
            counts = attendance_map.get(emp.id, {})
            accrued = stat.accrued or Decimal("0")
            paid = stat.paid or Decimal("0")
            bonus = stat.bonus or Decimal("0")
            penalty = stat.penalty or Decimal("0")
            loan_deduction = stat.loan_deduction or Decimal("0")
            net_received = max(paid - loan_deduction, Decimal("0"))
            status = _payment_status(accrued, paid)
            payments = [
                {
                    "amount": _money(p.amount),
                    "paid_at": p.paid_at,
                    "note": p.note or "",
                }
                for p in stat.salary_payments.all()
            ]

            data.append(
                {
                    "worker_code": str(emp.id),
                    "full_name": emp.get_full_name(),
                    "position": emp.position or "",
                    "department": emp.department or "",
                    "employee_type": emp.employee_type,
                    "employee_type_label": emp.get_employee_type_display(),
                    "role": emp.role,
                    "role_label": emp.get_role_display(),
                    "location": emp.location,
                    "is_active": emp.is_active,
                    "present_days": counts.get("present_days", 0),
                    "absent_days": counts.get("absent_days", 0),
                    "worked_days": stat.worked_days,
                    "days_in_month": stat.days_in_month,
                    # Orqa moslik: eski `salary` = hisoblangan
                    "salary": _money(accrued),
                    "oklad": _money(stat.salary),
                    "bonus": _money(bonus),
                    "penalty": _money(penalty),
                    "accrued": _money(accrued),
                    "paid": _money(paid),
                    "loan_deduction": _money(loan_deduction),
                    "net_received": _money(net_received),
                    "loan_remaining": _money(
                        get_active_loan_remaining_total(emp, stat.currency)
                    ),
                    "debt_start": _money(stat.debt_start),
                    "debt_end": _money(stat.debt_end),
                    "currency": stat.currency,
                    "paid_at": stat.paid_at,
                    "has_bonus": bonus > 0,
                    "has_penalty": penalty > 0,
                    "is_paid": paid > 0,
                    "is_fully_paid": status in ("paid", "overpaid"),
                    "payment_status": status,
                    "payments": payments,
                    "davomat_id": f"emp_{emp.id}",
                }
            )

        currency_totals = aggregate_salary_currency_totals(stats)
        totals_by_currency = {
            cur: {
                "oklad": _money(vals["salary"]),
                "bonus": _money(vals["bonus"]),
                "penalty": _money(vals["penalty"]),
                "accrued": _money(vals["accrued"]),
                "paid": _money(vals["paid"]),
                "loan_deduction": _money(vals["loan_deduction"]),
                "net_received": _money(vals["net_received"]),
                "loan_remaining": _money(vals["active_loan_remaining"]),
                "debt_start": _money(vals["debt_start"]),
                "debt_end": _money(vals["debt_end"]),
            }
            for cur, vals in currency_totals.items()
        }

        serializer = SalaryStatisticsItemSerializer(instance=data, many=True)
        return Response(
            {
                "year": year,
                "month": month,
                "count": len(data),
                "summary": {
                    "employees_total": len(data),
                    "employees_paid": sum(1 for row in data if row["is_paid"]),
                    "employees_unpaid": sum(1 for row in data if not row["is_paid"]),
                    "employees_fully_paid": sum(1 for row in data if row["is_fully_paid"]),
                    "employees_with_bonus": sum(1 for row in data if row["has_bonus"]),
                    "employees_with_penalty": sum(1 for row in data if row["has_penalty"]),
                    "totals_by_currency": totals_by_currency,
                },
                "employees": serializer.data,
            }
        )
