# ffmpeg_prepend.py
import os
import shlex
import shutil
import subprocess
import tempfile
from typing import Optional

class FFmpegPrependError(RuntimeError):
    pass

def _run_cmd(cmd, timeout):
    """
    Run a command (list form) and return (returncode, stdout, stderr).
    Also prints command and outputs for debugging.
    """
    cmd_str = " ".join(shlex.quote(c) for c in cmd)
    print(f"[FFMPEG_PREPEND] running: {cmd_str}")
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
    print(f"[FFMPEG_PREPEND] returncode={proc.returncode}")
    if proc.stdout:
        print(f"[FFMPEG_PREPEND] stdout:\n{proc.stdout.strip()}")
    if proc.stderr:
        print(f"[FFMPEG_PREPEND] stderr:\n{proc.stderr.strip()}")
    return proc.returncode, proc.stdout, proc.stderr

def probe_duration(path: str) -> Optional[float]:
    """
    Probe a media file for duration using ffprobe. Returns duration in seconds or None.
    """
    try:
        cmd = [shlex.quote("ffprobe"), "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1", path]
        # Use shell=False but build a single string for ffprobe invocation via subprocess.run
        # to avoid quoting issues on some platforms; however we capture output safely.
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=noprint_wrappers=1", path],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if p.returncode != 0:
            print(f"[FFMPEG_PREPEND] ffprobe failed for {path}: {p.stderr.strip()}")
            return None
        out = p.stdout.strip()
        if not out:
            return None
        # expected format: duration=1.200000
        if "=" in out:
            try:
                return float(out.split("=")[1].strip())
            except Exception:
                pass
        try:
            return float(out)
        except Exception:
            return None
    except Exception as e:
        print(f"[FFMPEG_PREPEND] probe_duration exception: {e}")
        return None

def try_concat_copy(img_vid: str, main_vid: str, out_path: str) -> bool:
    """
    Try concat demuxer with -c copy (fast, no re-encode). Returns True on success.
    Uses absolute paths in the list file to avoid cwd issues.
    """
    fd, list_txt = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    try:
        img_abs = os.path.abspath(img_vid)
        main_abs = os.path.abspath(main_vid)
        with open(list_txt, "w", encoding="utf-8") as fh:
            fh.write(f"file '{img_abs}'\n")
            fh.write(f"file '{main_abs}'\n")
        print(f"[FFMPEG_PREPEND] concat list file: {list_txt}")
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_txt, "-c", "copy", out_path]
        ret, out, err = _run_cmd(cmd, timeout=120)
        if ret != 0:
            print(f"[FFMPEG_PREPEND] concat copy failed (rc={ret})")
            return False

        # Verify output contains both segments (duration check)
        out_dur = probe_duration(out_path)
        if out_dur is not None:
            print(f"[FFMPEG_PREPEND] concat copy produced duration={out_dur}")

        # If the main video has audio but the concat output lacks audio, treat as failure
        try:
            main_has_audio = False
            p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
                                "-show_entries", "stream=codec_type", "-of", "csv=p=0", main_abs],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if p.returncode == 0 and p.stdout.strip():
                main_has_audio = True

            out_has_audio = False
            q = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
                                "-show_entries", "stream=codec_type", "-of", "csv=p=0", out_path],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if q.returncode == 0 and q.stdout.strip():
                out_has_audio = True

            if main_has_audio and not out_has_audio:
                print("[FFMPEG_PREPEND] concat copy produced no audio while main has audio; treating as failure")
                try:
                    os.remove(out_path)
                except Exception:
                    pass
                return False
        except Exception as e:
            print(f"[FFMPEG_PREPEND] audio verification failed: {e}")

        print(f"[FFMPEG_PREPEND] concat copy succeeded: {out_path}")
        return True
    finally:
        try:
            os.remove(list_txt)
        except Exception:
            pass

def concat_reencode(img_vid: str, main_vid: str, out_path: str) -> bool:
    """
    Safe fallback: re-encode both inputs into a single output.
    Preserves main audio (maps audio from main_vid if present).
    """
    # detect if main has audio
    has_audio = False
    try:
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
                                "-show_entries", "stream=codec_type", "-of", "csv=p=0", main_vid],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if probe.returncode == 0 and probe.stdout.strip():
            has_audio = True
    except Exception as e:
        print(f"[FFMPEG_PREPEND] audio probe failed: {e}")

    if has_audio:
        # Map video from concatenation and audio from main_vid
        # Simpler approach: concat videos (video only) then map audio from main_vid
        cmd = [
            "ffmpeg", "-y",
            "-i", img_vid,
            "-i", main_vid,
            "-filter_complex", "[0:v:0][1:v:0]concat=n=2:v=1:a=0[outv]",
            "-map", "[outv]",
            "-map", "1:a:0",
            "-c:v", "libx264",
            "-c:a", "aac",
            "-b:a", "128k",
            out_path
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", img_vid,
            "-i", main_vid,
            "-filter_complex", "[0:v:0][1:v:0]concat=n=2:v=1:a=0[outv]",
            "-map", "[outv]",
            "-c:v", "libx264",
            out_path
        ]
    ret, out, err = _run_cmd(cmd, timeout=300)
    if ret != 0:
        raise FFmpegPrependError(f"ffmpeg re-encode concat failed: rc={ret}\nstderr:\n{err}")
    print(f"[FFMPEG_PREPEND] re-encode concat succeeded: {out_path}")
    return True

def append_outro(main_vid: str, outro_vid: str, out_path: str, timeout: int = 300) -> str:
    """
    Append outro_vid to the end of main_vid, writing the result to out_path.
    Uses re-encode concat so that mismatched codecs/resolutions are handled safely.
    Raises FFmpegPrependError on failure.
    """
    if not os.path.exists(main_vid):
        raise FFmpegPrependError(f"main video not found: {main_vid}")
    if not os.path.exists(outro_vid):
        raise FFmpegPrependError(f"outro video not found: {outro_vid}")

    # Detect whether main has audio
    has_audio = False
    try:
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", main_vid],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        if p.returncode == 0 and p.stdout.strip():
            has_audio = True
    except Exception as e:
        print(f"[FFMPEG_PREPEND] outro audio probe failed: {e}")

    tmp_dir = os.path.dirname(out_path) or "."
    tmp_fd, tmp_out = tempfile.mkstemp(suffix=".mp4", dir=tmp_dir)
    os.close(tmp_fd)

    try:
        if has_audio:
            cmd = [
                "ffmpeg", "-y",
                "-i", main_vid,
                "-i", outro_vid,
                "-filter_complex",
                "[0:v:0][0:a:0][1:v:0][1:a:0]concat=n=2:v=1:a=1[outv][outa]",
                "-map", "[outv]", "-map", "[outa]",
                "-c:v", "libx264", "-c:a", "aac", "-b:a", "128k",
                tmp_out
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-i", main_vid,
                "-i", outro_vid,
                "-filter_complex",
                "[0:v:0][1:v:0]concat=n=2:v=1:a=0[outv]",
                "-map", "[outv]",
                "-c:v", "libx264",
                tmp_out
            ]
        ret, out, err = _run_cmd(cmd, timeout=timeout)
        if ret != 0:
            raise FFmpegPrependError(f"append_outro failed: rc={ret}\n{err}")

        final_dur = probe_duration(tmp_out)
        print(f"[FFMPEG_PREPEND] append_outro succeeded: duration={final_dur} -> {out_path}")
        try:
            shutil.move(tmp_out, out_path)
        except Exception:
            os.replace(tmp_out, out_path)
        return out_path
    except subprocess.TimeoutExpired:
        raise FFmpegPrependError("append_outro timed out")
    finally:
        try:
            if os.path.exists(tmp_out):
                os.remove(tmp_out)
        except Exception:
            pass


def append_outro(main_vid: str, outro_vid: str, out_path: str, timeout: int = 300) -> str:
    """
    Append outro_vid to the end of main_vid, writing the result to out_path.
    Uses re-encode concat so mismatched codecs/resolutions are handled safely.
    Raises FFmpegPrependError on failure.
    """
    if not os.path.exists(main_vid):
        raise FFmpegPrependError(f"main video not found: {main_vid}")
    if not os.path.exists(outro_vid):
        raise FFmpegPrependError(f"outro video not found: {outro_vid}")

    # Detect whether main has audio
    has_audio = False
    try:
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", main_vid],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        if p.returncode == 0 and p.stdout.strip():
            has_audio = True
    except Exception as e:
        print(f"[FFMPEG_PREPEND] outro audio probe failed: {e}")

    tmp_dir = os.path.dirname(out_path) or "."
    tmp_fd, tmp_out = tempfile.mkstemp(suffix=".mp4", dir=tmp_dir)
    os.close(tmp_fd)

    try:
        if has_audio:
            cmd = [
                "ffmpeg", "-y",
                "-i", main_vid,
                "-i", outro_vid,
                "-filter_complex",
                "[0:v:0][0:a:0][1:v:0][1:a:0]concat=n=2:v=1:a=1[outv][outa]",
                "-map", "[outv]", "-map", "[outa]",
                "-c:v", "libx264", "-c:a", "aac", "-b:a", "128k",
                tmp_out
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-i", main_vid,
                "-i", outro_vid,
                "-filter_complex",
                "[0:v:0][1:v:0]concat=n=2:v=1:a=0[outv]",
                "-map", "[outv]",
                "-c:v", "libx264",
                tmp_out
            ]
        ret, out, err = _run_cmd(cmd, timeout=timeout)
        if ret != 0:
            raise FFmpegPrependError(f"append_outro failed: rc={ret}\n{err}")

        final_dur = probe_duration(tmp_out)
        print(f"[FFMPEG_PREPEND] append_outro succeeded: duration={final_dur} -> {out_path}")
        try:
            shutil.move(tmp_out, out_path)
        except Exception:
            os.replace(tmp_out, out_path)
        return out_path
    except subprocess.TimeoutExpired:
        raise FFmpegPrependError("append_outro timed out")
    finally:
        try:
            if os.path.exists(tmp_out):
                os.remove(tmp_out)
        except Exception:
            pass


def _create_image_video(image_path: str, out_path: str, duration: float,
                        width: int, height: int, fps: float, timeout: int = 60) -> None:
    """
    Create a short MP4 from a still image using ffmpeg directly.
    Raises FFmpegPrependError on failure.
    """
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", image_path,
        "-c:v", "libx264",
        "-t", str(float(duration)),
        "-pix_fmt", "yuv420p",
        "-vf", f"scale={width}:{height},fps={fps}",
        "-an",
        out_path
    ]
    ret, out, err = _run_cmd(cmd, timeout=timeout)
    if ret != 0:
        raise FFmpegPrependError(f"failed to create image video: rc={ret}\n{err}")


def _probe_video_info(path: str):
    """
    Return (width, height, fps) from a video file using ffprobe.
    Falls back to (1080, 1920, 24) on failure.
    """
    try:
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate",
             "-of", "csv=p=0", path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        if p.returncode == 0 and p.stdout.strip():
            parts = p.stdout.strip().split(",")
            w = int(parts[0])
            h = int(parts[1])
            r = parts[2].strip()
            try:
                num, den = r.split("/")
                fps = float(num) / float(den)
            except Exception:
                fps = 24.0
            return w, h, round(fps, 3)
    except Exception as e:
        print(f"[FFMPEG_PREPEND] _probe_video_info failed: {e}")
    return 1080, 1920, 24.0


def prepend_thumbnail(video_path: str, image_path: str, out_path: str,
                      duration: float = 1.2,
                      force_width: Optional[int] = None,
                      force_height: Optional[int] = None,
                      force_fps: Optional[float] = None,
                      timeout: int = 300) -> str:
    """
    Create a new MP4 at out_path that has the image prepended for `duration` seconds.
    Performs exactly ONE concat: (image_video) + (video_path).
    Previously the helper script was called and then concatenated again, causing
    the main clip to appear twice (double-length) and audio to cut off at clip length.
    """
    if not os.path.exists(video_path):
        raise FFmpegPrependError("video not found")
    if not os.path.exists(image_path):
        raise FFmpegPrependError("image not found")

    tmp_dir = os.path.dirname(out_path) or "."

    # Step 1: probe the video so the image-video matches its dimensions/fps exactly
    w, h, fps = _probe_video_info(video_path)
    if force_width:
        w = int(force_width)
    if force_height:
        h = int(force_height)
    if force_fps:
        fps = float(force_fps)

    print(f"[FFMPEG_PREPEND] creating image-video: {w}x{h}@{fps} dur={duration}")

    # Step 2: create image-video in a temp file
    img_vid_fd, img_vid = tempfile.mkstemp(suffix=".mp4", dir=tmp_dir)
    os.close(img_vid_fd)

    # Step 3: single concat into tmp_out, then atomic move to out_path
    tmp_out_fd, tmp_out = tempfile.mkstemp(suffix=".mp4", dir=tmp_dir)
    os.close(tmp_out_fd)

    try:
        _create_image_video(image_path, img_vid, duration, w, h, fps, timeout=60)

        # Try fast copy-concat first
        print(f"[FFMPEG_PREPEND] attempting fast concat copy into {tmp_out}")
        ok = try_concat_copy(img_vid, video_path, tmp_out)
        if ok:
            out_dur = probe_duration(tmp_out)
            print(f"[FFMPEG_PREPEND] fast concat output duration={out_dur}")
            if out_dur is not None and abs(out_dur - float(duration)) < 0.5:
                print("[FFMPEG_PREPEND] fast concat looks like thumbnail-only; falling back to re-encode")
                ok = False

        if not ok:
            print("[FFMPEG_PREPEND] falling back to re-encode concat")
            concat_reencode(img_vid, video_path, tmp_out)

        # Verify final duration
        final_dur = probe_duration(tmp_out)
        vid_dur = probe_duration(video_path) or 0.0
        print(f"[FFMPEG_PREPEND] final output duration={final_dur} (expected ~{duration + vid_dur:.1f}s)")

        # Atomic move
        try:
            shutil.move(tmp_out, out_path)
            print(f"[FFMPEG_PREPEND] moved {tmp_out} -> {out_path}")
        except Exception:
            os.replace(tmp_out, out_path)
            print(f"[FFMPEG_PREPEND] replaced {tmp_out} -> {out_path}")

        return out_path

    except subprocess.TimeoutExpired:
        raise FFmpegPrependError("ffmpeg prepend timed out")
    finally:
        for p in (img_vid, tmp_out):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass
