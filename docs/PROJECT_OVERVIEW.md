# ReelStock Project Architecture Overview

## Purpose

ReelStock is an AI-powered product media platform. Users can generate images from text prompts or upload product photos to create commercial-style video reels. Content can be published to a community library.

## Technology stack

- Backend: Django 4.2, SQLite for local development, Python 3.10+
- Frontend: Bootstrap 5.3 and custom CSS
- AI images and scenes: Hugging Face Inference API with FLUX.1-schnell by default
- Product reel assembly: Pillow, OpenCV and FFmpeg/imageio-ffmpeg
- Optional video provider: fal.ai Kling image-to-video integration
- Authentication: Django authentication and Google OAuth through django-allauth

## Django apps

### `core/`

- Models include user profiles, generated assets, blog posts, featured assets, and social features.
- Views cover the homepage, authentication, account/profile pages, password reset, and blog pages.

### `studio/`

- `services/image_provider.py`: Hugging Face text-to-image generation
- `services/background_remover.py`: background removal with rembg, Hugging Face, or GrabCut fallbacks
- `services/scene_generator.py`: scene/background generation
- `services/compositor.py`: product compositing
- `services/variation_generator.py`: reel-frame generation
- `services/reel_assembler.py`: local video assembly
- `services/reel_pipeline.py`: Reel Maker orchestration
- `services/video_provider.py`: text-to-video and optional fal.ai provider integrations
- Views cover image generation, Reel Maker, My Assets, saving, publishing, and generation status.

### `libraryapp/`

Public library browsing, asset details, creator profiles, following, comments, reactions, ratings, bookmarks, collections, notifications, and trending content.

### `wallet/`

Reel Coin wallets, transaction history, coin requests, the download basket, and downloads.

### `moderation/`

Staff-only dashboard, platform analytics, asset and user moderation, wallet administration, engagement controls, and content tools. There is no user-submitted asset-report workflow in the current schema.

## Key generation flows

### Image generation

1. The browser posts a prompt to `/generate/image/`.
2. `HuggingFaceImageProvider` generates and stores the image under `media/generated/`.
3. The result is saved as the signed-in creator's private draft and can optionally be published.

### Product reel generation

1. The browser posts a product image to `/reel/submit/`.
2. The upload is stored under `media/reel_inputs/`.
3. The local Reel Maker pipeline removes the background, generates scene plates, composites the product, and assembles an MP4.
4. Intermediate frames are stored under `media/reel_frames/`; completed reels are stored under `media/reels/`.
5. The browser polls `/reel/status/<id>/` and can publish a completed reel.

## Local media

- `media/generated/`: AI-generated images
- `media/generated_videos/`: text-to-video outputs
- `media/reel_inputs/`: uploaded product photos
- `media/reel_frames/`: intermediate composited frames
- `media/reels/`: completed product reels

The entire `media/` tree is local runtime data and is excluded from version control. Django serves it in debug mode through `/media/`.

## Administration

- `/admin/`: standard Django administration
- `/admin-panel/`: custom staff moderation dashboard

## Environment variables

The placeholder-only [`.env.example`](../.env.example) documents all environment variables currently read by the project. Local secrets belong in `.env`, which is excluded from version control.

## Local setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```
