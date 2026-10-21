import json
import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import GeneratedImage
from wallet.models import BasketItem, CoinRequest, Transaction


class WalletFlowTests(TestCase):
    def setUp(self):
        self.creator = User.objects.create_user("seller", password="StrongPass!234")
        self.buyer = User.objects.create_user("buyer", password="StrongPass!234")
        self.client.force_login(self.buyer)

    def test_basket_uses_configured_asset_price(self):
        asset = GeneratedImage.objects.create(
            user=self.creator, prompt="Sale", image_url="/media/sale.png",
            is_published=True, coin_price=25,
        )
        response = self.client.post(
            reverse("basket_add"),
            data=json.dumps({"asset_type": "image", "asset_id": asset.pk}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(BasketItem.objects.get().coin_price_snapshot, 25)

    def test_wallet_page_describes_demo_credits_without_payment_brands(self):
        response = self.client.get(reverse("wallet_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Demo currency")
        self.assertNotContains(response, "PayPal")

    def test_missing_file_never_charges_wallet(self):
        asset = GeneratedImage.objects.create(
            user=self.creator, prompt="Missing", image_url="/media/missing.png",
            is_published=True, coin_price=40,
        )
        BasketItem.objects.create(user=self.buyer, image=asset, coin_price_snapshot=40)
        starting_balance = self.buyer.wallet.balance
        response = self.client.post(reverse("basket_confirm"))
        self.assertEqual(response.status_code, 302)
        self.buyer.wallet.refresh_from_db()
        self.assertEqual(self.buyer.wallet.balance, starting_balance)
        self.assertFalse(Transaction.objects.filter(kind=Transaction.KIND_DOWNLOAD).exists())

    def test_credit_request_is_not_presented_as_payment(self):
        response = self.client.post(reverse("request_coins"), {"amount": 75, "reason": "Demo review"})
        self.assertEqual(response.status_code, 302)
        request = CoinRequest.objects.get(user=self.buyer)
        self.assertEqual(request.amount, 75)
        self.assertEqual(request.transaction_id, "")
        self.assertEqual(request.usd_amount, 0)

    def test_valid_zip_charges_once_and_clears_basket(self):
        with tempfile.TemporaryDirectory() as directory:
            media_root = Path(directory)
            (media_root / "ready.png").write_bytes(b"image bytes")
            asset = GeneratedImage.objects.create(
                user=self.creator, prompt="Ready", image_url="/media/ready.png",
                is_published=True, coin_price=40,
            )
            BasketItem.objects.create(user=self.buyer, image=asset, coin_price_snapshot=40)
            with override_settings(MEDIA_ROOT=media_root):
                response = self.client.post(reverse("basket_confirm"))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "application/zip")
            self.buyer.wallet.refresh_from_db()
            self.assertEqual(self.buyer.wallet.balance, 60)
            self.assertFalse(BasketItem.objects.filter(user=self.buyer).exists())
            self.assertEqual(Transaction.objects.filter(kind=Transaction.KIND_DOWNLOAD).count(), 1)
