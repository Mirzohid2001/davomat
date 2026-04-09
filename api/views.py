from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import UserInfoSerializer


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
