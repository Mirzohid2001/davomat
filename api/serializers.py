from django.contrib.auth import get_user_model
from rest_framework import serializers


User = get_user_model()


class UserInfoSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "username", "email", "first_name", "last_name", "is_staff")


class SalaryStatisticsItemSerializer(serializers.Serializer):
    worker_code = serializers.CharField()
    full_name = serializers.CharField()
    present_days = serializers.IntegerField()
    absent_days = serializers.IntegerField()
    salary = serializers.FloatField()
    currency = serializers.CharField()
    davomat_id = serializers.CharField()
