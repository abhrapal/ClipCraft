# moviepy_worker.py
import os
import tempfile
import traceback
from moviepy.editor import VideoFileClip, CompositeVideoClip, ImageClip, concatenate_videoclips, AudioFileClip
from PIL import Image, ImageDraw, ImageFont

def _choose_font(font_path, fontsize):
    font = None
    if font_path and os.path.exists(font_path):
        try:
            font = ImageFont.truetype(font_path, fontsize)
        except Exception:
            font = None
    if font is None:
        for p in ("/System/Library/Fonts/Helvetica.ttc", "/Library/Fonts/Arial.ttf", "C:\\Windows\\Fonts\\arial.ttf"):
            try:
                if os.path.exists(p):
                    font = ImageFont.truetype(p, fontsize)
                    break
            except Exception:
                continue
    if font is None:
        font = ImageFont.load_default()
    return font

def _render_subtitle_png_line(text, width,
                              font_path=None, fontsize=56,
                              text_color="#E6F6FB",
                              bg_rgba=(0,0,0,160),
                              padding=14, max_lines=None):
    font = _choose_font(font_path, fontsize)
    dummy = Image.new("RGBA", (width, 10), (0,0,0,0))
    draw = ImageDraw.Draw(dummy)

    words = [w for w in text.split() if w.strip()]
    if not words:
        fd, tmp = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        Image.new("RGBA", (width, 40), (0,0,0,0)).save(tmp)
        return tmp

    tokens = []
    for i, w in enumerate(words):
        tokens.append((w, i))
        if i != len(words)-1:
            tokens.append((" ", None))

    lines = []
    cur_line = []
    cur_w = 0
    max_w = int(width * 0.95)
    for token, idx in tokens:
        bb = draw.textbbox((0, 0), token, font=font)
        token_w = bb[2] - bb[0]
        if cur_w + token_w > max_w and cur_line:
            lines.append(cur_line)
            cur_line = []
            cur_w = 0
        cur_line.append((token, idx))
        cur_w += token_w
    if cur_line:
        lines.append(cur_line)
    if max_lines:
        lines = lines[:max_lines]

    ay_bb = draw.textbbox((0, 0), "Ay", font=font)
    line_h = ay_bb[3] - ay_bb[1]
    img_h = line_h * len(lines) + padding * 2
    img = Image.new("RGBA", (width, img_h), (0,0,0,0))
    draw = ImageDraw.Draw(img)

    rect_margin = 8
    rect_x0 = rect_margin
    rect_y0 = rect_margin
    rect_x1 = width - rect_margin
    rect_y1 = img_h - rect_margin
    try:
        draw.rounded_rectangle([rect_x0, rect_y0, rect_x1, rect_y1], radius=18, fill=bg_rgba)
    except Exception:
        draw.rectangle([rect_x0, rect_y0, rect_x1, rect_y1], fill=bg_rgba)

    y = padding
    for line in lines:
        line_text = "".join([t for t, _ in line])
        wl_bb = draw.textbbox((0, 0), line_text, font=font)
        w_line = wl_bb[2] - wl_bb[0]
        x = (width - w_line) // 2
        for token, idx in line:
            draw.text((x, y), token, font=font, fill=text_color)
            tb = draw.textbbox((0, 0), token, font=font)
            x += tb[2] - tb[0]
        y += line_h

    fd, tmp_path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    img.save(tmp_path, format="PNG")
    return tmp_path

def _render_highlight_overlay_png(text, width, highlight_idx,
                                  font_path=None, fontsize=56,
                                  text_color="#E6F6FB",
                                  highlight_color="#FFD166",
                                  bg_rgba=(0, 0, 0, 160),
                                  padding=14, max_lines=None):
    """Render the full subtitle with all words visible; the word at highlight_idx is in highlight_color."""
    font = _choose_font(font_path, fontsize)
    dummy = Image.new("RGBA", (width, 10), (0,0,0,0))
    draw = ImageDraw.Draw(dummy)

    words = [w for w in text.split() if w.strip()]
    if not words:
        fd, tmp = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        Image.new("RGBA", (width, 40), (0,0,0,0)).save(tmp)
        return tmp
    # clamp highlight_idx to valid range
    highlight_idx = max(0, min(highlight_idx, len(words) - 1))

    tokens = []
    for i, w in enumerate(words):
        tokens.append((w, i))
        if i != len(words)-1:
            tokens.append((" ", None))

    lines = []
    cur_line = []
    cur_w = 0
    max_w = int(width * 0.95)
    for token, idx in tokens:
        bb = draw.textbbox((0, 0), token, font=font)
        token_w = bb[2] - bb[0]
        if cur_w + token_w > max_w and cur_line:
            lines.append(cur_line)
            cur_line = []
            cur_w = 0
        cur_line.append((token, idx))
        cur_w += token_w
    if cur_line:
        lines.append(cur_line)
    if max_lines:
        lines = lines[:max_lines]

    ay_bb = draw.textbbox((0, 0), "Ay", font=font)
    line_h = ay_bb[3] - ay_bb[1]
    img_h = line_h * len(lines) + padding * 2
    img = Image.new("RGBA", (width, img_h), (0,0,0,0))
    draw = ImageDraw.Draw(img)

    # Draw background
    rect_margin = 8
    try:
        draw.rounded_rectangle([rect_margin, rect_margin, width - rect_margin, img_h - rect_margin],
                                radius=18, fill=bg_rgba)
    except Exception:
        draw.rectangle([rect_margin, rect_margin, width - rect_margin, img_h - rect_margin], fill=bg_rgba)

    y = padding
    for line in lines:
        line_text = "".join([t for t, _ in line])
        wl_bb = draw.textbbox((0, 0), line_text, font=font)
        w_line = wl_bb[2] - wl_bb[0]
        x = (width - w_line) // 2
        for token, idx in line:
            if idx is None:
                tb = draw.textbbox((0, 0), token, font=font)
                x += tb[2] - tb[0]
            else:
                if idx == highlight_idx:
                    tbb = draw.textbbox((0, 0), token, font=font)
                    tw = tbb[2] - tbb[0]
                    th = tbb[3] - tbb[1]
                    pad = 6
                    try:
                        draw.rounded_rectangle([x - pad, y - 2, x + tw + pad, y + th + 2],
                                               radius=10, fill=(255, 255, 255, 20))
                    except Exception:
                        draw.rectangle([x - pad, y - 2, x + tw + pad, y + th + 2],
                                       fill=(255, 255, 255, 20))
                    draw.text((x, y), token, font=font, fill=highlight_color)
                else:
                    draw.text((x, y), token, font=font, fill=text_color)
                tb = draw.textbbox((0, 0), token, font=font)
                x += tb[2] - tb[0]
        y += line_h

    fd, tmp_path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    img.save(tmp_path, format="PNG")
    return tmp_path

def _create_word_timed_subtitle_clips_for_cue(full_text, cue_start_abs, cue_end_abs, segment_start_abs,
                                              target_w, target_h,
                                              font_path=None, fontsize=56,
                                              text_color="#E6F6FB", highlight_color="#FFD166",
                                              subtitle_position=("center", 0.5),
                                              fade=0.0):
    words = [w for w in full_text.split() if w.strip()]
    if not words:
        return None, [], []

    char_counts = [len(w) for w in words]
    total_chars = sum(char_counts) or len(words)
    cue_dur = max(0.001, float(cue_end_abs) - float(cue_start_abs))
    word_durations = [max(0.02, cue_dur * (c / total_chars)) for c in char_counts]
    s = sum(word_durations)
    if s > 0:
        word_durations = [d * (cue_dur / s) for d in word_durations]

    tmp_pngs = []

    x_pos = "center"
    y_val = subtitle_position[1] if isinstance(subtitle_position, tuple) else 0.5
    if isinstance(y_val, float) and 0.0 <= y_val <= 1.0:
        y_pos = int(y_val * target_h)
    else:
        y_pos = int(y_val)

    base_start_rel = cue_start_abs - segment_start_abs
    if base_start_rel < 0:
        base_start_rel = 0.0

    # Each word frame is a complete subtitle image (all words visible, current word highlighted).
    # No separate base layer — eliminates double-rendering.
    overlay_clips = []
    t_rel = base_start_rel
    for i, d in enumerate(word_durations):
        overlay_png = _render_highlight_overlay_png(
            full_text, width=int(target_w * 0.9),
            highlight_idx=i, font_path=font_path, fontsize=fontsize,
            text_color=text_color, highlight_color=highlight_color,
            bg_rgba=(0, 0, 0, 160), padding=14)
        tmp_pngs.append(overlay_png)
        oc = ImageClip(overlay_png).set_duration(d).set_start(max(0, t_rel)).set_position((x_pos, y_pos))
        overlay_clips.append(oc)
        t_rel += d

    return None, overlay_clips, tmp_pngs

def make_portrait_clip_two_speakers(video_path, cue, out_path,
                                   target_w=1080, target_h=1920,
                                   split_x_ratio=0.5,
                                   font_path=None, fontsize=56, text_color='#E6F6FB',
                                   highlight_color='#FFD166',
                                   subtitle_position=("center", 0.5),
                                   srt_cues=None,
                                   thumbnail_path=None,
                                   embed_thumbnail=False,
                                   thumbnail_duration=1.2,
                                   max_duration=None):
    """
    Create a 9:16 portrait clip and optionally prepend a thumbnail image as a short ImageClip.
    Uses only MoviePy + Pillow. debug_write_first_frame writes debug frames and prints their paths.
    """
    start_abs = float(cue.get('start', 0))
    end_abs = float(cue.get('end', start_abs + 1))
    if end_abs <= start_abs:
        raise ValueError("Invalid cue times: end must be > start")

    tmp_files = []
    try:
        with VideoFileClip(video_path) as clip:
            sub = clip.subclip(start_abs, end_abs)
            w, h = sub.w, sub.h
            split_x = int(max(0, min(1, split_x_ratio)) * w)
            left_x1, left_x2 = 0, max(1, split_x)
            right_x1, right_x2 = min(w-1, split_x), w

            left_half = sub.crop(x1=left_x1, x2=left_x2, y1=0, y2=h)
            right_half = sub.crop(x1=right_x1, x2=right_x2, y1=0, y2=h)

            half_h = int(target_h / 2)
            left_resized = left_half.resize(width=target_w, height=half_h).set_position(("center", 0)).set_duration(sub.duration)
            right_resized = right_half.resize(width=target_w, height=half_h).set_position(("center", half_h)).set_duration(sub.duration)

            base_final = CompositeVideoClip([left_resized, right_resized], size=(target_w, target_h))

            subtitle_overlays = []

            if srt_cues:
                for s_cue in srt_cues:
                    s_start = float(s_cue.get('start', 0))
                    s_end = float(s_cue.get('end', s_start + 0.001))
                    if s_end <= start_abs or s_start >= end_abs:
                        continue
                    cue_start_abs = max(s_start, start_abs)
                    cue_end_abs = min(s_end, end_abs)
                    text = s_cue.get('text', '').strip()
                    if not text:
                        continue
                    base_clip, overlays, tmp = _create_word_timed_subtitle_clips_for_cue(
                        full_text=text,
                        cue_start_abs=cue_start_abs,
                        cue_end_abs=cue_end_abs,
                        segment_start_abs=start_abs,
                        target_w=target_w,
                        target_h=target_h,
                        font_path=font_path,
                        fontsize=fontsize,
                        text_color=text_color,
                        highlight_color=highlight_color,
                        subtitle_position=subtitle_position,
                        fade=0.0
                    )
                    subtitle_overlays.extend(overlays)
                    tmp_files.extend(tmp)

            if not subtitle_overlays:
                text = (cue.get('text') or '').strip()
                if text:
                    _, overlays, tmp = _create_word_timed_subtitle_clips_for_cue(
                        full_text=text,
                        cue_start_abs=start_abs,
                        cue_end_abs=end_abs,
                        segment_start_abs=start_abs,
                        target_w=target_w,
                        target_h=target_h,
                        font_path=font_path,
                        fontsize=fontsize,
                        text_color=text_color,
                        highlight_color=highlight_color,
                        subtitle_position=subtitle_position,
                        fade=0.0
                    )
                    subtitle_overlays.extend(overlays)
                    tmp_files.extend(tmp)

            composed = CompositeVideoClip([base_final] + subtitle_overlays, size=(target_w, target_h))
            try:
                composed = composed.set_audio(sub.audio)
            except Exception:
                pass

            # Force composed to target size and fps
            fps_val = getattr(composed, "fps", None) or 24
            composed = composed.set_fps(fps_val).resize((target_w, target_h))

            # Ensure composed has an audio track matching its duration. MoviePy sometimes
            # leaves audio missing or shorter for long subclips; proactively attach audio
            # extracted from the source video for the same time range if needed.
            try:
                comp_audio = getattr(composed, "audio", None)
                if comp_audio is None:
                    from moviepy.editor import AudioFileClip
                    aclip = AudioFileClip(video_path).subclip(start_abs, end_abs)
                    composed = composed.set_audio(aclip)
                else:
                    try:
                        a_dur = getattr(comp_audio, "duration", None)
                        if a_dur is None or a_dur < (composed.duration - 0.05):
                            from moviepy.editor import AudioFileClip
                            aclip = AudioFileClip(video_path).subclip(start_abs, end_abs)
                            composed = composed.set_audio(aclip)
                    except Exception:
                        pass
            except Exception:
                pass

            final_clip = composed

            if embed_thumbnail and thumbnail_path and os.path.exists(thumbnail_path):
                try:
                    with Image.open(thumbnail_path) as im:
                        im = im.convert("RGB")
                        im_w, im_h = im.size
                        im_ratio = im_w / im_h
                        target_ratio = target_w / target_h
                        if im_ratio > target_ratio:
                            new_w = target_w
                            new_h = max(1, int(target_w / im_ratio))
                        else:
                            new_h = target_h
                            new_w = max(1, int(target_h * im_ratio))
                        fd, tmp_thumb = tempfile.mkstemp(suffix=".jpg")
                        os.close(fd)
                        im_resized = im.resize((new_w, new_h), Image.LANCZOS)
                        bg = Image.new("RGB", (target_w, target_h), (0, 0, 0))
                        paste_x = (target_w - new_w) // 2
                        paste_y = (target_h - new_h) // 2
                        bg.paste(im_resized, (paste_x, paste_y))
                        bg.save(tmp_thumb, format="JPEG", quality=90)
                    tmp_files.append(tmp_thumb)

                    thumb_clip = ImageClip(tmp_thumb).set_duration(float(thumbnail_duration)).set_position(("center", "center"))
                    thumb_clip = thumb_clip.set_fps(fps_val).resize((target_w, target_h))

                    final_clip = concatenate_videoclips([thumb_clip, composed], method="compose")
                    # If the composed clip has audio, shift it to start after the thumbnail clip
                    if getattr(composed, "audio", None) is not None:
                        try:
                            audio_shifted = composed.audio.set_start(thumb_clip.duration)
                            from moviepy.audio.AudioClip import CompositeAudioClip
                            final_audio = CompositeAudioClip([audio_shifted])
                            final_clip = final_clip.set_audio(final_audio)
                        except Exception:
                            # fallback to naive attach if shifting fails
                            final_clip = final_clip.set_audio(composed.audio)
                except Exception:
                    final_clip = composed

            # If a maximum duration was requested, trim the final clip to that length
            if max_duration is not None:
                try:
                    md = float(max_duration)
                except Exception:
                    md = None
                try:
                    if md is not None and final_clip.duration > md:
                        final_clip = final_clip.subclip(0, md)
                except Exception:
                    pass

            # Force final clip to exact size and fps before writing
            write_fps = getattr(final_clip, "fps", None) or fps_val or 24
            final_clip = final_clip.set_fps(write_fps).resize((target_w, target_h))

            final_clip.write_videofile(out_path,
                                       codec='libx264',
                                       audio_codec='aac',
                                       fps=write_fps,
                                       threads=1,
                                       preset='medium',
                                       verbose=True,
                                       logger=None)

            try:
                final_clip.close()
            except Exception:
                pass
            try:
                composed.close()
            except Exception:
                pass

    finally:
        # cleanup temporary png/jpg files created for subtitles and thumbnail
        for p in tmp_files:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


def make_portrait_full_video(video_path, out_path,
                             target_w=1080, target_h=1920,
                             split_x_ratio=0.5,
                             srt_cues=None,
                             font_path=None, fontsize=56,
                             text_color="#E6F6FB", highlight_color="#FFD166",
                             subtitle_position=("center", 0.5),
                             progress_cb=None):
    """
    Convert an entire horizontal video to 9:16 portrait format.
    Left half of the source is placed on the top half of the output,
    right half on the bottom — exactly the same layout used for clips.
    If srt_cues is provided, word-highlighted subtitles are embedded at subtitle_position.
    progress_cb(percent: int) is called periodically if provided.
    """
    tmp_files = []
    try:
        with VideoFileClip(video_path) as clip:
            w, h = clip.w, clip.h
            split_x = int(max(0, min(1, split_x_ratio)) * w)
            left_x1, left_x2 = 0, max(1, split_x)
            right_x1, right_x2 = min(w - 1, split_x), w

            left_half  = clip.crop(x1=left_x1,  x2=left_x2,  y1=0, y2=h)
            right_half = clip.crop(x1=right_x1, x2=right_x2, y1=0, y2=h)

            half_h = int(target_h / 2)
            left_resized  = left_half.resize(width=target_w, height=half_h).set_position(("center", 0)).set_duration(clip.duration)
            right_resized = right_half.resize(width=target_w, height=half_h).set_position(("center", half_h)).set_duration(clip.duration)

            base_final = CompositeVideoClip([left_resized, right_resized], size=(target_w, target_h))

            subtitle_overlays = []
            if srt_cues:
                for s_cue in srt_cues:
                    s_start = float(s_cue.get('start', 0))
                    s_end   = float(s_cue.get('end', s_start + 0.001))
                    # skip cues outside video duration
                    if s_end <= 0 or s_start >= clip.duration:
                        continue
                    cue_start_abs = max(s_start, 0.0)
                    cue_end_abs   = min(s_end, clip.duration)
                    text = s_cue.get('text', '').strip()
                    if not text:
                        continue
                    _, overlays, tmp = _create_word_timed_subtitle_clips_for_cue(
                        full_text=text,
                        cue_start_abs=cue_start_abs,
                        cue_end_abs=cue_end_abs,
                        segment_start_abs=0.0,
                        target_w=target_w,
                        target_h=target_h,
                        font_path=font_path,
                        fontsize=fontsize,
                        text_color=text_color,
                        highlight_color=highlight_color,
                        subtitle_position=subtitle_position,
                        fade=0.0,
                    )
                    subtitle_overlays.extend(overlays)
                    tmp_files.extend(tmp)

            layers = [base_final] + subtitle_overlays
            composed = CompositeVideoClip(layers, size=(target_w, target_h))

            try:
                composed = composed.set_audio(clip.audio)
            except Exception:
                pass

            fps_val = getattr(composed, "fps", None) or getattr(clip, "fps", None) or 24
            composed = composed.set_fps(fps_val).resize((target_w, target_h))

            composed.write_videofile(
                out_path,
                codec="libx264",
                audio_codec="aac",
                fps=fps_val,
                threads=2,
                preset="medium",
                verbose=False,
                logger=None,
            )

            try:
                composed.close()
            except Exception:
                pass
    finally:
        for p in tmp_files:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


def make_audio_reel(image_path, audio_path, out_path, start_time, end_time,
                    target_w=1080, target_h=1920):
    """
    Create a single 9:16 portrait reel: static background image + audio segment.
    Used by the Audio Clip Generator.
    """
    import tempfile
    audio = AudioFileClip(audio_path).subclip(start_time, end_time)
    with Image.open(image_path) as im:
        im = im.convert("RGB")
        im_w, im_h = im.size
        im_ratio = im_w / im_h
        target_ratio = target_w / target_h
        if im_ratio > target_ratio:
            new_h = target_h
            new_w = max(1, int(target_h * im_ratio))
        else:
            new_w = target_w
            new_h = max(1, int(target_w / im_ratio))
        im_resized = im.resize((new_w, new_h), Image.LANCZOS)
        bg = Image.new("RGB", (target_w, target_h), (0, 0, 0))
        paste_x = (target_w - new_w) // 2
        paste_y = (target_h - new_h) // 2
        bg.paste(im_resized, (paste_x, paste_y))
        fd, tmp_img = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        bg.save(tmp_img, "JPEG", quality=90)
    try:
        clip = ImageClip(tmp_img).set_duration(audio.duration).set_audio(audio)
        clip.write_videofile(
            out_path,
            fps=24,
            codec="libx264",
            audio_codec="aac",
            preset="medium",
            threads=2,
            verbose=False,
            logger=None,
        )
        clip.close()
        audio.close()
    finally:
        try:
            os.remove(tmp_img)
        except Exception:
            pass
