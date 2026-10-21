import json
import tempfile
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from core.models import GeneratedImage, GeneratedVideo
from studio.services.reel_pipeline import run_pipeline


def valid_png(name="product.png"):
    buffer = BytesIO()
    Image.new("RGB", (20, 20), "blue").save(buffer, "PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class StudioFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("creator", password="StrongPass!234")
        self.other = User.objects.create_user("other", password="StrongPass!234")

    def test_generation_pages_require_login(self):
        self.assertEqual(self.client.get(reverse("prompt_to_image")).status_code, 302)
        self.assertEqual(self.client.get(reverse("create")).status_code, 302)

    def test_authenticated_creation_pages_and_assets_render(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("prompt_to_image")).status_code, 200)
        self.assertEqual(self.client.get(reverse("create")).status_code, 200)
        self.assertEqual(self.client.get(reverse("my_assets")).status_code, 200)

    def test_short_image_prompt_is_rejected(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("generate_image"),
            data=json.dumps({"prompt": "x", "style": "Realistic", "aspect_ratio": "1:1"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    @override_settings(
        CLOUDFLARE_ACCOUNT_ID="",
        CLOUDFLARE_AI_TOKEN="",
    )
    def test_missing_image_provider_configuration_is_graceful(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("generate_image"),
            data=json.dumps({"prompt": "A blue watch", "style": "Realistic", "aspect_ratio": "1:1"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("not configured", response.json()["error"])

    @patch("studio.views.HuggingFaceImageProvider.generate_image")
    def test_generated_image_is_owned_draft_then_publishable(self, generate):
        generate.return_value = {
            "image_url": "/media/generated/test.png",
            "prompt_used": "A blue watch, Realistic style",
        }
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("generate_image"),
            data=json.dumps({"prompt": "A blue watch", "style": "Realistic", "aspect_ratio": "1:1"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        asset = GeneratedImage.objects.get(pk=response.json()["asset_id"])
        self.assertEqual(asset.user, self.user)
        self.assertFalse(asset.is_published)

        publish = self.client.post(
            reverse("save_image"),
            data=json.dumps({"asset_id": asset.pk, "publish": True}),
            content_type="application/json",
        )
        self.assertEqual(publish.status_code, 200)
        asset.refresh_from_db()
        self.assertTrue(asset.is_published)

    def test_user_cannot_publish_another_users_asset(self):
        asset = GeneratedImage.objects.create(user=self.other, prompt="Private")
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("set_asset_publication", args=["image", asset.pk]),
            data=json.dumps({"publish": True}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_completed_reel_can_be_published_by_owner(self):
        video = GeneratedVideo.objects.create(
            user=self.user,
            category="Shoe",
            product_name="Runner",
            duration="4",
            status=GeneratedVideo.STATUS_DONE,
            video_url="/media/reels/ready.mp4",
        )
        self.client.force_login(self.user)
        response = self.client.post(reverse("publish_reel", args=[video.pk]))
        self.assertEqual(response.status_code, 200)
        video.refresh_from_db()
        self.assertTrue(video.is_published)

    def test_reel_rejects_invalid_duration_and_corrupt_image(self):
        self.client.force_login(self.user)
        invalid_duration = self.client.post(reverse("submit_reel"), {
            "category": "Shoe", "duration": "9", "caption_style": "auto",
            "product_image": valid_png(),
        })
        self.assertEqual(invalid_duration.status_code, 400)

        corrupt = SimpleUploadedFile("broken.png", b"not an image", content_type="image/png")
        bad_file = self.client.post(reverse("submit_reel"), {
            "category": "Shoe", "duration": "4", "caption_style": "auto",
            "product_image": corrupt,
        })
        self.assertEqual(bad_file.status_code, 400)

    @patch("studio.views.start_pipeline_thread")
    def test_valid_reel_is_queued_with_supported_duration(self, start_thread):
        self.client.force_login(self.user)
        with tempfile.TemporaryDirectory() as directory:
            with override_settings(MEDIA_ROOT=directory):
                response = self.client.post(reverse("submit_reel"), {
                    "category": "Watch", "duration": "8", "caption_style": "auto",
                    "product_image": valid_png(),
                })
        self.assertEqual(response.status_code, 200)
        video = GeneratedVideo.objects.get(pk=response.json()["video_id"])
        self.assertEqual(video.duration, "8")
        self.assertEqual(video.status, GeneratedVideo.STATUS_PENDING)
        start_thread.assert_called_once()

    @patch("studio.services.variation_generator.generate_variations", side_effect=RuntimeError("/secret/path provider error"))
    def test_pipeline_failure_is_sanitized(self, _generate):
        video = GeneratedVideo.objects.create(
            user=self.user, category="Shoe", product_name="Runner", duration="4",
        )
        run_pipeline(video.pk, "/tmp/no-file.png", "Shoe", "4")
        video.refresh_from_db()
        self.assertEqual(video.status, GeneratedVideo.STATUS_FAILED)
        self.assertNotIn("/secret/path", video.error_message)
