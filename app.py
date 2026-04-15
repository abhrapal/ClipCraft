# app.py
import os
import uuid
import json as _json
import threading
import traceback
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")  # allow OAuth over http on localhost
from flask import Flask, request, jsonify, render_template, send_from_directory, abort, redirect
from werkzeug.utils import secure_filename
from moviepy_worker import make_portrait_clip_two_speakers, make_portrait_full_video, make_audio_reel
from ffmpeg_prepend import prepend_thumbnail, FFmpegPrependError, append_outro

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTRO_PATH = os.path.join(BASE_DIR, "ClipOutro.mp4")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
CLIPS_DIR = os.path.join(BASE_DIR, "clips")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(CLIPS_DIR, exist_ok=True)

# ── YouTube ────────────────────────────────────────────────────
YT_SECRETS_FILE    = os.path.join(BASE_DIR, "client_secrets.json")
YT_CREDENTIALS_FILE = os.path.join(BASE_DIR, "yt_credentials.json")
YT_SCOPES          = ["https://www.googleapis.com/auth/youtube.upload"]
YT_REDIRECT_URI    = "http://localhost:8080/youtube/callback"
yt_uploads         = {}          # upload_id -> progress dict
yt_uploads_lock    = threading.Lock()

ALLOWED_VIDEO_EXT = {"mp4", "mov", "mkv", "webm", "avi"}
ALLOWED_SRT_EXT = {"srt", "txt"}
ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "webp"}
ALLOWED_AUDIO_EXT = {"mp3", "wav", "m4a", "aac", "ogg"}

app = Flask(__name__, static_folder="static", template_folder="templates")

jobs = {}
jobs_lock = threading.Lock()

def allowed_file(filename, allowed_set):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in allowed_set

def unique_name(base="clip"):
    return f"{base}-{uuid.uuid4().hex[:8]}"

def ensure_mp4(name):
    if name.lower().endswith(".mp4"):
        return name
    return name + ".mp4"

def parse_srt_contents(srt_text):
    cues = []
    parts = srt_text.strip().split("\n\n")
    idx = 0
    for block in parts:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        time_line = None
        for ln in lines:
            if "-->" in ln:
                time_line = ln
                break
        if not time_line:
            continue
        try:
            start_s, end_s = [t.strip() for t in time_line.split("-->")]
            def to_seconds(t):
                t = t.replace(",", ".")
                parts = t.split(":")
                parts = [float(p) for p in parts]
                if len(parts) == 3:
                    return parts[0]*3600 + parts[1]*60 + parts[2]
                if len(parts) == 2:
                    return parts[0]*60 + parts[1]
                return parts[0]
            start = to_seconds(start_s)
            end = to_seconds(end_s)
        except Exception:
            continue
        try:
            ti = lines.index(time_line)
            text = " ".join(lines[ti+1:]) if ti+1 < len(lines) else ""
        except ValueError:
            text = " ".join(lines[1:]) if len(lines) > 1 else ""
        cues.append({"index": idx, "start": start, "end": end, "text": text})
        idx += 1
    return cues

def background_generate_clips(job_id, video_path, srt_path, selected_indices, max_clips, split_x_ratio=0.5,
                              auto_window=45, auto_min_duration=30, thumbnail_path=None, embed_thumbnail=False,
                              thumbnail_duration=1.2, max_duration=None):
    with jobs_lock:
        jobs[job_id] = {"status": "running", "percent": 0, "clips": [], "errors": [], "finished": False, "cancel": False}

    # If a thumbnail was provided, prefer embedding unless explicitly disabled
    if thumbnail_path and not embed_thumbnail:
        embed_thumbnail = True

    try:
        with open(srt_path, "r", encoding="utf-8", errors="ignore") as fh:
            srt_text = fh.read()
        cues = parse_srt_contents(srt_text)
    except Exception:
        cues = []

    try:
        from moviepy.editor import VideoFileClip
        with VideoFileClip(video_path) as vclip:
            video_duration = vclip.duration
    except Exception:
        video_duration = None

    # helper: snap segment end to the boundary of the SRT cue that overlaps or immediately follows
    # the calculated end time, so clips never cut off mid-sentence.
    def snap_end_to_cue(end_time):
        if not cues:
            return end_time
        # Find the cue whose range contains end_time
        for c in cues:
            cs = float(c['start'])
            ce = float(c['end'])
            if cs <= end_time < ce:
                return ce          # extend to end of this cue
        # end_time falls between cues or after all cues — find nearest cue end >= end_time
        for c in sorted(cues, key=lambda x: float(x['start'])):
            ce = float(c['end'])
            if ce >= end_time:
                return ce
        return end_time  # already past all cues

    # helper: clamp a segment to be between auto_min_duration and max_duration (if provided)
    def clamp_segment(seg):
        s = float(seg.get('start', 0.0))
        e = float(seg.get('end', s + 1.0))
        dur = e - s
        # ensure minimum duration
        if dur < auto_min_duration:
            needed = auto_min_duration - dur
            half = needed / 2.0
            s = s - half
            e = e + half
            if video_duration is not None:
                if s < 0:
                    e = min(video_duration, e + abs(s))
                    s = 0.0
                if e > video_duration:
                    s = max(0.0, s - (e - video_duration))
                    e = video_duration
        # enforce maximum duration if provided
        if max_duration is not None:
            try:
                md = float(max_duration)
            except Exception:
                md = None
            if md is not None and (e - s) > md:
                center = (s + e) / 2.0
                s = center - md / 2.0
                e = center + md / 2.0
                if s < 0:
                    s = 0.0
                    e = min(video_duration if video_duration is not None else md, md)
                if video_duration is not None and e > video_duration:
                    e = video_duration
                    s = max(0.0, e - md)
        seg['start'] = max(0.0, s)
        seg['end'] = max(seg['start'] + 0.001, e)
        return seg

    worklist = []
    if not selected_indices:
        start = 0.0
        candidate_windows = []
        while True:
            if video_duration is not None and start >= video_duration:
                break
            end = start + auto_window if video_duration is None else min(start + auto_window, video_duration)
            candidate_windows.append({"start": start, "end": end})
            if video_duration is not None and end >= video_duration:
                break
            start += auto_window

        snapped = []
        used_starts = set()
        if cues:
            cue_starts = [float(c['start']) for c in cues]
            for win in candidate_windows:
                desired_center = (win['start'] + win['end']) / 2.0
                best_idx = None
                best_dist = None
                for i, cs in enumerate(cue_starts):
                    d = abs(cs - desired_center)
                    if best_dist is None or d < best_dist:
                        best_dist = d
                        best_idx = i
                if best_idx is None:
                    continue
                cue_start = cue_starts[best_idx]
                if cue_start in used_starts:
                    continue
                used_starts.add(cue_start)
                new_start = cue_start
                new_end = new_start + auto_window
                if video_duration is not None:
                    if new_end > video_duration:
                        new_end = video_duration
                        new_start = max(0.0, new_end - auto_window)
                    snapped.append({"index": len(snapped), "start": new_start, "end": new_end, "text": ""})
        else:
            for i, win in enumerate(candidate_windows):
                snapped.append({"index": i, "start": win['start'], "end": win['end'], "text": ""})

        padded = []
        for seg in snapped:
            seg_start = float(seg["start"])
            seg_end = float(seg["end"])
            seg_dur = seg_end - seg_start
            if seg_dur >= auto_min_duration:
                padded.append(seg)
                continue
            needed = auto_min_duration - seg_dur
            half = needed / 2.0
            new_start = seg_start - half
            new_end = seg_end + half
            if video_duration is not None:
                if new_start < 0:
                    new_end = min(video_duration, new_end + abs(new_start))
                    new_start = 0.0
                if new_end > video_duration:
                    new_start = max(0.0, new_start - (new_end - video_duration))
                    new_end = video_duration
            else:
                new_start = max(0.0, new_start)
            if video_duration is not None and (new_end - new_start) < auto_min_duration and video_duration >= auto_min_duration:
                mid = (seg_start + seg_end) / 2.0
                new_start = max(0.0, min(video_duration - auto_min_duration, mid - auto_min_duration / 2.0))
                new_end = new_start + auto_min_duration
            padded.append({"index": seg.get("index", 0), "start": new_start, "end": new_end, "text": seg.get("text", "")})

        # snap each segment's end to the nearest SRT cue boundary so clips end on a full sentence,
        # then clamp to max_duration
        def _snap(seg):
            snapped_end = snap_end_to_cue(float(seg['end']))
            # only extend — never shorten — and don't exceed video duration
            if snapped_end > float(seg['end']):
                if video_duration is None or snapped_end <= video_duration:
                    seg['end'] = snapped_end
            return seg
        worklist = [clamp_segment(_snap(seg)) for seg in padded]
        worklist = worklist[:max_clips] if max_clips else worklist
    else:
        worklist = []
        for idx in selected_indices:
            cue = next((c for c in cues if c["index"] == idx), None)
            if cue:
                worklist.append(cue)
        if not worklist and cues:
            worklist = cues[:max_clips]

        padded_selected = []
        for cue in worklist:
            s = float(cue.get("start", 0))
            e = float(cue.get("end", s + 1))
            dur = e - s
            if dur >= auto_min_duration:
                padded_selected.append(cue)
                continue
            needed = auto_min_duration - dur
            half = needed / 2.0
            new_start = s - half
            new_end = e + half
            if video_duration is not None:
                if new_start < 0:
                    new_end = min(video_duration, new_end + abs(new_start))
                    new_start = 0.0
                if new_end > video_duration:
                    new_start = max(0.0, new_start - (new_end - video_duration))
                    new_end = video_duration
            else:
                new_start = max(0.0, new_start)
            if video_duration is not None and (new_end - new_start) < auto_min_duration and video_duration >= auto_min_duration:
                mid = (s + e) / 2.0
                new_start = max(0.0, min(video_duration - auto_min_duration, mid - auto_min_duration / 2.0))
                new_end = new_start + auto_min_duration
            padded_selected.append({"index": cue.get("index"), "start": new_start, "end": new_end, "text": cue.get("text", "")})

        # snap to cue boundary then clamp
        def _snap_sel(seg):
            snapped_end = snap_end_to_cue(float(seg['end']))
            if snapped_end > float(seg['end']):
                if video_duration is None or snapped_end <= video_duration:
                    seg['end'] = snapped_end
            return seg
        padded_selected = [clamp_segment(_snap_sel(seg)) for seg in padded_selected]
        worklist = padded_selected[:max_clips] if max_clips else padded_selected

    # Fallback to ensure at least one clip
    if not worklist:
        fallback_end = min(auto_min_duration, video_duration) if video_duration else auto_min_duration
        worklist = [{"index": 0, "start": 0.0, "end": fallback_end, "text": ""}]
        print(f"[JOB {job_id}] worklist was empty, using fallback segment {worklist[0]}")

    total = len(worklist)
    if total == 0:
        with jobs_lock:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["errors"].append({"error": "No clips to generate."})
            jobs[job_id]["finished"] = True
        print(f"[JOB {job_id}] no worklist generated; exiting.")
        return

    done = 0
    for cue in worklist:
        with jobs_lock:
            if jobs[job_id].get("cancel"):
                jobs[job_id]["status"] = "cancelled"
                jobs[job_id]["finished"] = True
                print(f"[JOB {job_id}] cancelled by user.")
                return

        base = secure_filename(f"{os.path.splitext(os.path.basename(video_path))[0]}_seg{int(cue['start'])}_{unique_name()}")
        out_name = ensure_mp4(base)
        out_path = os.path.join(CLIPS_DIR, out_name)

        try:
            make_portrait_clip_two_speakers(
                video_path,
                cue,
                out_path,
                target_w=1080,
                target_h=1920,
                split_x_ratio=split_x_ratio,
                font_path=None,
                fontsize=56,
                text_color="#E6F6FB",
                highlight_color="#FFD166",
                subtitle_position=("center", 0.5),
                srt_cues=cues,
                thumbnail_path=thumbnail_path,
                embed_thumbnail=False,
                thumbnail_duration=thumbnail_duration,
                max_duration=max_duration
            )

            # If embed_thumbnail requested, call ffmpeg prepend wrapper to ensure robust prepend
            if embed_thumbnail:
                if not thumbnail_path or not os.path.exists(thumbnail_path):
                    print(f"[JOB {job_id}] embed_thumbnail requested but thumbnail missing: {thumbnail_path}")
                else:
                    try:
                        tmp_out = out_path + ".withthumb.mp4"
                        prepend_thumbnail(out_path, thumbnail_path, tmp_out, duration=thumbnail_duration, timeout=240)
                        os.replace(tmp_out, out_path)
                    except FFmpegPrependError as e:
                        print(f"[JOB {job_id}] ffmpeg prepend failed: {e}")
                        with jobs_lock:
                            jobs[job_id]["errors"].append({"cue_index": cue.get("index"), "error": f"ffmpeg prepend failed: {str(e)}"})
                    except Exception as e:
                        print(f"[JOB {job_id}] unexpected error during ffmpeg prepend: {e}")
                        with jobs_lock:
                            jobs[job_id]["errors"].append({"cue_index": cue.get("index"), "error": f"unexpected prepend error: {str(e)}"})

            # Append fixed outro if present
            if os.path.exists(OUTRO_PATH):
                try:
                    tmp_outro = out_path + ".withoutro.mp4"
                    append_outro(out_path, OUTRO_PATH, tmp_outro, timeout=300)
                    os.replace(tmp_outro, out_path)
                except FFmpegPrependError as e:
                    print(f"[JOB {job_id}] outro append failed: {e}")
                    with jobs_lock:
                        jobs[job_id]["errors"].append({"cue_index": cue.get("index"), "error": f"outro failed: {str(e)}"})
                except Exception as e:
                    print(f"[JOB {job_id}] unexpected outro error: {e}")

            with jobs_lock:
                jobs[job_id]["clips"].append({"clip": out_name})
        except Exception as e:
            print(f"[JOB {job_id}] ERROR processing cue: {e}")
            traceback.print_exc()
            with jobs_lock:
                jobs[job_id]["errors"].append({"cue_index": cue.get("index"), "error": str(e)})
        done += 1
        with jobs_lock:
            jobs[job_id]["percent"] = int(done / total * 100)

    with jobs_lock:
        jobs[job_id]["status"] = "done"
        jobs[job_id]["finished"] = True
        jobs[job_id]["percent"] = 100
    print(f"[JOB {job_id}] finished. total_clips={len(jobs[job_id]['clips'])} errors={len(jobs[job_id]['errors'])}")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/upload", methods=["POST"])
def upload():
    if "video" not in request.files or "srt" not in request.files:
        return jsonify({"error": "Both video and srt files are required"}), 400

    video = request.files["video"]
    srt = request.files["srt"]
    thumb = request.files.get("thumbnail")

    if video.filename == "" or srt.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    vname = secure_filename(video.filename)
    sname = secure_filename(srt.filename)

    if not allowed_file(vname, ALLOWED_VIDEO_EXT):
        return jsonify({"error": "Unsupported video format"}), 400
    if not allowed_file(sname, ALLOWED_SRT_EXT):
        return jsonify({"error": "Unsupported subtitle format"}), 400

    vid_save = unique_name(os.path.splitext(vname)[0]) + os.path.splitext(vname)[1]
    srt_save = unique_name(os.path.splitext(sname)[0]) + os.path.splitext(sname)[1]
    vid_path = os.path.join(UPLOAD_DIR, vid_save)
    srt_path = os.path.join(UPLOAD_DIR, srt_save)
    video.save(vid_path)
    srt.save(srt_path)

    thumb_save = None
    if thumb and thumb.filename:
        tname = secure_filename(thumb.filename)
        if not allowed_file(tname, ALLOWED_IMAGE_EXT):
            return jsonify({"error": "Unsupported thumbnail image format"}), 400
        thumb_save = unique_name(os.path.splitext(tname)[0]) + os.path.splitext(tname)[1]
        thumb_path = os.path.join(UPLOAD_DIR, thumb_save)
        thumb.save(thumb_path)
    else:
        thumb_path = None

    try:
        with open(srt_path, "r", encoding="utf-8", errors="ignore") as fh:
            srt_text = fh.read()
        cues = parse_srt_contents(srt_text)
    except Exception:
        cues = []

    return jsonify({"video": vid_save, "srt": srt_save, "thumbnail": thumb_save, "cues": cues})

@app.route("/make_clips", methods=["POST"])
def make_clips():
    data = request.get_json(force=True)
    video = data.get("video")
    srt = data.get("srt")
    selected_indices = data.get("selected_indices") or []
    try:
        max_clips = int(data.get("max_clips") or 3)
    except Exception:
        max_clips = 3
    # sanitize and cap to reasonable maximum
    max_clips = max(1, min(max_clips, 20))
    split_x_ratio = float(data.get("split_x_ratio") or 0.5)
    auto_window = int(data.get("auto_window") or 45)
    auto_min_duration = int(data.get("auto_min_duration") or 30)
    # optional maximum clip duration (in seconds) for auto-generated clips
    try:
        max_duration = int(data.get("max_duration")) if data.get("max_duration") is not None else None
    except Exception:
        max_duration = None
    thumbnail = data.get("thumbnail")
    embed_thumbnail = bool(data.get("embed_thumbnail", True))
    thumbnail_duration = float(data.get("thumbnail_duration") or 1.2)

    if not video or not srt:
        return jsonify({"error": "video and srt required"}), 400

    vid_path = os.path.join(UPLOAD_DIR, video)
    srt_path = os.path.join(UPLOAD_DIR, srt)
    thumb_path = os.path.join(UPLOAD_DIR, thumbnail) if thumbnail else None
    if not os.path.exists(vid_path) or not os.path.exists(srt_path):
        return jsonify({"error": "uploaded files not found"}), 404
    if thumb_path and not os.path.exists(thumb_path):
        thumb_path = None

    job_id = uuid.uuid4().hex
    with jobs_lock:
        jobs[job_id] = {"status": "queued", "percent": 0, "clips": [], "errors": [], "finished": False, "cancel": False}
        # store params for debugging/inspection
        jobs[job_id]["params"] = {
            "video": video,
            "srt": srt,
            "selected_indices": selected_indices,
            "max_clips": max_clips,
            "split_x_ratio": split_x_ratio,
            "auto_window": auto_window,
            "auto_min_duration": auto_min_duration,
            "max_duration": max_duration,
            "thumbnail": thumbnail,
            "embed_thumbnail": embed_thumbnail,
            "thumbnail_duration": thumbnail_duration,
        }

    thread = threading.Thread(
        target=background_generate_clips,
        args=(job_id, vid_path, srt_path, selected_indices, max_clips, split_x_ratio, auto_window, auto_min_duration, thumb_path, embed_thumbnail, thumbnail_duration, max_duration),
        daemon=True
    )
    thread.start()

    return jsonify({"job_id": job_id})

@app.route("/progress/<job_id>", methods=["GET"])
def progress(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "job not found"}), 404
        return jsonify({
            "status": job.get("status"),
            "percent": job.get("percent", 0),
            "clips": job.get("clips", []),
            "errors": job.get("errors", []),
            "finished": job.get("finished", False)
        })


@app.route("/debug_job/<job_id>", methods=["GET"])
def debug_job(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "job not found"}), 404
        # return full job dict (for debugging only)
        return jsonify(job)

@app.route("/cancel/<job_id>", methods=["POST"])
def cancel(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "job not found"}), 404
        job["cancel"] = True
    return jsonify({"ok": True})

@app.route("/clips/<path:filename>", methods=["GET"])
def serve_clip(filename):
    safe = secure_filename(filename)
    path = os.path.join(CLIPS_DIR, safe)
    if not os.path.exists(path):
        abort(404)
    return send_from_directory(CLIPS_DIR, safe, as_attachment=False)

# ── YouTube routes ─────────────────────────────────────────────

def _yt_get_credentials():
    """Load stored OAuth credentials, refreshing if expired."""
    if not os.path.exists(YT_CREDENTIALS_FILE):
        return None
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        with open(YT_CREDENTIALS_FILE) as fh:
            data = _json.load(fh)
        creds = Credentials.from_authorized_user_info(data, YT_SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(YT_CREDENTIALS_FILE, "w") as fh:
                fh.write(creds.to_json())
        return creds if creds.valid else None
    except Exception:
        return None


def _yt_save_credentials(creds):
    with open(YT_CREDENTIALS_FILE, "w") as fh:
        fh.write(creds.to_json())


@app.route("/youtube/status")
def yt_status():
    if not os.path.exists(YT_SECRETS_FILE):
        return jsonify({"configured": False, "authenticated": False})
    creds = _yt_get_credentials()
    channel_name = None
    if creds:
        try:
            from googleapiclient.discovery import build
            svc = build("youtube", "v3", credentials=creds)
            ch = svc.channels().list(part="snippet", mine=True).execute()
            items = ch.get("items", [])
            channel_name = items[0]["snippet"]["title"] if items else "YouTube"
        except Exception:
            channel_name = "YouTube"
    return jsonify({"configured": True, "authenticated": bool(creds), "channel": channel_name})


@app.route("/youtube/auth")
def yt_auth():
    if not os.path.exists(YT_SECRETS_FILE):
        return "client_secrets.json not found in project root. See the YouTube tab for setup instructions.", 400
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_secrets_file(YT_SECRETS_FILE, scopes=YT_SCOPES, redirect_uri=YT_REDIRECT_URI)
    auth_url, state = flow.authorization_url(access_type="offline", include_granted_scopes="true", prompt="consent")
    # Persist both state and code_verifier so the callback can complete the PKCE exchange
    pkce_data = {"state": state, "code_verifier": flow.code_verifier}
    with open(os.path.join(BASE_DIR, ".yt_oauth_state"), "w") as fh:
        _json.dump(pkce_data, fh)
    return redirect(auth_url)


@app.route("/youtube/callback")
def yt_callback():
    if not os.path.exists(YT_SECRETS_FILE):
        return "client_secrets.json not found.", 400
    try:
        state_path = os.path.join(BASE_DIR, ".yt_oauth_state")
        state = None
        code_verifier = None
        if os.path.exists(state_path):
            try:
                pkce_data = _json.load(open(state_path))
                state = pkce_data.get("state")
                code_verifier = pkce_data.get("code_verifier")
            except Exception:
                # Legacy plain-text state file
                state = open(state_path).read().strip()
        from google_auth_oauthlib.flow import Flow
        flow = Flow.from_client_secrets_file(
            YT_SECRETS_FILE, scopes=YT_SCOPES, state=state, redirect_uri=YT_REDIRECT_URI
        )
        # Restore the code_verifier so PKCE token exchange succeeds
        if code_verifier:
            flow.code_verifier = code_verifier
        callback_url = request.url.replace("http://127.0.0.1:", "http://localhost:")
        flow.fetch_token(authorization_response=callback_url)
        _yt_save_credentials(flow.credentials)
        return redirect("/?yt_connected=1")
    except Exception as exc:
        tb = traceback.format_exc()
        print(f"[YT OAuth error] {exc}\n{tb}")
        return f"<h2>OAuth error</h2><pre>{exc}\n\n{tb}</pre>", 500


@app.route("/youtube/logout", methods=["POST"])
def yt_logout():
    if os.path.exists(YT_CREDENTIALS_FILE):
        os.remove(YT_CREDENTIALS_FILE)
    return jsonify({"ok": True})


def _yt_upload_worker(upload_id, clip_path, title, description, scheduled_at):
    with yt_uploads_lock:
        yt_uploads[upload_id] = {"status": "running", "percent": 0, "video_id": None, "error": None, "finished": False}
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        creds = _yt_get_credentials()
        if not creds:
            raise RuntimeError("Not authenticated with YouTube")
        youtube = build("youtube", "v3", credentials=creds)
        privacy = "private" if scheduled_at else "public"
        status_body = {"privacyStatus": privacy}
        if scheduled_at:
            status_body["publishAt"] = scheduled_at   # RFC 3339, e.g. 2026-04-01T18:00:00Z
        body = {
            "snippet": {
                "title": title or "ClipCraft Upload",
                "description": description or "",
                "categoryId": "22",   # People & Blogs
            },
            "status": status_body,
        }
        media = MediaFileUpload(clip_path, chunksize=256 * 1024, resumable=True, mimetype="video/mp4")
        insert_req = youtube.videos().insert(part=",".join(body.keys()), body=body, media_body=media)
        response = None
        while response is None:
            status_info, response = insert_req.next_chunk()
            if status_info:
                pct = int(status_info.progress() * 100)
                with yt_uploads_lock:
                    yt_uploads[upload_id]["percent"] = pct
        video_id = response.get("id", "")
        with yt_uploads_lock:
            yt_uploads[upload_id].update({"video_id": video_id, "percent": 100, "finished": True, "status": "done"})
    except Exception as exc:
        with yt_uploads_lock:
            yt_uploads[upload_id].update({"error": str(exc), "finished": True, "status": "error"})


@app.route("/youtube/upload", methods=["POST"])
def yt_upload():
    data = request.get_json(force=True)
    clip = (data.get("clip") or "").strip()
    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    scheduled_at = (data.get("scheduled_at") or "").strip() or None
    if not clip:
        return jsonify({"error": "clip filename required"}), 400
    clip_path = os.path.join(CLIPS_DIR, secure_filename(clip))
    if not os.path.exists(clip_path):
        return jsonify({"error": "clip not found on server"}), 404
    if not _yt_get_credentials():
        return jsonify({"error": "Not authenticated with YouTube"}), 401
    upload_id = uuid.uuid4().hex
    threading.Thread(
        target=_yt_upload_worker,
        args=(upload_id, clip_path, title, description, scheduled_at),
        daemon=True,
    ).start()
    return jsonify({"upload_id": upload_id})


@app.route("/youtube/upload_progress/<upload_id>")
def yt_upload_progress(upload_id):
    with yt_uploads_lock:
        info = yt_uploads.get(upload_id)
    if not info:
        return jsonify({"error": "not found"}), 404
    return jsonify(info)


@app.route("/clips/list")
def list_clips():
    try:
        files = [f for f in os.listdir(CLIPS_DIR) if f.lower().endswith(".mp4")]
        files.sort(key=lambda f: os.path.getmtime(os.path.join(CLIPS_DIR, f)), reverse=True)
    except Exception:
        files = []
    return jsonify({"clips": files})


# ── Full-video portrait conversion ────────────────────────────

def background_convert_video(job_id, video_path, out_path, split_x_ratio, srt_cues=None):
    with jobs_lock:
        jobs[job_id]["status"] = "running"
    try:
        make_portrait_full_video(
            video_path, out_path,
            split_x_ratio=split_x_ratio,
            srt_cues=srt_cues,
            subtitle_position=("center", 0.5),
        )
        out_name = os.path.basename(out_path)
        with jobs_lock:
            jobs[job_id]["status"] = "done"
            jobs[job_id]["percent"] = 100
            jobs[job_id]["clips"] = [{"clip": out_name}]
            jobs[job_id]["finished"] = True
    except Exception as exc:
        traceback.print_exc()
        with jobs_lock:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["errors"].append({"error": str(exc)})
            jobs[job_id]["finished"] = True


@app.route("/convert")
def convert_page():
    return render_template("convert.html")


@app.route("/convert/upload", methods=["POST"])
def convert_upload():
    if "video" not in request.files:
        return jsonify({"error": "video file required"}), 400
    video = request.files["video"]
    if not video.filename:
        return jsonify({"error": "Empty filename"}), 400
    vname = secure_filename(video.filename)
    if not allowed_file(vname, ALLOWED_VIDEO_EXT):
        return jsonify({"error": "Unsupported video format"}), 400
    vid_save = unique_name(os.path.splitext(vname)[0]) + os.path.splitext(vname)[1]
    vid_path = os.path.join(UPLOAD_DIR, vid_save)
    video.save(vid_path)

    srt_save = None
    srt = request.files.get("srt")
    if srt and srt.filename:
        sname = secure_filename(srt.filename)
        if not allowed_file(sname, ALLOWED_SRT_EXT):
            return jsonify({"error": "Unsupported subtitle format"}), 400
        srt_save = unique_name(os.path.splitext(sname)[0]) + os.path.splitext(sname)[1]
        srt.save(os.path.join(UPLOAD_DIR, srt_save))

    return jsonify({"video": vid_save, "original_name": vname, "srt": srt_save})


@app.route("/convert/start", methods=["POST"])
def convert_start():
    data = request.get_json(force=True)
    video = data.get("video")
    if not video:
        return jsonify({"error": "video required"}), 400
    try:
        split_x_ratio = float(data.get("split_x_ratio") or 0.5)
        split_x_ratio = max(0.1, min(0.9, split_x_ratio))
    except Exception:
        split_x_ratio = 0.5

    vid_path = os.path.join(UPLOAD_DIR, secure_filename(video))
    if not os.path.exists(vid_path):
        return jsonify({"error": "uploaded file not found"}), 404

    srt_cues = None
    srt = data.get("srt")
    if srt:
        srt_path = os.path.join(UPLOAD_DIR, secure_filename(srt))
        if os.path.exists(srt_path):
            try:
                with open(srt_path, "r", encoding="utf-8", errors="ignore") as fh:
                    srt_cues = parse_srt_contents(fh.read())
            except Exception:
                srt_cues = None

    base = os.path.splitext(os.path.basename(vid_path))[0]
    out_name = ensure_mp4(f"{base}_portrait-{uuid.uuid4().hex[:8]}")
    out_path = os.path.join(CLIPS_DIR, out_name)

    job_id = uuid.uuid4().hex
    with jobs_lock:
        jobs[job_id] = {"status": "queued", "percent": 0, "clips": [], "errors": [], "finished": False}

    threading.Thread(
        target=background_convert_video,
        args=(job_id, vid_path, out_path, split_x_ratio, srt_cues),
        daemon=True,
    ).start()

    return jsonify({"job_id": job_id})


# ── Audio Clip Generator ─────────────────────────────────────────────────────

def background_audio_clips(job_id, image_path, audio_path, num_clips, clip_duration, start_offset):
    with jobs_lock:
        jobs[job_id]["status"] = "running"
    try:
        from moviepy.editor import AudioFileClip as AFC
        probe = AFC(audio_path)
        audio_duration = probe.duration
        probe.close()
    except Exception:
        audio_duration = None

    clips_made = []
    for i in range(num_clips):
        with jobs_lock:
            if jobs[job_id].get("cancel"):
                jobs[job_id]["status"] = "cancelled"
                jobs[job_id]["finished"] = True
                return
        start_time = start_offset + i * clip_duration
        if audio_duration is not None and start_time >= audio_duration:
            break
        end_time = start_time + clip_duration
        if audio_duration is not None:
            end_time = min(end_time, audio_duration)
        out_name = ensure_mp4(f"audioclip_{unique_name()}_part{i + 1}")
        out_path = os.path.join(CLIPS_DIR, out_name)
        try:
            make_audio_reel(image_path, audio_path, out_path, start_time, end_time)
            clips_made.append({"clip": out_name})
            with jobs_lock:
                jobs[job_id]["clips"] = clips_made[:]
                jobs[job_id]["percent"] = int((i + 1) / num_clips * 100)
        except Exception as exc:
            traceback.print_exc()
            with jobs_lock:
                jobs[job_id]["errors"].append({"clip_index": i + 1, "error": str(exc)})

    with jobs_lock:
        jobs[job_id]["status"] = "done"
        jobs[job_id]["percent"] = 100
        jobs[job_id]["finished"] = True


@app.route("/audioclips")
def audioclips_page():
    return render_template("audioclips.html")


@app.route("/audioclips/upload", methods=["POST"])
def audioclips_upload():
    image = request.files.get("image")
    audio = request.files.get("audio")
    if not image or not audio or not image.filename or not audio.filename:
        return jsonify({"error": "image and audio files required"}), 400
    iname = secure_filename(image.filename)
    aname = secure_filename(audio.filename)
    if not allowed_file(iname, ALLOWED_IMAGE_EXT):
        return jsonify({"error": "Unsupported image format"}), 400
    if not allowed_file(aname, ALLOWED_AUDIO_EXT):
        return jsonify({"error": "Unsupported audio format"}), 400
    img_save = unique_name(os.path.splitext(iname)[0]) + os.path.splitext(iname)[1]
    aud_save = unique_name(os.path.splitext(aname)[0]) + os.path.splitext(aname)[1]
    image.save(os.path.join(UPLOAD_DIR, img_save))
    audio.save(os.path.join(UPLOAD_DIR, aud_save))
    return jsonify({"image": img_save, "audio": aud_save, "audio_name": aname, "image_name": iname})


@app.route("/audioclips/start", methods=["POST"])
def audioclips_start():
    data = request.get_json(force=True)
    image = data.get("image")
    audio = data.get("audio")
    if not image or not audio:
        return jsonify({"error": "image and audio required"}), 400
    try:
        num_clips = max(1, min(int(data.get("num_clips") or 3), 50))
        clip_duration = max(5, int(data.get("clip_duration") or 60))
        start_offset = max(0, int(data.get("start_offset") or 0))
    except Exception:
        return jsonify({"error": "Invalid config values"}), 400
    image_path = os.path.join(UPLOAD_DIR, secure_filename(image))
    audio_path = os.path.join(UPLOAD_DIR, secure_filename(audio))
    if not os.path.exists(image_path) or not os.path.exists(audio_path):
        return jsonify({"error": "uploaded files not found"}), 404
    job_id = uuid.uuid4().hex
    with jobs_lock:
        jobs[job_id] = {"status": "queued", "percent": 0, "clips": [], "errors": [], "finished": False, "cancel": False}
    threading.Thread(
        target=background_audio_clips,
        args=(job_id, image_path, audio_path, num_clips, clip_duration, start_offset),
        daemon=True,
    ).start()
    return jsonify({"job_id": job_id})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
