from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import GeneratedVideo
from wallet.models import CoinRequest, Transaction


class ModerationAccessTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            "moderator", password="StrongPass!234", is_staff=True,
        )
        self.member = User.objects.create_user("member", password="StrongPass!234")

    def test_anonymous_and_nonstaff_users_cannot_open_dashboard(self):
        response = self.client.get(reverse("admin_dashboard"))
        self.assertRedirects(
            response,
            reverse("admin_login") + "?next=" + reverse("admin_dashboard"),
            fetch_redirect_response=False,
        )
        denied = self.client.post(reverse("admin_login"), {
            "identifier": self.member.username,
            "password": "StrongPass!234",
        })
        self.assertEqual(denied.status_code, 200)
        self.assertContains(denied, "valid staff or superuser")

    def test_staff_login_reaches_dashboard_and_analytics(self):
        response = self.client.post(reverse("admin_login"), {
            "identifier": self.staff.username,
            "password": "StrongPass!234",
        })
        self.assertRedirects(response, reverse("admin_dashboard"))
        self.assertEqual(self.client.get(reverse("admin_dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin_reports")).status_code, 200)

    def test_moderator_cannot_publish_incomplete_reel(self):
        video = GeneratedVideo.objects.create(
            user=self.member,
            category="Shoe",
            product_name="Runner",
            status=GeneratedVideo.STATUS_FAILED,
        )
        self.client.post(reverse("admin_login"), {
            "identifier": self.staff.username,
            "password": "StrongPass!234",
        })
        response = self.client.post(
            reverse("admin_asset_action", args=["video", video.pk, "publish"]),
        )
        self.assertRedirects(response, reverse("admin_asset_detail", args=["video", video.pk]))
        video.refresh_from_db()
        self.assertFalse(video.is_published)

    def test_staff_can_approve_credit_request_once(self):
        coin_request = CoinRequest.objects.create(user=self.member, amount=50, reason="Demo")
        self.client.post(reverse("admin_login"), {
            "identifier": self.staff.username,
            "password": "StrongPass!234",
        })
        response = self.client.post(
            reverse("admin_coin_request_action", args=[coin_request.pk, "approve"]),
            {"admin_note": "Approved for portfolio review"},
        )
        self.assertRedirects(response, reverse("admin_wallets"))
        coin_request.refresh_from_db()
        self.member.wallet.refresh_from_db()
        self.assertEqual(coin_request.status, CoinRequest.STATUS_APPROVED)
        self.assertEqual(self.member.wallet.balance, 150)
        self.assertEqual(
            Transaction.objects.filter(wallet=self.member.wallet, kind=Transaction.KIND_GRANT).count(),
            1,
        )

    def test_staff_can_restrict_user_and_unpublish_assets(self):
        from core.models import GeneratedImage

        asset = GeneratedImage.objects.create(
            user=self.member,
            prompt="Published",
            image_url="/media/published.png",
            is_published=True,
        )
        self.client.post(reverse("admin_login"), {
            "identifier": self.staff.username,
            "password": "StrongPass!234",
        })
        response = self.client.post(
            reverse("admin_user_action", args=[self.member.pk, "toggle-active"]),
            {"admin_note": "Policy review"},
        )
        self.assertRedirects(response, reverse("admin_user_detail", args=[self.member.pk]))
        self.member.refresh_from_db()
        asset.refresh_from_db()
        self.assertFalse(self.member.is_active)
        self.assertFalse(asset.is_published)
