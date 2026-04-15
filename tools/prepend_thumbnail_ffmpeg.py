#!/usr/bin/env python3
"""
prepend_thumbnail_ffmpeg.py

Usage:
  python prepend_thumbnail_ffmpeg.py --video input.mp4 --image thumb.jpg --out out.mp4 --duration 1.2

Requirements:
  - ffmpeg and ffprobe must be installed and on PATH.
"""
import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile

def run(cmd, capture=False):
    print("RUN:", cmd)
    if capture:
        return subprocess.run(cmd, shell=True, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    else:
        return subprocess.run(cmd, shell=True, check=False)

def probe_video(path):
    """Return dict with width,height,fps,duration or raise RuntimeError."""
    if not shutil.which("ffprobe"):
        raise RuntimeError("ffprobe not found in PATH")
    cmd = (
        f"ffprobe -v error -select_streams v:0 "
        f"-show_entries stream=width,height,r_frame_rate,duration "
        f"-of json {shlex.quote(path)}"
    )
    res = run(cmd, capture=True)
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {res.stderr.strip()}")
    info = json.loads(res.stdout)
    streams = info.get("streams") or []
    if not streams:
        raise RuntimeError("no video stream found")
    s = streams[0]
    width = int(s.get("width"))
    height = int(s.get("height"))
    # r_frame_rate like "30000/1001" or "30/1"
    r = s.get("r_frame_rate", "30/1")
    try:
        num, den = r.split("/")
        fps = float(num) / float(den)
    except Exception:
        fps = 30.0
    duration = float(s.get("duration") or 0.0)
    return {"width": width, "height": height, "fps": fps, "duration": duration}

def create_image_video(image_path, out_path, width, height, fps, duration):
    """
    Create a short MP4 from an image with exact size and fps.
    """
    # -loop 1: loop image; -t duration; -vf scale and fps; -pix_fmt yuv420p for compatibility
    cmd = (
        f"ffmpeg -y -loop 1 -i {shlex.quote(image_path)} "
        f"-c:v libx264 -t {float(duration)} -pix_fmt yuv420p "
        f"-vf scale={width}:{height},fps={fps} -an {shlex.quote(out_path)}"
    )
    res = run(cmd)
    if res.returncode != 0:
        raise RuntimeError("ffmpeg failed to create image video")

def try_concat_copy(img_vid, main_vid, out_path):
    """
    Try concat demuxer with -c copy (fast, no re-encode). Returns True on success.
    """
    fd, list_txt = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    try:
        with open(list_txt, "w", encoding="utf-8") as fh:
            fh.write(f"file '{img_vid}'\n")
            fh.write(f"file '{main_vid}'\n")
        cmd = f"ffmpeg -y -f concat -safe 0 -i {shlex.quote(list_txt)} -c copy {shlex.quote(out_path)}"
        res = run(cmd, capture=True)
        if res.returncode == 0:
            return True
        # if it failed, print stderr for debugging
        print("concat copy failed:", res.stderr)
        return False
    finally:
        try:
            os.remove(list_txt)
        except Exception:
            pass

def concat_reencode(img_vid, main_vid, out_path):
    """
    Safe fallback: re-encode both inputs into a single output.
    Preserves main audio (maps audio from main_vid if present).
    """
    # detect if main has audio
    has_audio = False
    probe = run(f"ffprobe -v error -select_streams a:0 -show_entries stream=codec_type -of csv=p=0 {shlex.quote(main_vid)}", capture=True)
    if probe.returncode == 0 and probe.stdout.strip():
        has_audio = True

    # build filter_complex for concat
    # inputs: 0 = img_vid (video only), 1 = main_vid (video+maybe audio)
    # concat n=2 v=1 a=1 if audio present else a=0
    if has_audio:
        filter_complex = "[0:v:0][1:v:0][0:a:0][1:a:0]concat=n=2:v=1:a=1[outv][outa]"
        cmd = (
            f"ffmpeg -y -i {shlex.quote(img_vid)} -i {shlex.quote(main_vid)} "
            f"-filter_complex \"[0:v:0][1:v:0]concat=n=2:v=1:a=0[outv]\" "
            f"-map \"[outv]\" -map 1:a:0 -c:v libx264 -c:a aac -b:a 128k {shlex.quote(out_path)}"
        )
        # simpler: map composed video and main audio
    else:
        cmd = (
            f"ffmpeg -y -i {shlex.quote(img_vid)} -i {shlex.quote(main_vid)} "
            f"-filter_complex \"[0:v:0][1:v:0]concat=n=2:v=1:a=0[outv]\" "
            f"-map \"[outv]\" -c:v libx264 {shlex.quote(out_path)}"
        )
    res = run(cmd, capture=True)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg re-encode concat failed: {res.stderr}")
    return True

def main():
    p = argparse.ArgumentParser(description="Prepend an image as a short video to an existing MP4 using ffmpeg.")
    p.add_argument("--video", required=True, help="Path to input video")
    p.add_argument("--image", required=True, help="Path to thumbnail image")
    p.add_argument("--out", required=True, help="Path to output MP4")
    p.add_argument("--duration", type=float, default=1.2, help="Thumbnail display duration in seconds")
    p.add_argument("--force-width", type=int, default=None, help="Force width (overrides probe)")
    p.add_argument("--force-height", type=int, default=None, help="Force height (overrides probe)")
    p.add_argument("--force-fps", type=float, default=None, help="Force fps (overrides probe)")
    args = p.parse_args()

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        print("ffmpeg/ffprobe not found in PATH", file=sys.stderr)
        sys.exit(2)
    if not os.path.exists(args.video):
        print("video not found", file=sys.stderr); sys.exit(2)
    if not os.path.exists(args.image):
        print("image not found", file=sys.stderr); sys.exit(2)

    try:
        info = probe_video(args.video)
    except Exception as e:
        print("probe failed:", e, file=sys.stderr)
        sys.exit(3)

    width = args.force_width or info["width"]
    height = args.force_height or info["height"]
    fps = args.force_fps or round(info["fps"], 2) or 24.0

    tmp_dir = tempfile.mkdtemp(prefix="thumb_prepend_")
    try:
        img_vid = os.path.join(tmp_dir, "thumb_video.mp4")
        create_image_video(args.image, img_vid, width, height, fps, args.duration)

        # Try fast concat copy first
        try:
            ok = try_concat_copy(img_vid, args.video, args.out)
            if ok:
                print("Concatenation (copy) succeeded:", args.out)
                sys.exit(0)
        except Exception as e:
            print("concat copy attempt failed:", e)

        # Fallback: re-encode concat
        print("Falling back to re-encode concat...")
        concat_reencode(img_vid, args.video, args.out)
        print("Concatenation (re-encode) succeeded:", args.out)
        sys.exit(0)
    except Exception as e:
        print("Error:", e, file=sys.stderr)
        sys.exit(4)
    finally:
        try:
            shutil.rmtree(tmp_dir)
        except Exception:
            pass

if __name__ == "__main__":
    main()
