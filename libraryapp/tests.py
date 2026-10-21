import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import AssetComment, AssetRating, Collection, GeneratedImage


class LibrarySocialTests(TestCase):
    def setUp(self):
        self.creator = User.objects.create_user("artist", password="StrongPass!234")
        self.viewer = User.objects.create_user("viewer", password="StrongPass!234")
        self.asset = GeneratedImage.objects.create(
            user=self.creator,
            prompt="Published image",
            title="Published image",
            image_url="/static/img/placeholder.png",
            is_published=True,
        )

    def test_library_hides_drafts_and_paginates(self):
        GeneratedImage.objects.create(user=self.creator, prompt="Private", is_published=False)
        for index in range(13):
            GeneratedImage.objects.create(
                user=self.creator,
                prompt=f"Public {index}",
                image_url="/static/img/placeholder.png",
                is_published=True,
            )
        response = self.client.get(reverse("library"), {"type": "images"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["assets"]), 12)
        self.assertEqual(response.context["assets"].paginator.count, 14)

    def test_rating_updates_instead_of_duplicating(self):
        self.client.force_login(self.viewer)
        url = reverse("rate_asset")
        for score in (3, 5):
            response = self.client.post(
                url,
                data=json.dumps({"asset_type": "image", "asset_id": self.asset.pk, "score": score}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)
        self.assertEqual(AssetRating.objects.count(), 1)
        self.assertEqual(AssetRating.objects.get().score, 5)

    def test_replies_are_limited_to_one_level(self):
        parent = AssetComment.objects.create(
            user=self.creator, asset_type="image", asset_id=self.asset.pk, body="Parent",
        )
        reply = AssetComment.objects.create(
            user=self.viewer, asset_type="image", asset_id=self.asset.pk, parent=parent, body="Reply",
        )
        self.client.force_login(self.viewer)
        response = self.client.post(
            reverse("post_comment"),
            data=json.dumps({
                "asset_type": "image", "asset_id": self.asset.pk,
                "parent_id": reply.pk, "body": "Nested reply",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_public_collection_is_public_and_private_collection_is_not(self):
        public = Collection.objects.create(user=self.creator, name="Public", is_public=True)
        private = Collection.objects.create(user=self.creator, name="Private", is_public=False)
        self.assertEqual(self.client.get(reverse("collection_detail", args=[public.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("collection_detail", args=[private.pk])).status_code, 404)

    def test_self_follow_is_rejected(self):
        self.client.force_login(self.viewer)
        response = self.client.post(
            reverse("toggle_follow"),
            data=json.dumps({"username": self.viewer.username}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_creator_and_notification_pages_render(self):
        self.assertEqual(
            self.client.get(reverse("creator_profile", args=[self.creator.username])).status_code,
            200,
        )
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("notifications")).status_code, 200)
