from django.urls import path
from rest_framework.authtoken.views import obtain_auth_token

from .views import EmployeesAPIView, HealthCheckAPIView, MeAPIView, SalaryStatisticsAPIView


urlpatterns = [
    path("health/", HealthCheckAPIView.as_view(), name="api-health"),
    path("me/", MeAPIView.as_view(), name="api-me"),
    path("employees/", EmployeesAPIView.as_view(), name="api-employees"),
    path("statistics/salary/", SalaryStatisticsAPIView.as_view(), name="api-salary-statistics"),
    path("auth/token/", obtain_auth_token, name="api-token"),
]
