import tempfile
from io import StringIO

from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from allauth.socialaccount.models import SocialApp

from core.models import GeneratedImage


class AccountFlowTests(TestCase):
    def test_unavailable_google_message_is_rendered_once(self):
        response = self.client.get(
            reverse("social_login_start", args=["google"]),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Google sign-in is temporarily unavailable. Please use email and password instead.",
            count=1,
        )

    def test_configured_google_login_reaches_allauth(self):
        app = SocialApp.objects.create(
            provider="google",
            name="Google",
            client_id="test-client-id",
            secret="test-client-secret",
        )
        app.sites.add(Site.objects.get_current())

        response = self.client.get(reverse("social_login_start", args=["google"]))

        self.assertRedirects(
            response,
            "/accounts/google/login/",
            fetch_redirect_response=False,
        )

    def test_login_rejects_external_next_redirect(self):
        User.objects.create_user("member", email="member@example.com", password="StrongPass!234")
        response = self.client.post(
            reverse("login") + "?next=https://attacker.example/",
            {"email": "member@example.com", "password": "StrongPass!234"},
        )
        self.assertRedirects(response, reverse("home"))

    def test_registration_uses_django_password_validation(self):
        response = self.client.post(reverse("register"), {
            "first_name": "New",
            "last_name": "User",
            "email": "new@example.com",
            "password": "password",
            "password2": "password",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email="new@example.com").exists())

    def test_profile_edit_rejects_duplicate_email(self):
        first = User.objects.create_user("first", email="first@example.com", password="StrongPass!234")
        User.objects.create_user("second", email="second@example.com", password="StrongPass!234")
        self.client.force_login(first)
        response = self.client.post(reverse("edit_profile"), {
            "first_name": "First",
            "last_name": "User",
            "email": "second@example.com",
            "bio": "",
            "location": "",
            "website": "",
            "x_handle": "",
            "instagram": "",
            "youtube": "",
            "tiktok": "",
        })
        self.assertEqual(response.status_code, 200)
        first.refresh_from_db()
        self.assertEqual(first.email, "first@example.com")


class SeedDemoTests(TestCase):
    def test_seed_demo_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            with override_settings(MEDIA_ROOT=directory):
                call_command("seed_demo", stdout=StringIO())
                call_command("seed_demo", stdout=StringIO())
        self.assertEqual(User.objects.filter(username__startswith="demo_").count(), 4)
        self.assertEqual(GeneratedImage.objects.filter(user__username__startswith="demo_").count(), 8)
