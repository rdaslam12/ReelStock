from __future__ import annotations

import json
import logging
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST
from PIL import Image, UnidentifiedImageError

from core.models import GeneratedImage, GeneratedVideo
from .services.image_provider import HuggingFaceImageProvider, ImageGenerationError
from .services.reel_pipeline import start_pipeline_thread

logger = logging.getLogger(__name__)

IMAGE_STYLES = {"Realistic", "Anime", "Oil Painting", "Digital Art"}
IMAGE_ASPECT_RATIOS = {"1:1", "16:9", "9:16"}
REEL_CATEGORIES = {"Shoe", "Watch", "Bag", "Other"}
REEL_DURATIONS = {"4", "6", "8"}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


def _absolute_url(request, url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    if not url.startswith("/"):
        url = "/" + url
    return request.build_absolute_uri(url)


@login_required
def create(request):
    return render(request, "studio/create.html")


@login_required
def my_assets(request):
    tab    = request.GET.get("tab", "all")
    if tab not in {"all", "images", "videos"}:
        tab = "all"
    images = GeneratedImage.objects.filter(user=request.user, is_saved=True)
    videos = GeneratedVideo.objects.filter(user=request.user, is_saved=True, status="done")
    return render(request, "studio/my_assets.html", {
        "images": images, "videos": videos,
        "tab": tab,
        "total_images": images.count(),
        "total_videos": videos.count(),
        "total": images.count() + videos.count(),
    })


@login_required
def prompt_to_image(request):
    return render(request, "studio/prompt_to_image.html")


@require_POST
@login_required
def generate_image(request):
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON."}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"success": False, "error": "Invalid request."}, status=400)

    prompt       = (payload.get("prompt") or "").strip()
    style        = (payload.get("style") or "Realistic").strip()
    aspect_ratio = (payload.get("aspect_ratio") or "1:1").strip()

    if len(prompt) < 3:
        return JsonResponse({"success": False, "error": "Please enter a more descriptive prompt."}, status=400)
    if len(prompt) > 1200:
        return JsonResponse({"success": False, "error": "Please keep the prompt under 1,200 characters."}, status=400)
    if style not in IMAGE_STYLES:
        return JsonResponse({"success": False, "error": "Please choose a valid image style."}, status=400)
    if aspect_ratio not in IMAGE_ASPECT_RATIOS:
        return JsonResponse({"success": False, "error": "Please choose a valid aspect ratio."}, status=400)

    try:
        provider = HuggingFaceImageProvider()
        result = provider.generate_image(prompt=prompt, style=style, aspect_ratio=aspect_ratio)
    except ImageGenerationError as exc:
        logger.warning("Image generation failed for user_id=%s: %s", request.user.pk, exc)
        return JsonResponse({"success": False, "error": str(exc)}, status=503)
    except Exception:
        logger.exception("Unexpected image generation failure for user_id=%s", request.user.pk)
        return JsonResponse({"success": False, "error": "Image generation failed. Please try again."}, status=503)

    image_url = result.get("image_url", "") if isinstance(result, dict) else ""
    if not image_url:
        logger.error("Image provider returned a malformed result for user_id=%s", request.user.pk)
        return JsonResponse({
            "success": False,
            "error": "The image provider returned an unusable result. Please try again.",
        }, status=503)
    media_prefix = getattr(settings, "MEDIA_URL", "/media/")
    image_file_name = image_url[len(media_prefix):].lstrip("/") if image_url.startswith(media_prefix) else ""
    image = GeneratedImage.objects.create(
        user=request.user,
        prompt=prompt,
        style=style,
        aspect_ratio=aspect_ratio,
        image_url=image_url,
        is_saved=True,
        is_published=False,
    )
    if image_file_name:
        image.image_file.name = image_file_name
        image.save(update_fields=["image_file"])

    return JsonResponse({
        "success": True,
        "asset_id": image.pk,
        "image_url": image.media_url,
        "prompt_used": result.get("prompt_used", prompt),
        "style": style,
        "aspect_ratio": aspect_ratio,
    })


@require_POST
@login_required
def save_image(request):
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON."}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"success": False, "error": "Invalid request."}, status=400)

    asset_id = payload.get("asset_id")
    publish      = bool(payload.get("publish", False))

    if not asset_id:
        return JsonResponse({"success": False, "error": "No generated image was selected."}, status=400)

    img = get_object_or_404(GeneratedImage, pk=asset_id, user=request.user, is_saved=True)
    img.is_published = publish
    img.save(update_fields=["is_published"])
    detail_url = reverse("asset_detail", args=["image", img.pk]) if publish else ""
    return JsonResponse({
        "success": True,
        "id": img.pk,
        "published": publish,
        "detail_url": detail_url,
        "public_url": _absolute_url(request, detail_url) if detail_url else "",
    })





# ── Reel Maker ────────────────────────────────────────────────────────

@require_POST
@login_required
def submit_reel(request):
    category     = request.POST.get("category", "Other").strip()
    product_name = request.POST.get("product_name", "").strip()
    image_file   = request.FILES.get("product_image")

    if category not in REEL_CATEGORIES:
        return JsonResponse({"success": False, "error": "Please choose a valid product type."}, status=400)
    if category == "Other" and not product_name:
        return JsonResponse({"success": False, "error": "Please enter a product name."}, status=400)
    product_name = product_name or category
    if len(product_name) > 200:
        return JsonResponse({"success": False, "error": "Product name must be 200 characters or fewer."}, status=400)

    # Capture final duration. Valid values are exact target seconds.
    duration_str = (request.POST.get("duration") or "").strip()
    if duration_str not in REEL_DURATIONS:
        return JsonResponse({"success": False, "error": "Please choose a 4, 6, or 8 second duration."}, status=400)
    duration = duration_str
    caption_style = (request.POST.get("caption_style") or "auto").strip().lower()
    allowed_caption_styles = {
        "auto", "karaoke", "bounce", "slide_up", "typewriter",
        "zoom", "glitch", "fade_motion", "punch",
    }
    if caption_style not in allowed_caption_styles:
        return JsonResponse({"success": False, "error": "Please choose a valid caption style."}, status=400)

    if not image_file:
        return JsonResponse({"success": False, "error": "Please upload a product image."}, status=400)

    allowed_ext = {".jpg", ".jpeg", ".png", ".webp"}
    ext = Path(image_file.name).suffix.lower()
    if ext not in allowed_ext:
        return JsonResponse({"success": False, "error": "Only JPG, PNG, WEBP images are accepted."}, status=400)
    if image_file.size > MAX_UPLOAD_BYTES:
        return JsonResponse({"success": False, "error": "Image must be 15 MB or smaller."}, status=400)
    try:
        with Image.open(image_file) as uploaded_image:
            detected_format = (uploaded_image.format or "").upper()
            uploaded_image.verify()
        image_file.seek(0)
    except (UnidentifiedImageError, OSError, ValueError):
        return JsonResponse({"success": False, "error": "The uploaded image is corrupt or unreadable."}, status=400)
    if detected_format not in {"JPEG", "PNG", "WEBP"}:
        return JsonResponse({"success": False, "error": "Please upload a valid JPG, PNG, or WebP image."}, status=400)

    filename  = f"reel_input_{uuid4().hex}{ext}"
    upload_dir = Path(settings.MEDIA_ROOT) / "reel_inputs"
    upload_dir.mkdir(parents=True, exist_ok=True)
    save_path = upload_dir / filename

    try:
        with open(save_path, "wb") as f:
            for chunk in image_file.chunks():
                f.write(chunk)
    except OSError:
        logger.exception("Could not save reel upload for user_id=%s", request.user.pk)
        return JsonResponse({"success": False, "error": "The image could not be saved. Please try again."}, status=500)

    relative_url = f"{settings.MEDIA_URL}reel_inputs/{filename}"

    try:
        video = GeneratedVideo.objects.create(
            user=request.user,
            category=category,
            product_name=product_name,
            source_image=f"reel_inputs/{filename}",
            source_image_url=relative_url,
            status=GeneratedVideo.STATUS_PENDING,
            duration=duration,
            caption_style=caption_style,
        )
    except Exception:
        save_path.unlink(missing_ok=True)
        logger.exception("Could not create reel record for user_id=%s", request.user.pk)
        return JsonResponse({"success": False, "error": "The reel could not be queued. Please try again."}, status=500)

    logger.info(
        "submit_reel: queued video_id=%s category=%s source_image=%s duration=%s caption_style=%s",
        video.pk,
        category,
        video.source_image.name,
        duration,
        caption_style,
    )

    # Start the background processing thread with the optional duration
    try:
        start_pipeline_thread(
            video_id=video.pk,
            source_image_path=str(save_path),
            category=category,
            duration=duration,
        )
    except Exception:
        logger.exception("Could not start reel pipeline for video_id=%s", video.pk)
        video.status = GeneratedVideo.STATUS_FAILED
        video.error_message = "The reel could not be started. Please try again."
        video.save(update_fields=["status", "error_message"])
        return JsonResponse({"success": False, "error": video.error_message}, status=500)

    return JsonResponse({"success": True, "video_id": video.pk})


@login_required
def reel_status(request, video_id):
    """
    Returns pipeline status for frontend polling.

    Response schema:
      pending / processing:  {"status": "pending"|"processing", "stage": "<human message>"}
      done:                  {"status": "done", "video_url": "<url>"}
      failed:                {"status": "failed", "error": "<message>"}

    NOTE: We do NOT delete the record on failure so the user can see the
    error message. The frontend handles cleanup.
    """
    video = get_object_or_404(GeneratedVideo, pk=video_id, user=request.user)
    if video.status == GeneratedVideo.STATUS_DONE:
        if video.sync_video_file_from_url():
            video.save(update_fields=["video_file", "updated_at"])
            logger.info(
                "reel_status: backfilled video_file for video_id=%s from video_url=%s -> %s",
                video_id,
                video.video_url,
                video.video_file.name,
            )
        video_url = _absolute_url(request, video.playback_url)
        logger.debug(
            "reel_status: video_id=%s done playback_url=%s raw_video_url=%s video_file=%s",
            video_id,
            video_url,
            video.video_url,
            video.video_file.name if video.video_file else "",
        )
        return JsonResponse({
            "status": "done",
            "video_url": video_url,
            "media_url": video_url,
            "playback_url": video_url,
            "note": video.error_message,
        })

    if video.status == GeneratedVideo.STATUS_FAILED:
        error = video.error_message or "Generation failed — please try again."
        # Don't delete — just report failure so user can retry
        return JsonResponse({"status": "failed", "error": error})

    # pending or processing — include stage message for UI
    stage = video.error_message or ""  # repurposed as stage label during processing
    return JsonResponse({"status": video.status, "stage": stage})


@require_POST
@login_required
def publish_reel(request, video_id):
    video = get_object_or_404(GeneratedVideo, pk=video_id, user=request.user, status="done")
    changed = video.sync_video_file_from_url()
    if not video.playback_url:
        return JsonResponse({"success": False, "error": "No playable reel file was saved."}, status=400)

    video.is_published = True
    title = (request.POST.get("title") or "").strip()
    if title:
        video.title = title
    update_fields = ["is_published", "title", "updated_at"]
    if changed:
        update_fields.append("video_file")
    video.save(update_fields=update_fields)
    logger.info(
        "publish_reel: published video_id=%s playback_url=%s video_file=%s raw_video_url=%s",
        video_id,
        video.playback_url,
        video.video_file.name if video.video_file else "",
        video.video_url,
    )
    return JsonResponse({
        "success": True,
        "video_url": _absolute_url(request, video.playback_url),
        "playback_url": _absolute_url(request, video.playback_url),
        "detail_url": reverse("asset_detail", args=["video", video.pk]),
        "public_url": _absolute_url(request, reverse("asset_detail", args=["video", video.pk])),
    })


@require_POST
@login_required
def set_asset_publication(request, asset_type, asset_id):
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid request."}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"success": False, "error": "Invalid request."}, status=400)
    if not isinstance(payload.get("publish"), bool):
        return JsonResponse({"success": False, "error": "Invalid publication state."}, status=400)

    publish = payload["publish"]
    if asset_type == "image":
        asset = get_object_or_404(GeneratedImage, pk=asset_id, user=request.user, is_saved=True)
        if publish and not asset.media_url:
            return JsonResponse({"success": False, "error": "This image file is unavailable."}, status=400)
    elif asset_type == "video":
        asset = get_object_or_404(
            GeneratedVideo,
            pk=asset_id,
            user=request.user,
            is_saved=True,
            status=GeneratedVideo.STATUS_DONE,
        )
        if publish and not asset.playback_url:
            return JsonResponse({"success": False, "error": "This reel file is unavailable."}, status=400)
    else:
        raise Http404("Unknown asset type")

    asset.is_published = publish
    asset.save(update_fields=["is_published"])
    detail_url = reverse("asset_detail", args=[asset_type, asset.pk]) if publish else ""
    return JsonResponse({"success": True, "published": publish, "detail_url": detail_url})
