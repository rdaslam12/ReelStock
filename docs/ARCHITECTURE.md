# ReelStock Architecture

ReelStock combines hosted image inference with local product-media composition in a Django application. Its central workflow is creation → owned draft → publication → discovery and reuse. The architecture keeps inference and rendering in `studio/services/`, while Django applications manage accounts, asset metadata, creator interactions, credits, and staff operations.

## Application boundaries

| Application | Responsibilities and entry points |
| --- | --- |
| `core` | `GeneratedImage`, `GeneratedVideo`, profiles, blog, and shared social models; account/password-reset flows; Google sign-in entry; homepage and blog views |
| `studio` | `/generate/`, `/create/`, and `/my-assets/`; generation, status, and owner-scoped publication endpoints |
| `libraryapp` | `/library/`; asset detail, creator profiles, ratings, comments/reactions, follows, bookmarks, collections, notifications, and Trending |
| `wallet` | Wallet and transaction models; demo credit requests, basket pricing, file retrieval, and ZIP download checkout |
| `moderation` | `/admin-panel/`; staff authentication/session handling, user/asset review, credit approvals, featured/trending curation, blog management, and action logs |

`reelstock/` composes these applications through settings, middleware, and URL routing. Django templates and vanilla JavaScript provide the browser interface, including JSON requests for generation and social actions. These are application modules in one process, sharing the ORM and database.

## Still-image inference

`POST /generate/image/` accepts an authenticated creator's prompt, style, and aspect-ratio selection. The view validates the input before delegating to `studio/services/image_provider.py`.

1. The provider combines prompt and style and calls the configured Cloudflare Workers AI model, defaulting to `@cf/black-forest-labs/flux-1-schnell`.
2. The HTTP request uses bearer authentication, a configurable timeout, and a payload containing the prompt and four inference steps.
3. The service decodes the base64 image response, applies a watermark, and writes the file under `media/generated/`.
4. The view creates an owned `GeneratedImage` with `is_saved=True` and `is_published=False`, and returns its identifier and media URL.
5. The creator can publish using the asset identifier; the publication query includes the current user, preventing publication of another creator's asset.

The implementation retains the class name `HuggingFaceImageProvider` for compatibility with existing imports, but this class makes Cloudflare requests. Hugging Face remains a separate integration in the reel pipeline.

The aspect-ratio selection is validated and stored in metadata, but the current Cloudflare payload does not pass output dimensions. The selected ratio is therefore not enforced by the provider request.

Known provider errors raise `ImageGenerationError` and produce HTTP 503 with a user-facing explanation. Unexpected failures are logged and return a generic error. No placeholder asset is created in place of a failed generation.

## Product reel pipeline

`POST /reel/submit/` verifies authentication, product category, a 4/6/8 second duration, caption style, file extension, decoded image format, and the 15 MB size limit. Accepted uploads are saved under `media/reel_inputs/`; a `GeneratedVideo` starts with `status=pending` and `is_published=False`.

`start_pipeline_thread()` launches a named daemon thread. `run_pipeline()` coordinates the following services:

| Service | Work performed |
| --- | --- |
| `background_remover.py` | Produce an RGBA product cutout using optional local `rembg`, optional hosted background removal, or OpenCV GrabCut |
| `scene_generator.py` | Select five category-specific empty-scene prompts and generate backgrounds through optional hosted inference or local rendering |
| `compositor.py` | Place the product into scenes with scale/position rules, shadows, rim lighting, color adjustment, and optional reflections |
| `variation_generator.py` | Prepare an opening frame from the original upload, coordinate removal/scenes/compositing, and save six PNG frames with safe scene-name slugs |
| `reel_assembler.py` | Allocate frames, render camera motion/transitions/captions/watermarks, encode MP4, and attempt browser-oriented transcoding |
| `reel_pipeline.py` | Persist processing status, stage messages, output references, caption segments, fallback notes, and failure state |

### Inference and fallback boundaries

Background removal tries `rembg` first. If unavailable or unsuccessful, a configured `HF_API_TOKEN` enables an HTTP request to the Hugging Face `briaai/RMBG-2.0` endpoint. OpenCV GrabCut provides the local fallback, with morphology and edge feathering. If segmentation fails, its fallback mask can retain the original image rather than isolate the product.

Scene generation uses `huggingface_hub.InferenceClient` with `provider="auto"`, the configured model and timeout, and default model `black-forest-labs/FLUX.1-schnell`. Scene prompts request empty vertical backgrounds; the uploaded product image is not sent to this text-to-image stage. The separate hosted background-removal stage does send the uploaded image when selected.

Each failed or unconfigured scene request falls back to a locally rendered gradient with grain, vignette, and spotlight. A callback marks that degradation in the job's progress and completion note. Hosted inference is therefore optional for reel completion, while the standalone still-image path requires Cloudflare.

### Assembly and job lifecycle

The assembler renders 576 × 1024 frames at 24 fps. Shot holds and transitions share a total frame budget for the selected duration. Camera movement uses image zoom/pan transforms; transitions include zoom dissolves, pans, blur fades, flashes, and crossfades. Caption segments are built from product/category templates and rendered as animated overlays; they do not use a language model or speech transcription.

OpenCV writes the initial `mp4v` file. The service locates system FFmpeg or the `imageio-ffmpeg` executable and attempts H.264 baseline encoding with `yuv420p`, fast-start metadata, and the selected duration. If transcoding fails, it retains the OpenCV output; decoding then depends on the browser's codec support. The rendering path makes no hosted video-generation request.

The database lifecycle is `pending` → `processing` → `done`, or `failed` on an exception. During processing, the existing `error_message` column carries stage text; on completion it may carry a scene-fallback note. The browser polls `/reel/status/<id>/`, which restricts lookup to the owner. Full exceptions are logged server-side; failed jobs retain their records with a generic message.

Completed reels remain unpublished until an owner publishes them. Publication requires a completed record with a playback reference. There is no durable job queue, retry scheduler, or recovery of interrupted daemon threads.

## Asset lifecycle and discovery

`GeneratedImage` records the creator, prompt, style, selected aspect ratio, file/URL references, publication state, price, and view count. `GeneratedVideo` adds source-image references, processing status, duration, and caption configuration/script. My Assets lists the creator's saved images and completed reels.

Public Library and detail queries require published assets; videos must also have `status=done`. Library pages contain up to 12 items, with text search and style/category filtering. Creator profiles apply the same publication restrictions.

Trending combines staff overrides with a score from the last seven days of views, comments, and ratings. When a media type has no ranked or curated results, it falls back to recent published assets. It is an application-level engagement ranking, not a learned recommendation model.

Social endpoints validate published targets. Ratings are unique per user and asset; comment replies are limited to one level. Collections use an explicit public/private flag and owner checks. Publication and collection visibility apply to application responses, not filesystem access controls.

## Credits, downloads, and moderation

Reel Coins are internal demo credits with no implemented payment settlement. Users request credits; staff approve or reject requests. Wallet changes have transaction records.

The download basket stores a price snapshot for each item. Checkout builds the ZIP in memory and verifies that all files can be read before debiting credits. It then uses a Django database transaction to recheck the basket and balance, record the debit, and clear the basket. Although the code requests row locks, SQLite does not supply the row-level locking semantics of a server database; this design does not establish concurrent checkout scalability.

The custom moderation area uses a separate staff session cookie, active staff/superuser checks, and superuser-only controls for role changes. Moderation services record actions such as account restriction, unpublishing, credit adjustments, and curation. The reports page aggregates platform activity; there is no user-submitted abuse-report model or workflow.

## Authentication and configuration

Django handles passwords, sessions, CSRF protection, password validation, and password-reset views. django-allauth handles Google OAuth with Django Sites. The Google entry point requires a Google SocialApp attached to the configured `SITE_ID`; client credentials are stored in that database record. Token storage is disabled by `SOCIALACCOUNT_STORE_TOKENS=False`.

For local use, configure the Site domain as `127.0.0.1:8000`, attach the SocialApp, and authorize `http://127.0.0.1:8000/accounts/google/login/callback/`. Callback generation uses the incoming request, so a different hostname or scheme needs corresponding provider configuration.

[`.env.example`](../.env.example) lists settings for Django, Cloudflare still images, optional Hugging Face reel inference, email, and application logging. `python-dotenv` loads the root `.env` with `override=True`, so its values take precedence over existing environment values. Keep secrets out of version control.

## Persistence and deployment assumptions

SQLite resides at `BASE_DIR / db.sqlite3`. It holds application data, job state, Django Sites, and SocialApp configuration. Media files are stored separately:

| Directory | Contents |
| --- | --- |
| `media/generated/` | Generated still images |
| `media/reel_inputs/` | Uploaded product photos |
| `media/reel_frames/` | Opening and composited PNG frames |
| `media/reels/` | Completed MP4 files |

The database, `.env`, and media are Git-ignored local state. Backups need both database records and the referenced media; migrating a fresh database does not restore assets or OAuth configuration. The implementation retains uploaded sources and scene frames without an automated retention policy.

Current operation assumes one node with a writable filesystem, local CPU/media codecs, and optional outbound inference access. Still-image generation occupies its HTTP request; reel work runs inside the application process. Process termination can leave a pending/processing record without an executing job. No worker pool, admission control, durable queue, object storage, or distributed coordination is configured.

The checked-in settings are for local development: `DEBUG=True`, `ALLOWED_HOSTS=['*']`, SQLite, console email by default, and Django media serving. Files under `/media/` are served without asset-level authorization, including unpublished outputs. Public deployment requires explicit security/host configuration, appropriate media serving and access controls, and a backup policy. WSGI and ASGI entry points exist, but no production deployment configuration is supplied.

## Verification scope

Run `python manage.py check` and `python manage.py test` from the repository root. Tests exercise accounts/redirects, Google configuration routing and error display, draft ownership/publication, upload validation, mocked reel submission and pipeline failure, Library filtering/pagination, collection/social access, download charging, and staff operations.

Tests use mocks and temporary media where appropriate. They do not verify live inference quality, an interactive Google authorization, or a complete rendering benchmark. Provider model IDs, timeouts, status logging, and scene fallback handling are implemented operational controls; model training, evaluation tracking, a model registry, and automated model rollout are not part of this repository.
