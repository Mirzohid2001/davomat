from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase


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
