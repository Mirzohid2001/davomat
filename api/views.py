from datetime import date

from django.db.models import Count, Q
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from blog.models import Attendance, MonthlyEmployeeStat
from blog.services import calculate_monthly_stats

from .serializers import SalaryStatisticsItemSerializer, UserInfoSerializer


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
    ERP integratsiyasi uchun oylik statistikani JSON ko'rinishida qaytaradi.
    URL: /api/statistics/salary/?year=2026&month=4
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

        stats = MonthlyEmployeeStat.objects.filter(year=year, month=month).select_related("employee")
        attendance_counts = Attendance.objects.filter(
            date__year=year,
            date__month=month,
            employee__in=[s.employee_id for s in stats],
        ).values("employee_id").annotate(
            present_days=Count("id", filter=Q(status__in=["present", "sick"])),
            absent_days=Count("id", filter=Q(status="absent")),
        )
        attendance_map = {row["employee_id"]: row for row in attendance_counts}

        data = []
        for stat in stats:
            emp = stat.employee
            counts = attendance_map.get(emp.id, {})
            full_name = f"{emp.last_name} {emp.first_name}".strip()
            data.append(
                {
                    "worker_code": str(emp.id),
                    "full_name": full_name,
                    "present_days": counts.get("present_days", 0),
                    "absent_days": counts.get("absent_days", 0),
                    "salary": float(stat.accrued),
                    "currency": stat.currency,
                    "davomat_id": f"emp_{emp.id}",
                }
            )

        serializer = SalaryStatisticsItemSerializer(instance=data, many=True)
        return Response({"employees": serializer.data, "year": year, "month": month})
