# utils.py
import os, uuid
import pysrt
from moviepy.editor import VideoFileClip

UPLOAD_DIR = "uploads"
CLIPS_DIR = "clips"
THUMBS_DIR = "thumbs"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(CLIPS_DIR, exist_ok=True)
os.makedirs(THUMBS_DIR, exist_ok=True)

def parse_srt(path):
    subs = pysrt.open(path, encoding='utf-8')
    cues = []
    for i, s in enumerate(subs):
        start = s.start.ordinal / 1000.0
        end = s.end.ordinal / 1000.0
        text = s.text.replace('\n', ' ')
        cues.append({"index": i+1, "start": start, "end": end, "text": text})
    return cues

def select_top_cues(cues, max_clips=5):
    scored = []
    for c in cues:
        duration = max(0.01, c["end"] - c["start"])
        words = len(c["text"].split())
        score = duration * words
        scored.append((score, c))
    scored.sort(reverse=True, key=lambda x: x[0])
    top = [c for _, c in scored[:max_clips]]
    top_sorted = sorted(top, key=lambda x: x["start"])
    return top_sorted

def make_thumbnail(video_path, t, out_path, w=360, h=640):
    with VideoFileClip(video_path) as clip:
        t = min(max(0.1, t), clip.duration - 0.1)
        frame = clip.get_frame(t)
        from PIL import Image
        im = Image.fromarray(frame)
        im = im.resize((w, h))
        im.save(out_path)
    return out_path

def safe_name(prefix="clip"):
    return f"{prefix}_{uuid.uuid4().hex}.mp4"
