# ClipCraft — Stories & Stanza

A local web app that turns long-form video and audio into short-form, portrait-oriented social media reels.  
Three tools in one browser tab: generate subtitle-driven clips from a video, convert any full video to portrait, or build sequential audio reels from a static image — then publish directly to YouTube.

---

## Table of Contents

1. [Features](#features)
2. [How It Works](#how-it-works)
3. [Installation](#installation)
4. [Running the App](#running-the-app)
5. [Usage Guide](#usage-guide)
6. [YouTube Integration](#youtube-integration)
7. [Project Structure](#project-structure)
8. [API Reference](#api-reference)
9. [Configuration](#configuration)
10. [Troubleshooting](#troubleshooting)
11. [Changelog](#changelog)

---

## Features

### Clip Generator (/)
- **Portrait clip generation** — auto-converts landscape video to 1080×1920 (9:16) with side-by-side speaker layout
- **Subtitle-aware cutting** — clips snap to SRT cue boundaries so they never cut off mid-sentence
- **Auto-mode** — splits a video into equal windows snapped to the nearest subtitle cue; no manual selection needed
- **Manual cue selection** — browse all SRT cues and pick exactly which moments to clip
- **Thumbnail prepend** — optionally prepend a branded thumbnail image for a configurable duration (default 1.2 s)
- **Outro append** — automatically appends `ClipOutro.mp4` from the project root to every clip
- **Burnin subtitles** — subtitles rendered as overlaid PNG strips with word-highlight colour
- **Gallery** — preview, play, and manage all generated clips in the browser
- **YouTube bulk upload** — select multiple clips, set per-clip titles, shared description, and staggered publish schedule

### Portrait Converter (/convert) — *New*
- **Full-video portrait conversion** — converts an entire landscape video to 9:16 in one step (no cue selection needed)
- **Side-by-side speaker layout** — configurable split ratio (left/right speaker weight)
- **Optional SRT subtitles** — attach an SRT file to burn subtitles into the converted video
- **One-click download** — result clip appears in the output area with a direct download link

### Audio Clip Generator (/audioclips) — *New*
- **Image + audio → video reels** — combine a static portrait image with an audio file to produce sequential MP4 clips
- **Flexible slicing** — configure number of clips, clip duration (seconds), and start offset into the audio
- **Live preview** — duration preview updates in real time as settings change
- **Per-clip live downloads** — each clip becomes downloadable as soon as it finishes, without waiting for the full batch

### Navigation UX — *Improved*
- Sidebar restructured into a **Tools** section (cross-page links) and a **Workflow** section (numbered step dots with active/done progression)
- Step dots animate: completed steps turn green ✓, the active step highlights in brand colour

---

## How It Works

### Clip Generator

```
Video + SRT + Thumbnail
        │
   ┌────▼─────────────────────────────────────────────┐
   │  1. Upload (Flask /upload)                        │
   │     • Parses SRT into cue list                    │
   │     • Saves files to uploads/                     │
   └────┬─────────────────────────────────────────────┘
        │  cues JSON returned to browser
   ┌────▼─────────────────────────────────────────────┐
   │  2. Cue Selection (browser)                       │
   │     • Auto-mode: windows snapped to cues          │
   │     • Manual: user picks individual cues          │
   └────┬─────────────────────────────────────────────┘
        │  POST /make_clips
   ┌────▼─────────────────────────────────────────────┐
   │  3. Background Clip Generation (Flask thread)     │
   │     • moviepy_worker: crop, layout, subtitles     │
   │     • ffmpeg_prepend: thumbnail prepend           │
   │     • ffmpeg_prepend: outro append                │
   │     • Clips saved to clips/                       │
   └────┬─────────────────────────────────────────────┘
        │  job progress polled via /progress/<id>
   ┌────▼─────────────────────────────────────────────┐
   │  4. Gallery (browser)                             │
   │     • Loads clips from /clips/list                │
   │     • Preview, playback                           │
   └────┬─────────────────────────────────────────────┘
        │  upload via /youtube/upload
   ┌────▼─────────────────────────────────────────────┐
   │  5. YouTube Bulk Upload (Flask thread per clip)   │
   │     • OAuth 2.0 + PKCE via google-auth-oauthlib   │
   │     • Resumable MediaFileUpload (256 KB chunks)   │
   │     • Polled via /youtube/upload_progress/<id>    │
   └──────────────────────────────────────────────────┘
```

### Portrait Converter

```
Video (+ optional SRT)
        │
   ┌────▼──────────────────────────────┐
   │  POST /convert/upload             │
   │  • Saves video + SRT to uploads/  │
   └────┬──────────────────────────────┘
        │  POST /convert/start
   ┌────▼──────────────────────────────┐
   │  Background job (Flask thread)    │
   │  • make_portrait_full_video()     │
   │    – full landscape → 9:16 crop   │
   │    – optional SRT burn-in         │
   │  • Output saved to clips/         │
   └────┬──────────────────────────────┘
        │  polled via /progress/<id>
   ┌────▼──────────────────────────────┐
   │  Download result clip             │
   └───────────────────────────────────┘
```

### Audio Clip Generator

```
Static Image + Audio file
        │
   ┌────▼──────────────────────────────┐
   │  POST /audioclips/upload          │
   │  • Saves image + audio to uploads/│
   └────┬──────────────────────────────┘
        │  POST /audioclips/start
   ┌────▼──────────────────────────────┐
   │  Background job (Flask thread)    │
   │  For each clip i:                 │
   │  • make_audio_reel()              │
   │    – scale image to 9:16 canvas   │
   │    – slice audio[start..end]      │
   │    – combine → MP4                │
   │  • Clip available for download    │
   │    immediately after each batch   │
   └────┬──────────────────────────────┘
        │  polled via /progress/<id>
   ┌────▼──────────────────────────────┐
   │  Per-clip live download links     │
   └───────────────────────────────────┘
```

---

## Installation

### Prerequisites

- Python 3.9+
- ffmpeg installed and on `PATH`
- A Google Cloud project with the YouTube Data API v3 enabled (for the upload feature)

### Steps

```bash
# 1. Clone / download the project
cd "Social Media Clips"

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 3. Install Python dependencies
pip install -r requirements.txt

# YouTube upload dependencies
pip install google-auth-oauthlib google-api-python-client
```

---

## Running the App

```bash
source venv/bin/activate
python app.py
```

Open **http://localhost:8080** in your browser.

For production use with gunicorn:

```bash
gunicorn -w 2 -b 0.0.0.0:8080 app:app
```

> Note: clip generation uses background threads, so `--workers 1` or a thread-aware worker is recommended if running behind gunicorn.

---

## Usage Guide

### Clip Generator (/)

#### Step 1 — Upload

Drop or select three files:

| Field | Required | Notes |
|-------|----------|-------|
| Video | ✓ | `.mp4`, `.mov`, `.mkv`, `.webm`, `.avi` |
| Subtitles | ✓ | `.srt` or `.txt` in SRT format |
| Thumbnail | optional | `.png`, `.jpg`, `.jpeg`, `.webp` — prepended to each clip |

#### Step 2 — Cues

Configure generation settings, then choose clip sources:

| Setting | Default | Description |
|---------|---------|-------------|
| Max clips | 3 | Maximum number of clips to generate (1–20) |
| Auto-window | 45 s | Each auto-segment length before snap |
| Min duration | 30 s | Minimum clip length (padded symmetrically if shorter) |
| Max duration | — | Hard cap; centered trim applied if segment exceeds this |

**Auto mode** (no cues selected): divides the video into windows, snaps each window start to the nearest SRT cue, then snaps ends to the boundary of the cue that overlaps the calculated end time — so no clip ever cuts off mid-sentence.

**Manual mode**: tick individual SRT cue rows, then click **Create Clips**.

#### Step 3 — Generation

A progress bar tracks the background job. Each clip goes through:

1. `moviepy_worker.py` — crop to portrait, layout, subtitle burn-in
2. `ffmpeg_prepend.py` → `prepend_thumbnail()` — thumbnail prepend
3. `ffmpeg_prepend.py` → `append_outro()` — outro append from `ClipOutro.mp4`

#### Step 4 — Gallery

All generated clips are listed as cards. Click any card to play the clip in the browser. Hit **Refresh** to reload clips generated in previous sessions.

---

### Portrait Converter (/convert)

1. **Upload** — Drop a video file (required) and an optional SRT subtitle file
2. **Configure** — Adjust the left/right speaker split ratio using the visual slider; the diagram updates live
3. **Convert** — Click **Convert to Portrait**; a progress bar tracks the job
4. **Download** — When complete, a download button appears with the output file

> The converted file is also available in the main **Gallery** via `/clips/list`.

---

### Audio Clip Generator (/audioclips)

1. **Upload** — Drop a portrait image (PNG/JPG/WEBP) and an audio file (MP3/WAV/M4A/AAC/OGG)
2. **Configure** settings:

| Setting | Default | Description |
|---------|---------|-------------|
| Number of clips | 3 | How many sequential clips to generate (1–50) |
| Clip duration | 60 s | Length of each clip in seconds (min 5 s) |
| Start offset | 0 s | Skip this many seconds before the first clip |

The **Duration preview** (e.g. `60s × 3 clips = 3m 0s total`) updates live.

3. **Generate** — Click **Generate Audio Clips**; each clip appears as a download link as soon as it finishes, without waiting for the full batch
4. **Download** — Use the per-clip download buttons or wait for all to finish

---

## YouTube Integration

### One-time Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project → enable **YouTube Data API v3**
3. Create **OAuth 2.0 credentials** (Desktop app) → download JSON
4. Rename the downloaded file to `client_secrets.json` and place it in the project root
5. Add `http://localhost:8080/youtube/callback` to the OAuth redirect URIs

### Connecting Your Channel

In the **▶ YouTube** tab, click **Connect channel** and complete the Google sign-in. Credentials are stored in `yt_credentials.json` at the project root and auto-refreshed when they expire.

### Bulk Upload

1. Clips grid loads automatically — click clips to select them (red border = selected)
2. Use **Select all** / **Clear** as needed — a badge shows the count
3. Fill in a **title** for each selected clip
4. Optionally add a shared **description**
5. Choose **Publish now** or **Schedule for later**
   - When scheduling, the first clip is published at your chosen date/time; each subsequent clip is staggered **+1 day**
6. Click **Upload N clips** — a per-clip progress queue appears

---

## Project Structure

```
Clip Generator/
├── app.py                  # Flask server — routes, job orchestration, YouTube OAuth
├── moviepy_worker.py       # Portrait clip rendering, full-video converter, audio reel builder
├── ffmpeg_prepend.py       # ffmpeg wrappers: thumbnail prepend, outro append
├── utils.py                # Shared utility helpers
├── requirements.txt        # Python dependencies
│
├── client_secrets.json     # Google OAuth credentials (you provide — not committed)
├── yt_credentials.json     # Stored YouTube OAuth token (auto-created — not committed)
├── .yt_oauth_state         # Ephemeral PKCE state (auto-created — not committed)
├── ClipOutro.mp4           # Outro video appended to every clip (you provide)
│
├── uploads/                # Temporary storage for uploaded videos, SRTs, images, audio
├── clips/                  # Generated output clips (MP4)
│
├── static/
│   ├── css/app.css         # Full design system — dark navy theme, component styles, nav step dots
│   ├── js/app.js           # Clip Generator frontend logic (upload, cues, gallery, YouTube)
│   └── Logo.png            # Stories & Stanza brand logo
│
└── templates/
    ├── index.html          # Clip Generator page
    ├── convert.html        # Portrait Converter page  ← new
    └── audioclips.html     # Audio Clip Generator page  ← new
```

---

## API Reference

### Upload & Clip Generation

| Endpoint | Method | Description |
|----------|--------|-------------|
| `POST /upload` | multipart/form-data | Upload video, SRT, optional thumbnail. Returns cue list + file tokens. |
| `POST /make_clips` | JSON | Start background clip generation job. Returns `job_id`. |
| `GET /progress/<job_id>` | — | Poll job status, percent, clip list, errors. |
| `POST /cancel/<job_id>` | — | Signal cancellation to the running job. |
| `GET /clips/<filename>` | — | Serve a generated clip file. |
| `GET /clips/list` | — | List all `.mp4` files in `clips/`, newest first. |

#### `POST /make_clips` body

```json
{
  "video": "token.mp4",
  "srt": "token.srt",
  "selected_indices": [0, 2, 5],
  "max_clips": 3,
  "split_x_ratio": 0.5,
  "auto_window": 45,
  "auto_min_duration": 30,
  "max_duration": 90,
  "thumbnail": "token.jpg",
  "embed_thumbnail": true,
  "thumbnail_duration": 1.2
}
```

`selected_indices` — array of SRT cue indices to clip; pass `[]` for auto-mode.

#### `GET /progress/<job_id>` response

```json
{
  "status": "running | done | error | cancelled",
  "percent": 60,
  "clips": [{ "clip": "filename.mp4" }],
  "errors": [],
  "finished": false
}
```

---

### Portrait Converter

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /convert` | — | Render the Portrait Converter page. |
| `POST /convert/upload` | multipart/form-data | Upload video (required) + optional SRT. Returns file tokens. |
| `POST /convert/start` | JSON | Start full-video portrait conversion job. Returns `job_id`. |

#### `POST /convert/start` body

```json
{
  "video": "token.mp4",
  "srt": "token.srt",
  "split_x_ratio": 0.5
}
```

`srt` is optional. `split_x_ratio` controls where the left/right speaker boundary falls (0.1–0.9, default 0.5).

---

### Audio Clip Generator

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /audioclips` | — | Render the Audio Clip Generator page. |
| `POST /audioclips/upload` | multipart/form-data | Upload image + audio. Returns file tokens. |
| `POST /audioclips/start` | JSON | Start batch audio-reel generation job. Returns `job_id`. |

#### `POST /audioclips/start` body

```json
{
  "image": "token.png",
  "audio": "token.mp3",
  "num_clips": 3,
  "clip_duration": 60,
  "start_offset": 0
}
```

- `num_clips` — 1–50 (default 3)
- `clip_duration` — seconds per clip, minimum 5 (default 60)
- `start_offset` — seconds to skip before the first clip (default 0)

---

### YouTube

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /youtube/status` | — | Check OAuth configuration and authentication state. |
| `GET /youtube/auth` | — | Redirect to Google OAuth consent screen. |
| `GET /youtube/callback` | — | OAuth callback; stores credentials, redirects to `/?yt_connected=1`. |
| `POST /youtube/logout` | — | Delete stored credentials. |
| `POST /youtube/upload` | JSON | Start a background upload. Returns `upload_id`. |
| `GET /youtube/upload_progress/<id>` | — | Poll per-clip upload progress. |

#### `POST /youtube/upload` body

```json
{
  "clip": "filename.mp4",
  "title": "Episode 1 Highlights",
  "description": "Shared description text",
  "scheduled_at": "2026-04-01T09:00:00.000Z"
}
```

`scheduled_at` — ISO 8601 / RFC 3339 UTC timestamp. Omit or pass `null` to publish immediately.

#### `GET /youtube/upload_progress/<id>` response

```json
{
  "status": "running | done | error",
  "percent": 72,
  "video_id": "dQw4w9WgXcQ",
  "error": null,
  "finished": false
}
```

---

## Configuration

| File | Purpose |
|------|---------|
| `client_secrets.json` | Google OAuth app credentials (Desktop app type). Must be placed in the project root before using the YouTube tab. |
| `ClipOutro.mp4` | Outro clip appended to every generated clip. Remove or replace this file to change or disable the outro. |
| `static/Logo.png` | Brand logo displayed in the sidebar. |

Server port is hardcoded to **8080** in `app.py`. To change it, edit the `app.run()` call.

---

## Troubleshooting

**Clips are cut short / not generated**  
Make sure `ffmpeg` is on your system `PATH`. Run `ffmpeg -version` to verify.

**`ModuleNotFoundError: google_auth_oauthlib`**  
Install into the venv, not system Python: `venv/bin/pip install google-auth-oauthlib google-api-python-client`

**YouTube OAuth `invalid_grant` error**  
Delete `yt_credentials.json` and `.yt_oauth_state` from the project root and reconnect.

**`redirect_uri_mismatch` error**  
Ensure `http://localhost:8080/youtube/callback` is listed exactly in your Google Cloud OAuth redirect URIs (not `127.0.0.1`).

**Scheduled uploads fail**  
YouTube requires the channel to be in good standing for scheduled uploads. The `scheduled_at` timestamp must be at least 10 minutes in the future and in RFC 3339 UTC format.

---

## Changelog

### 2026-04-16

#### New Features
- **Portrait Converter** (`/convert`) — convert any full landscape video to 9:16 portrait in one step, with optional SRT subtitle burn-in and configurable speaker split ratio
- **Audio Clip Generator** (`/audioclips`) — combine a static portrait image with an audio file to produce sequential MP4 reels; supports configurable number of clips, clip duration, and start offset; each clip becomes downloadable as soon as it renders
- **Live nav step progression** — sidebar Workflow steps now animate: completed steps show a green checkmark, the active step highlights in brand colour

#### Bug Fixes
- **Pillow 10+ compatibility** — replaced deprecated `Image.ANTIALIAS` with `Image.LANCZOS` in MoviePy's resize helper
- **Pillow 10+ text measurement** — replaced all `draw.textsize()` calls with `draw.textbbox()` in `moviepy_worker.py` (10 call-sites) to fix `AttributeError` on Python 3.12+
- **Double subtitle rendering** — eliminated duplicate caption layers; each subtitle frame now renders all words on a single transparent overlay

#### Internal Changes
- Added `make_portrait_full_video()` and `make_audio_reel()` to `moviepy_worker.py`
- Added `background_convert_video()` and `background_audio_clips()` background workers to `app.py`
- Added `ALLOWED_AUDIO_EXT` and `ALLOWED_SRT_EXT` extension sets to `app.py`
- Added `AudioFileClip` import to `moviepy_worker.py`
- New templates: `templates/convert.html`, `templates/audioclips.html`
- New CSS utilities: `.nav-section-label`, `.nav-divider`, `.nav-step`, `.step-dot` (with `.active` / `.done` states)
- `static/js/app.js`: added `navUpload` reference, rewrote `setNavActive()` with linear done/active progression, added `navUpload` click handler, fixed `newJobBtn` reset to call `setNavActive('upload')`
