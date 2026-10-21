# Changelog

All notable changes to this project will be documented in this file.

## v5 – Product‑CGI Reel Maker (2026‑04‑29)

### Added

- Added a product reel pipeline with local Pillow/OpenCV compositing and video assembly: background removal, five scene compositions, shadows, rim lighting, optional reflections, camera motion, and transitions. Scene backgrounds can use hosted inference or a local gradient fallback. See the [current architecture](docs/ARCHITECTURE.md) for provider boundaries.
- Added duration selection to the Reel Maker UI. Users can choose an exact length (4 s, 6 s or 8 s), and the backend allocates a fixed frame budget across shots and transitions.
- Added a Step 3 card to the Reel Maker page for picking the duration and wired up the form submission to include this value.
- Updated the reel pipeline to accept an optional `duration` parameter and compute per‑frame hold duration dynamically.
- Extended `save_reel_to_media` to forward a custom `hold_duration` to the video assembler.
- Added documentation on environment variables and usage instructions to the README.
- Added this `CHANGELOG.md` to track future changes.

### Removed

- Removed the deprecated classic slideshow reel concept.  The Reel Maker now exclusively generates product‑CGI reels with motion and transitions.

### Changed

- Renumbered the steps in the Reel Maker UI to accommodate the new duration selection.
- Updated the progress bar and pipeline status tracker to reflect the new stage ordering.
