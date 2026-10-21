from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from PIL import Image, ImageDraw

from core.models import (
    AssetComment,
    AssetRating,
    Bookmark,
    Collection,
    CollectionItem,
    Follow,
    GeneratedImage,
    UserProfile,
)


CREATORS = [
    ("demo_nova", "Nova", "Hart", "Dhaka", "Product imagery with dramatic studio light."),
    ("demo_mira", "Mira", "Chen", "Singapore", "Minimal compositions, warm color, and clean detail."),
    ("demo_atlas", "Atlas", "Reed", "London", "Editorial product concepts for bold brands."),
    ("demo_sora", "Sora", "Kim", "Seoul", "Playful AI art and polished campaign studies."),
]

ASSETS = [
    ("demo_nova", "Midnight Chronograph", "A luxury chronograph on a charcoal pedestal", "Realistic", (20, 28, 52), (89, 111, 220), 40),
    ("demo_nova", "Neon Runner", "A modern running shoe under violet rim lighting", "Digital Art", (44, 15, 66), (237, 65, 129), 45),
    ("demo_mira", "Ceramic Calm", "A sculptural ceramic bottle in a quiet cream studio", "Minimalist", (225, 211, 188), (158, 121, 90), 40),
    ("demo_mira", "Amber Fragrance", "An amber perfume bottle with soft window light", "Realistic", (72, 38, 22), (238, 157, 72), 50),
    ("demo_atlas", "Chrome Headphones", "Chrome headphones in a futuristic blue campaign", "Digital Art", (8, 36, 57), (32, 180, 205), 55),
    ("demo_atlas", "Monolith Bag", "A black leather bag on a red editorial set", "Realistic", (47, 8, 16), (196, 42, 65), 50),
    ("demo_sora", "Citrus Spark", "A bright citrus drink with energetic splashes", "Anime", (240, 111, 35), (255, 214, 72), 40),
    ("demo_sora", "Future Skincare", "A pearl skincare jar floating in a lavender scene", "Digital Art", (97, 75, 145), (213, 190, 255), 45),
]


class Command(BaseCommand):
    help = "Create a small, idempotent public demo catalog without clearing existing data."

    def handle(self, *args, **options):
        users = {}
        for username, first_name, last_name, location, bio in CREATORS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": f"{username}@example.invalid",
                },
            )
            if created:
                user.set_unusable_password()
                user.save(update_fields=["password"])
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.location = location
            profile.bio = bio
            profile.needs_profile_completion = False
            profile.save(update_fields=["location", "bio", "needs_profile_completion"])
            users[username] = user

        demo_dir = Path(settings.MEDIA_ROOT) / "demo"
        demo_dir.mkdir(parents=True, exist_ok=True)
        assets = []
        for index, (username, title, prompt, style, top, bottom, price) in enumerate(ASSETS, start=1):
            filename = f"seed_{index:02d}.png"
            output_path = demo_dir / filename
            if not output_path.exists():
                self._make_demo_image(output_path, title, style, top, bottom)

            asset, _ = GeneratedImage.objects.update_or_create(
                user=users[username],
                title=title,
                defaults={
                    "prompt": prompt,
                    "style": style,
                    "aspect_ratio": "1:1",
                    "image_file": f"demo/{filename}",
                    "image_url": f"{settings.MEDIA_URL}demo/{filename}",
                    "is_saved": True,
                    "is_published": True,
                    "coin_price": price,
                    "view_count": 12 + index * 7,
                },
            )
            assets.append(asset)

        user_list = list(users.values())
        for follower, following in zip(user_list, user_list[1:] + user_list[:1]):
            Follow.objects.get_or_create(follower=follower, following=following)

        for index, asset in enumerate(assets):
            rater = user_list[(index + 1) % len(user_list)]
            AssetRating.objects.update_or_create(
                user=rater,
                asset_type="image",
                asset_id=asset.pk,
                defaults={"score": 4 + (index % 2)},
            )
            AssetComment.objects.get_or_create(
                user=rater,
                asset_type="image",
                asset_id=asset.pk,
                body="Great lighting and a strong campaign-ready composition.",
            )
            Bookmark.objects.get_or_create(user=rater, asset_type="image", asset_id=asset.pk)

        collection, _ = Collection.objects.get_or_create(
            user=users["demo_mira"],
            name="Demo Campaign Picks",
            defaults={"description": "A public sample collection for exploring ReelStock.", "is_public": True},
        )
        if not collection.is_public:
            collection.is_public = True
            collection.save(update_fields=["is_public"])
        for asset in assets[:4]:
            CollectionItem.objects.get_or_create(
                collection=collection,
                asset_type="image",
                asset_id=asset.pk,
            )

        self.stdout.write(self.style.SUCCESS(
            f"Demo catalog ready: {len(users)} creators, {len(assets)} published images, ratings, comments, follows, bookmarks, and a public collection."
        ))

    @staticmethod
    def _make_demo_image(path, title, style, top, bottom):
        width = height = 900
        image = Image.new("RGB", (width, height))
        pixels = image.load()
        for y in range(height):
            ratio = y / (height - 1)
            color = tuple(int(top[i] + (bottom[i] - top[i]) * ratio) for i in range(3))
            for x in range(width):
                pixels[x, y] = color

        draw = ImageDraw.Draw(image, "RGBA")
        draw.ellipse((150, 105, 750, 705), fill=(255, 255, 255, 26), outline=(255, 255, 255, 95), width=4)
        draw.rounded_rectangle((245, 275, 655, 625), radius=70, fill=(9, 15, 28, 150), outline=(255, 255, 255, 120), width=5)
        draw.text((70, 730), title.upper(), fill=(255, 255, 255, 245), stroke_width=1, stroke_fill=(0, 0, 0, 100))
        draw.text((72, 775), f"REELSTOCK · {style}", fill=(255, 255, 255, 185))
        image.save(path, "PNG", optimize=True)
