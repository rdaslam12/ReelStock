"""
Small image generation helper for the Generate page.

This version uses Cloudflare Workers AI instead of Hugging Face, while keeping
the same public interface so the rest of the app does not need to change.
"""
from __future__ import annotations

import base64
import logging
from io import BytesIO
from pathlib import Path
from typing import Dict, Tuple
from uuid import uuid4

import requests
from django.conf import settings

from .watermark import watermark_image_bytes

logger = logging.getLogger(__name__)


class ImageGenerationError(Exception):
    """Raised when the external image provider cannot return an image."""


class HuggingFaceImageProvider:
    """
    Backward-compatible provider class name.

    The app may already import HuggingFaceImageProvider elsewhere, so we keep
    the class name the same even though it now uses Cloudflare Workers AI.
    """

    def __init__(self) -> None:
        self.account_id = getattr(settings, "CLOUDFLARE_ACCOUNT_ID", "")
        self.api_token = getattr(settings, "CLOUDFLARE_AI_TOKEN", "")
        self.model = getattr(
            settings,
            "CLOUDFLARE_IMAGE_MODEL",
            "@cf/black-forest-labs/flux-1-schnell",
        )
        self.timeout = getattr(settings, "CLOUDFLARE_IMAGE_TIMEOUT", 90)

        self.endpoint = (
            f"https://api.cloudflare.com/client/v4/accounts/"
            f"{self.account_id}/ai/run/{self.model}"
        )

    def generate_image(self, prompt: str, style: str, aspect_ratio: str) -> Dict[str, str]:
        if not self.account_id or not self.api_token:
            raise ImageGenerationError(
                "Image generation is temporarily unavailable because the AI provider is not configured."
            )

        full_prompt = self._build_prompt(prompt, style)

        image_bytes, content_type = self._request_image(
            prompt=full_prompt,
        )
        image_url = self._save_image(image_bytes=image_bytes, content_type=content_type)

        return {
            "image_url": image_url,
            "prompt_used": full_prompt,
        }

    def _build_prompt(self, prompt: str, style: str) -> str:
        if style:
            return f"{prompt}, {style} style"
        return prompt

    def _dimensions_for_ratio(self, aspect_ratio: str) -> Tuple[int, int]:
        dimension_map = {
            "1:1": (768, 768),
            "16:9": (1024, 576),
            "9:16": (576, 1024),
        }
        return dimension_map.get(aspect_ratio, (768, 768))

    def _request_image(self, prompt: str) -> Tuple[bytes, str]:
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

        payload = {
            "prompt": prompt,
            "steps": 4,
        }

        try:
            response = requests.post(
                self.endpoint,
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            raise ImageGenerationError(
                "The image provider timed out while generating your image. Please try again in a moment."
            ) from exc
        except requests.RequestException as exc:
            logger.exception("Cloudflare image request failed")
            raise ImageGenerationError(
                "The image provider could not generate an image right now. Please try again shortly."
            ) from exc

        if not response.ok:
            logger.warning(
                "Cloudflare image request failed: status=%s body=%s",
                response.status_code,
                response.text[:500],
            )
            raise ImageGenerationError(
                "The image provider could not generate an image right now. Please try again shortly."
            )

        try:
            data = response.json()
        except ValueError as exc:
            logger.exception("Cloudflare returned invalid JSON")
            raise ImageGenerationError(
                "The image provider returned an unexpected response."
            ) from exc

        image_b64 = data.get("result", {}).get("image")

        if not image_b64:
            logger.warning("Cloudflare response did not contain image data")
            raise ImageGenerationError(
                "The image provider returned an unexpected response."
            )

        try:
            image_bytes = base64.b64decode(image_b64)
        except Exception as exc:
            logger.exception("Could not decode Cloudflare image")
            raise ImageGenerationError(
                "The generated image could not be processed."
            ) from exc

        return image_bytes, "image/jpeg"

    def _image_to_bytes(self, image) -> Tuple[bytes, str]:
        buffer = BytesIO()
        image_format = (getattr(image, "format", None) or "PNG").upper()

        if image_format == "JPEG":
            content_type = "image/jpeg"
        elif image_format == "WEBP":
            content_type = "image/webp"
        else:
            image_format = "PNG"
            content_type = "image/png"

        image.save(buffer, format=image_format)
        return buffer.getvalue(), content_type

    def _save_image(self, image_bytes: bytes, content_type: str) -> str:
        extension = self._extension_from_content_type(content_type)
        image_format = self._format_from_content_type(content_type)

        output_dir = Path(settings.MEDIA_ROOT) / "generated"
        output_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{uuid4().hex}{extension}"
        output_path = output_dir / filename
        image_bytes = watermark_image_bytes(image_bytes, image_format)
        output_path.write_bytes(image_bytes)

        return f"{settings.MEDIA_URL}generated/{filename}"

    def _extension_from_content_type(self, content_type: str) -> str:
        content_type = (content_type or "").lower()

        if "jpeg" in content_type or "jpg" in content_type:
            return ".jpg"
        if "webp" in content_type:
            return ".webp"
        return ".png"

    def _format_from_content_type(self, content_type: str) -> str:
        content_type = (content_type or "").lower()

        if "jpeg" in content_type or "jpg" in content_type:
            return "JPEG"
        if "webp" in content_type:
            return "WEBP"
        return "PNG"