from django.contrib.auth import get_user_model
from rest_framework import serializers


User = get_user_model()


class UserInfoSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "username", "email", "first_name", "last_name", "is_staff")


class SalaryPaymentItemSerializer(serializers.Serializer):
    amount = serializers.FloatField()
    paid_at = serializers.DateField()
    note = serializers.CharField(allow_blank=True)


class SalaryStatisticsItemSerializer(serializers.Serializer):
    worker_code = serializers.CharField()
    full_name = serializers.CharField()
    position = serializers.CharField(allow_blank=True)
    department = serializers.CharField(allow_blank=True, allow_null=True)
    employee_type = serializers.CharField()
    employee_type_label = serializers.CharField()
    role = serializers.CharField()
    role_label = serializers.CharField()
    location = serializers.CharField()
    is_active = serializers.BooleanField()

    present_days = serializers.IntegerField()
    absent_days = serializers.IntegerField()
    worked_days = serializers.IntegerField()
    days_in_month = serializers.IntegerField()

    # Orqa moslik: eski ERP mijozlar `salary`ni hisoblangan summa sifatida olgan
    salary = serializers.FloatField()
    oklad = serializers.FloatField()
    bonus = serializers.FloatField()
    penalty = serializers.FloatField()
    accrued = serializers.FloatField()
    paid = serializers.FloatField()
    loan_deduction = serializers.FloatField()
    net_received = serializers.FloatField()
    loan_remaining = serializers.FloatField()
    debt_start = serializers.FloatField()
    debt_end = serializers.FloatField()
    currency = serializers.CharField()
    paid_at = serializers.DateField(allow_null=True)

    has_bonus = serializers.BooleanField()
    has_penalty = serializers.BooleanField()
    is_paid = serializers.BooleanField()
    is_fully_paid = serializers.BooleanField()
    payment_status = serializers.CharField()
    payments = SalaryPaymentItemSerializer(many=True)

    davomat_id = serializers.CharField()
