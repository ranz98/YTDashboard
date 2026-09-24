#!/usr/bin/env python3
"""Find the white caption box in a video's first frame and cover it up.

Detection runs once on frame.jpg (cheap), then the resulting rectangle is
painted over every frame with ffmpeg (fast) instead of decoding the whole
video in Python.

    python download.py            # writes video.mp4 + frame.jpg
    python cover_caption.py       # detects the caption, covers it

Outputs, alongside the video:
    frame-detected.jpg   the frame with the detected box outlined - CHECK THIS
    caption-box.txt      the coordinates, reusable
    caption-crop.png     just the caption, as fed to OCR
    caption.txt          the caption text, read out of the box
    video-covered.mp4    the covered video

If detection picks the wrong thing, pass the rectangle yourself:
    python cover_caption.py --box 120,430,1920,300
"""

import argparse
import json
import subprocess
import shutil
import sys
from pathlib import Path

# Windows consoles default to cp1252; an emoji in a caption would otherwise
# crash the run on the way to the screen, after all the real work was done.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

try:
    import cv2
    import numpy as np
except ImportError:
    sys.exit("OpenCV is required.\n  pip install opencv-python numpy")

BASE = Path(__file__).resolve().parent.parent
VIDEO_DIR = BASE / "output" / "videos"
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}


# --------------------------------------------------------------------------
# locating the work
# --------------------------------------------------------------------------

def newest_video_folder():
    """Most recently modified per-video folder under output/videos/<date>/."""
    if not VIDEO_DIR.is_dir():
        return None
    candidates = [p for p in VIDEO_DIR.rglob("*") if p.is_dir() and any(
        f.suffix.lower() in VIDEO_EXTS for f in p.iterdir() if f.is_file()
    )]
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def resolve_target(arg):
    """Return (folder, video_path, frame_path) from a folder or a video file."""
    folder = Path(arg).expanduser().resolve() if arg else newest_video_folder()
    if folder is None:
        sys.exit("No downloaded videos found. Run download.py first.")

    if folder.is_file():
        video, folder = folder, folder.parent
    else:
        # Never pick our own output: it is the largest file in the folder after
        # the first run, so re-running would cover an already-covered video and
        # stack another re-encode on top.
        videos = [
            p for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in VIDEO_EXTS and "covered" not in p.stem.lower()
        ]
        if not videos:
            sys.exit(f"No source video in {folder}")
        canonical = [p for p in videos if p.stem.lower() == "video"]
        video = canonical[0] if canonical else max(videos, key=lambda p: p.stat().st_size)

    frame = folder / "frame.jpg"
    if not frame.exists():
        for alt in ("frame.png", "frame.jpeg"):
            if (folder / alt).exists():
                frame = folder / alt
                break
    return folder, video, frame


def safe_filename(text, limit=110):
    """Turn a title into a Windows-safe file name.

    Emoji are dropped: fine in a YouTube title, awkward in a filename to type,
    script against or sync. Reserved characters go, runs of space collapse, and
    trailing dots and spaces are stripped because Windows silently rejects them.
    """
    import re as _re
    text = text or ""
    # Trailing hashtags are search metadata for YouTube, not part of a name.
    text = _re.sub(r"((?:\s#[^\s#]+)+)\s*$", "", text)
    text = "".join(ch for ch in text if ord(ch) < 0x2190)
    text = _re.sub(r'[<>:"/|?*]', "", text)
    text = "".join(ch for ch in text if ch == "\t" or ord(ch) >= 32)
    text = text.replace("\\", "")
    text = _re.sub(r"\s+", " ", text).strip()
    text = text.strip(". ")
    return text[:limit].strip(". ") or "video-covered"


def final_dir(folder):
    """Finished videos live in their own subfolder.

    Keeping the deliverable out of the working folder means the source-video
    picker can never mistake a finished render for the input and cover it twice
    -- and the finished file is free to be named after the title instead of a
    fixed name the rest of the code has to recognise.
    """
    return Path(folder) / "final"


def stage_dir(folder=None):
    """The shared collection folder: output/videos/toupload.

    One flat folder for every finished video, whatever day it was made, so the
    upload step has a single place to look and nothing has to be gathered from
    per-date folders first. The argument is accepted and ignored so callers do
    not have to care where the video came from.
    """
    return VIDEO_DIR / "toupload"


def stage_for_upload(out_path, folder):
    """Copy a finished render into the day's TOUPLOAD folder.

    A copy rather than a move: final/ stays the canonical output that
    --skip-existing and the upload queue read, and TOUPLOAD is a staging area
    that can be emptied at any time without the pipeline losing track.

    Returns (destination, copied) - copied is False when it was already there.
    """
    dest_dir = stage_dir(folder)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / out_path.name

    if (dest.exists()
            and dest.stat().st_size == out_path.stat().st_size
            and dest.stat().st_mtime >= out_path.stat().st_mtime):
        return dest, False

    shutil.copy2(out_path, dest)
    return dest, True

def existing_final(folder):
    """The newest finished render in a folder, whatever it ended up called."""
    out = final_dir(folder)
    if not out.is_dir():
        return None
    videos = [p for p in out.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
    return max(videos, key=lambda p: p.stat().st_mtime) if videos else None


# --------------------------------------------------------------------------
# detection
# --------------------------------------------------------------------------

def detect_caption(image, value=240, sat=20, min_width=0.30, region="all", pad=0.004):
    """Find the caption block anywhere in the frame. Returns (x, y, w, h) or None.

    Two things make the naive approach fail:

    1. Brightness alone is not enough -- a white hoodie or a sunlit wall is just
       as bright as the caption, and a morphological close then welds them into
       one blob covering half the frame. The caption is *pure* white, so gating
       on low saturation as well as high value separates it from bright but
       tinted video content.

    2. These captions draw a rounded background per LINE, and the lines have
       ragged widths. Bounding all of them at once leaves the corners empty, so
       a "how solidly filled is this rectangle" test rejects the real caption
       (measured 0.48 on a genuine three-line caption). Detecting each line as
       its own solid slab and then grouping neighbours sidesteps that entirely,
       and handles one-line captions for free.
    """
    h, w = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    saturation, brightness = hsv[:, :, 1], hsv[:, :, 2]
    mask = (((brightness >= value) & (saturation <= sat)) * 255).astype(np.uint8)

    # Wide but short: weld the glyphs inside a line without fusing the lines.
    kx = max(3, int(w * 0.020) | 1)
    ky = max(3, int(h * 0.004) | 1)
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                              cv2.getStructuringElement(cv2.MORPH_RECT, (kx, ky)))

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    def ink_of(x, y, bw, bh):
        return float(np.count_nonzero(closed[y:y + bh, x:x + bw]))

    # --- candidates -------------------------------------------------------
    # Two shapes reach us. Where the per-line backgrounds are separated, each
    # line is its own solid slab and the lines must be grouped. Where they
    # touch, the whole caption arrives as a single ragged component that no
    # per-line height cap would admit. Collect both and let scoring decide.
    lines, blocks = [], []
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        if bw < w * 0.08 or bw / max(bh, 1) < 1.2:
            continue
        fill = ink_of(x, y, bw, bh) / max(bw * bh, 1)

        if h * 0.004 <= bh <= h * 0.16 and bw / max(bh, 1) >= 1.5 and fill >= 0.62:
            lines.append((x, y, bw, bh, fill))       # one caption line
        if bh <= h * 0.35 and bw >= w * min_width and fill >= 0.40:
            blocks.append((x, y, bw, bh))            # a whole caption block

    if not lines and not blocks:
        return None
    lines.sort(key=lambda item: item[1])

    # --- group stacked lines into blocks ----------------------------------
    groups = []
    for line in lines:
        x, y, bw, bh, _ = line
        for group in groups:
            px, py, pw, ph, _ = group[-1]
            gap = y - (py + ph)
            left, right = max(x, px), min(x + bw, px + pw)
            overlap = max(0, right - left) / max(1, min(bw, pw))
            # Comparable line heights, or a banner sitting just under the
            # caption gets absorbed and the box grows past the real text.
            height_ratio = min(bh, ph) / max(bh, ph)
            # Stacked closely, column-aligned, and the same kind of line.
            if (-ph * 0.5 <= gap <= max(ph, bh) * 0.9
                    and overlap >= 0.50 and height_ratio >= 0.45):
                group.append(line)
                break
        else:
            groups.append([line])

    # --- pick the most caption-like candidate ------------------------------
    candidates = [
        (
            min(i[0] for i in g),
            min(i[1] for i in g),
            max(i[0] + i[2] for i in g) - min(i[0] for i in g),
            max(i[1] + i[3] for i in g) - min(i[1] for i in g),
        )
        for g in groups
    ] + blocks

    best, best_score = None, 0.0
    for gx, gy, gw, gh in candidates:
        if gw < w * min_width:
            continue
        centre = gy + gh / 2
        if region == "top" and centre > h * 0.60:
            continue
        if region == "bottom" and centre < h * 0.40:
            continue
        # White actually painted, weighted by how wide the block runs. Comparing
        # painted pixels rather than box area lets a ragged multi-line block and
        # a tidy stack of lines be judged on the same footing.
        score = ink_of(gx, gy, gw, gh) * (gw / w)
        if score > best_score:
            best, best_score = (gx, gy, gw, gh), score

    if best is None:
        return None

    x, y, bw, bh = best
    px, py = int(w * pad), int(h * pad * 0.5)
    x = max(0, x - px)
    y = max(0, y - py)
    bw = min(w - x, bw + 2 * px)
    bh = min(h - y, bh + 2 * py)
    return x, y, bw, bh


def save_preview(image, box, path):
    preview = image.copy()
    x, y, w, h = box
    thickness = max(2, int(image.shape[1] * 0.004))
    cv2.rectangle(preview, (x, y), (x + w, y + h), (0, 0, 255), thickness)
    cv2.imwrite(str(path), preview, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return path


# --------------------------------------------------------------------------
# reading the caption
# --------------------------------------------------------------------------

def ocr_windows(image_path):
    """Windows.Media.Ocr - built into Windows 10/11, nothing to install.

    Preferred over Tesseract because it needs no separate binary and no model
    download, and the caption is high-contrast black-on-white, which it reads
    essentially perfectly.
    """
    try:
        import asyncio
        from winsdk.windows.graphics.imaging import BitmapDecoder
        from winsdk.windows.media.ocr import OcrEngine
        from winsdk.windows.storage import FileAccessMode, StorageFile
    except ImportError:
        return None

    async def run():
        handle = await StorageFile.get_file_from_path_async(str(image_path))
        stream = await handle.open_async(FileAccessMode.READ)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            return None
        result = await engine.recognize_async(bitmap)
        return [line.text for line in result.lines]

    try:
        return asyncio.run(run())
    except Exception:
        return None


def ocr_tesseract(image_path):
    """Fallback. pytesseract is useless without the Tesseract binary, so check."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return None
    if not shutil.which("tesseract"):
        return None
    try:
        text = pytesseract.image_to_string(Image.open(image_path))
    except Exception:
        return None
    return [line.strip() for line in text.splitlines() if line.strip()] or None


def extract_caption_text(image, box, folder):
    """OCR just the detected rectangle. Returns (lines, crop_path)."""
    x, y, w, h = box
    crop_path = folder / "caption-crop.png"
    cv2.imwrite(str(crop_path), image[y:y + h, x:x + w])
    lines = ocr_windows(crop_path) or ocr_tesseract(crop_path)
    return lines, crop_path


# --------------------------------------------------------------------------
# covering
# --------------------------------------------------------------------------

# Grades applied to the whole frame BEFORE the caption is drawn, so the caption
# stays crisp and correctly coloured on top of a graded picture.
VIDEO_FILTERS = {
    "none": "",
    "vivid": "eq=contrast=1.10:saturation=1.32:brightness=0.02",
    "punch": "eq=contrast=1.18:saturation=1.18,unsharp=5:5:0.7:5:5:0.0",
    "warm": "colortemperature=temperature=5000,eq=saturation=1.12:contrast=1.05",
    "cool": "colortemperature=temperature=8500,eq=saturation=1.08:contrast=1.05",
    "bright": "eq=brightness=0.06:contrast=1.06:saturation=1.08",
    "fade": "eq=contrast=0.92:saturation=0.82:brightness=0.05",
    "cinematic": "eq=contrast=1.12:saturation=1.06,curves=preset=increase_contrast,vignette=PI/6",
    "clarity": "unsharp=5:5:0.9:5:5:0.0,eq=contrast=1.06:saturation=1.10",
    "bw": "hue=s=0,eq=contrast=1.12",
    "vignette": "vignette=PI/5",
}


def build_filter(box, mode, color, grade=""):
    """The ffmpeg filter graph: grade the picture, then hide the old caption.

    Everything downstream reads from one graded source, so a grade and a cover
    mode compose instead of fighting over the input pad.
    """
    x, y, w, h = box
    base = f"[0:v]{grade}[base];" if grade else ""
    src = "[base]" if grade else "[0:v]"

    if mode == "fill":
        chain = f"{src}drawbox=x={x}:y={y}:w={w}:h={h}:color={color}@1.0:t=fill"
        return base + chain

    if mode == "blur":
        radius = max(2, min(w, h) // 12)
        patch = f"boxblur=luma_radius={radius}:luma_power=2"
    elif mode == "pixelate":
        patch = (f"scale={max(2, w // 24)}:{max(2, h // 24)},"
                 f"scale={w}:{h}:flags=neighbor")
    else:
        raise ValueError(mode)

    return (base
            + f"{src}split=2[a][b];"
            + f"[b]crop={w}:{h}:{x}:{y},{patch}[cv];"
            + f"[a][cv]overlay={x}:{y}")


def cover_video(video, box, out_path, mode, color, crf, preset, ffmpeg,
                overlay=None, grade="", preview=0):
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-stats"]
    if preview:
        cmd += ["-t", str(preview)]
    cmd += ["-i", str(video)]

    if overlay is not None:
        # The PNG is opaque and exactly box-sized, so it covers the original
        # caption and draws the new one in a single pass.
        cmd += ["-i", str(overlay)]
        if grade:
            chain = f"[0:v]{grade}[base];[base][1:v]overlay={box[0]}:{box[1]}"
        else:
            chain = f"[0:v][1:v]overlay={box[0]}:{box[1]}"
        cmd += ["-filter_complex", chain]
    else:
        cmd += ["-filter_complex", build_filter(box, mode, color, grade)]

    cmd += [
        "-c:v", "libx264", "-crf", str(crf), "-preset", preset,
        "-pix_fmt", "yuv420p", "-c:a", "copy",
        str(out_path),
    ]

    result = subprocess.run(cmd)
    if result.returncode != 0 or not out_path.exists():
        # Audio copy fails when the source codec cannot sit in mp4; re-encode it.
        cmd[cmd.index("copy")] = "aac"
        result = subprocess.run(cmd)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed with exit code {result.returncode}")
    return out_path



def probe_size(video, ffprobe):
    if not ffprobe:
        return None
    out = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(video)],
        capture_output=True, text=True,
    )
    try:
        stream = json.loads(out.stdout)["streams"][0]
        return int(stream["width"]), int(stream["height"])
    except Exception:
        return None


# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Detect the white caption box in a video's first frame and cover it.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python cover_caption.py                       # newest download\n"
            "  python cover_caption.py <folder>              # a specific folder\n"
            "  python cover_caption.py --detect-only         # just find it, no render\n"
            "  python cover_caption.py --mode blur           # blur instead of a solid box\n"
            "  python cover_caption.py --box 120,430,1920,300\n"
        ),
    )
    parser.add_argument("target", nargs="?", help="video folder or file (default: newest download)")
    parser.add_argument("--box", help="override detection: x,y,w,h in pixels")
    parser.add_argument("--mode", default="fill", choices=["fill", "blur", "pixelate"])
    parser.add_argument("--filter", default="none", choices=sorted(VIDEO_FILTERS),
                        help="colour grade applied to the whole video (default: none)")
    parser.add_argument("--filter-custom", help="raw ffmpeg filter chain, overrides --filter")
    parser.add_argument("--preview", type=int, metavar="SECONDS", default=0,
                        help="render only the first N seconds, to video-preview.mp4")
    parser.add_argument("--color", default="white", help="box colour (default: white)")
    parser.add_argument("--region", default="all", choices=["top", "bottom", "all"],
                        help="where to look for the caption (default: all - it moves between videos)")
    parser.add_argument("--value", type=int, default=240,
                        help="minimum brightness 0-255 for 'white' (default: 240)")
    parser.add_argument("--sat", type=int, default=20,
                        help="maximum saturation 0-255; low = untinted white (default: 20)")
    parser.add_argument("--min-width", type=float, default=0.30,
                        help="caption must span this fraction of the width (default: 0.30)")
    parser.add_argument("--detect-only", action="store_true", help="detect and preview, do not render")
    parser.add_argument("--no-ocr", action="store_true", help="skip reading the caption text")
    parser.add_argument("--no-stage", action="store_true",
                        help="do not copy the finished video into TOUPLOAD")
    parser.add_argument("--no-title", action="store_true",
                        help="skip rewriting the video title")
    parser.add_argument("--skip-existing", action="store_true",
                        help="do nothing if video-covered.mp4 is already up to date")
    parser.add_argument("--rewrite", action="store_true",
                        help="rewrite the caption with DeepSeek and draw it in the box")
    parser.add_argument("--text", help="draw this exact text in the box (skips the AI)")
    parser.add_argument("--text-color", default="black", help="caption text colour (default: black)")
    parser.add_argument("--font", help="font name, alias or path (default: Montserrat)")
    parser.add_argument("--font-weight", default="SemiBold",
                        help="weight instance for variable fonts (default: SemiBold)")
    parser.add_argument("--api-key", help="DeepSeek key (else DEEPSEEK_API_KEY or deepseek-key.txt)")
    parser.add_argument("--crf", type=int, default=18, help="x264 quality, lower is better (default: 18)")
    parser.add_argument("--preset", default="veryfast", help="x264 preset (default: veryfast)")
    parser.add_argument("-o", "--out", help="output video path")
    args = parser.parse_args()

    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg:
        sys.exit("ffmpeg not found on PATH.")

    folder, video, frame = resolve_target(args.target)
    print(f"  Folder : {folder}")
    print(f"  Video  : {video.name}")

    if args.skip_existing and not args.preview:
        done = existing_final(folder)
        if done and done.stat().st_mtime >= video.stat().st_mtime:
            print(f"  Already processed -> final/{done.name}")
            print("  Nothing to do (pass --force or drop --skip-existing to redo it).")
            return 0

    if args.box:
        try:
            box = tuple(int(v) for v in args.box.split(","))
            if len(box) != 4:
                raise ValueError
        except ValueError:
            sys.exit("--box must be four integers: x,y,w,h")
        image = cv2.imread(str(frame)) if frame.exists() else None
        print(f"  Box    : {box}  (manual)")
    else:
        if not frame.exists():
            sys.exit(f"No frame image in {folder}. Re-run download.py, or pass --box.")
        image = cv2.imread(str(frame))
        if image is None:
            sys.exit(f"Could not read {frame}")
        print(f"  Frame  : {frame.name}  ({image.shape[1]}x{image.shape[0]})")

        box = detect_caption_auto(image, value=args.value, sat=args.sat,
                             min_width=args.min_width, region=args.region)
        if box is None:
            sys.exit(
                "No caption box found.\n"
                "  Try --region all, or relax the white test\n"
                "  (e.g. --value 225 --sat 35), or give it directly with --box x,y,w,h"
            )
        x, y, w, h = box
        pct = 100.0 * w * h / (image.shape[0] * image.shape[1])
        print(f"  Box    : x={x} y={y} w={w} h={h}   ({pct:.1f}% of the frame)")

    # The frame and the video must share dimensions or the box will not line up.
    size = probe_size(video, ffprobe)
    if size and image is not None and (size[0], size[1]) != (image.shape[1], image.shape[0]):
        print(f"  WARNING: frame is {image.shape[1]}x{image.shape[0]} but video is {size[0]}x{size[1]};")
        print("           coordinates will not line up.")

    (folder / "caption-box.txt").write_text(
        f"{box[0]},{box[1]},{box[2]},{box[3]}\n", encoding="utf-8"
    )

    if image is not None:
        preview = save_preview(image, box, folder / "frame-detected.jpg")
        print(f"  Preview: {preview.name}   <- check this before trusting it")

    caption_lines = None
    if image is not None and not args.no_ocr:
        caption_lines, crop_path = extract_caption_text(image, box, folder)
        if caption_lines:
            (folder / "caption.txt").write_text("\n".join(caption_lines) + "\n", encoding="utf-8")
            print(f"  Caption: {len(caption_lines)} line(s) -> caption.txt")
            for line in caption_lines:
                print(f"           {line}")
        else:
            print("  Caption: no OCR engine available, or no text found")
            print(f"           the crop is at {crop_path.name} if you want to read it")

    # --- new caption text, either from DeepSeek or supplied directly ---------
    overlay_png = None
    final_title = None
    if args.rewrite or args.text:
        import caption_text

        new_text = args.text
        if not new_text:
            # This run's OCR if we have it, else a caption.txt from a previous run.
            source = " ".join(caption_lines) if caption_lines else None
            if not source and (folder / "caption.txt").exists():
                source = (folder / "caption.txt").read_text(encoding="utf-8")
            if not source or not source.strip():
                sys.exit(
                    "Nothing to rewrite: no caption text available.\n"
                    "  Pass the text yourself with --text, or check why OCR found nothing."
                )
            source = " ".join(source.split())

            key = caption_text.load_api_key(args.api_key)
            if not key:
                sys.exit(
                    "No DeepSeek API key. Set DEEPSEEK_API_KEY, put it in "
                    "deepseek-key.txt, or pass --api-key."
                )
            print("  Rewrite: asking DeepSeek...")
            try:
                new_text, note = caption_text.rewrite_caption(source, key)
            except Exception as err:
                sys.exit(f"  DeepSeek failed: {type(err).__name__}: {err}")
            print(f"           {note}")

        (folder / "caption-new.txt").write_text(new_text + "\n", encoding="utf-8")
        print(f"  New    : {new_text}")

        overlay_png, pt, n_lines = caption_text.render_caption_png(
            new_text, (box[2], box[3]), folder / "caption-overlay.png",
            bg=args.color, fg=args.text_color,
            font_path=args.font, weight=args.font_weight,
        )
        print(f"  Overlay: {Path(overlay_png).name}  ({pt}px, {n_lines} line(s))")

        # --- the video title gets the same treatment ---------------------
        if args.rewrite and not args.no_title:
            title_file = folder / "title.txt"
            if not title_file.exists():
                print("  Title  : no title.txt in this folder - skipping the title")
            else:
                source_title = " ".join(title_file.read_text(encoding="utf-8").split())
                if not source_title:
                    print("  Title  : title.txt is empty - skipping")
                else:
                    key = caption_text.load_api_key(args.api_key)
                    print("  Title  : " + source_title)
                    # Trailing hashtags are search tags, not prose. Hold them
                    # aside so the model rewrites the sentence and does not
                    # spend its character budget on them, then put them back.
                    import re as _re
                    tag_match = _re.search(r"((?:\s#[^\s#]+)+)\s*$", source_title)
                    tags = tag_match.group(1).strip() if tag_match else ""
                    body = source_title[:tag_match.start()].strip() if tag_match else source_title
                    try:
                        new_body, tnote = caption_text.rewrite_title(body, key)
                        new_title = (new_body + " " + tags).strip() if tags else new_body
                        final_title = new_title
                        (folder / "title-new.txt").write_text(
                            new_title + "\n", encoding="utf-8")
                        print("           " + tnote + (" (+tags kept)" if tags else ""))
                        print("  Title+ : " + new_title)
                    except Exception as err:
                        print("  WARNING: title rewrite failed: "
                              + type(err).__name__ + ": " + str(err))

    if args.detect_only:
        print("\n  Detect-only; nothing rendered.")
        return 0

    grade = args.filter_custom or VIDEO_FILTERS.get(args.filter, "")

    if args.out:
        out_path = Path(args.out).expanduser().resolve()
    elif args.preview:
        out_path = folder / "video-preview.mp4"
    else:
        # Named after the rewritten title, in its own folder.
        out_dir = final_dir(folder)
        out_dir.mkdir(parents=True, exist_ok=True)
        name_source = final_title
        if not name_source:
            for candidate in ("title-new.txt", "title.txt"):
                item = folder / candidate
                if item.exists():
                    line = next((l.strip() for l
                                 in item.read_text(encoding="utf-8", errors="replace").splitlines()
                                 if l.strip()), "")
                    if line:
                        name_source = line
                        break
        out_path = out_dir / (safe_filename(name_source) + ".mp4")

        # A rerun with a different title would otherwise leave the old file
        # behind as a second, stale copy of the same video.
        for stale in out_dir.glob("*.mp4"):
            if stale.resolve() != out_path.resolve():
                try:
                    stale.unlink()
                    print(f"  Removed stale render: final/{stale.name}")
                except OSError:
                    pass
                old_copy = stage_dir(folder) / stale.name
                if old_copy.exists():
                    try:
                        old_copy.unlink()
                        print(f"  Removed stale copy:   TOUPLOAD/{old_copy.name}")
                    except OSError:
                        pass

    print(f"  Mode   : {'new caption' if overlay_png else args.mode}")
    if grade:
        print(f"  Filter : {args.filter_custom or args.filter}")
    if args.preview:
        print(f"  Preview: first {args.preview}s only")
    print(f"  Writing: {out_path.name}")
    try:
        cover_video(video, box, out_path, args.mode, args.color, args.crf,
                    args.preset, ffmpeg, overlay=overlay_png,
                    grade=grade, preview=args.preview)
    except RuntimeError as err:
        sys.exit(f"  FAILED: {err}")

    mb = out_path.stat().st_size / (1024 * 1024)
    print(f"\n  Done: {out_path}  ({mb:.1f} MB)")

    # Collect the finished video into the day's TOUPLOAD folder. Previews are
    # throwaway samples and an explicit --out is the caller's own destination,
    # so neither gets staged.
    if not args.preview and not args.out and not args.no_stage:
        try:
            dest, copied = stage_for_upload(out_path, folder)
            label = "Copied to" if copied else "Already in"
            print("  " + label + ": " + str(dest))
        except OSError as err:
            print("  WARNING: could not copy into TOUPLOAD: " + str(err))
    return 0




def detect_caption_v2(image, value=240, sat=20, min_width=0.30, region="all",
                      pad=0.004, dark=105, grow=0.42):
    """Locate the caption from its DARK TEXT instead of its white background.

    White-plate detection breaks whenever the caption sits on something white --
    an overexposed shirt, a bright wall. The plate merges with the background
    and the combined blob stops looking like a caption, so the detector wanders
    off to whatever else is bright.

    The black glyphs never merge with anything. Finding those first is stable
    regardless of what is behind the caption; the white plate is then recovered
    by growing the text block by a fraction of its own line height.

    Falls back to the white-plate detector when no text-like lines are found.
    """
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    mask = ((gray < dark).astype(np.uint8)) * 255

    # Wide and short: weld glyphs into a line, keep lines apart.
    kx = max(3, int(w * 0.018) | 1)
    ky = max(3, int(h * 0.002) | 1)
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                              cv2.getStructuringElement(cv2.MORPH_RECT, (kx, ky)))
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    lines = []
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        if bw < w * 0.12:                          # a caption line runs wide
            continue
        if not (h * 0.004 <= bh <= h * 0.05):      # one line, not a dark region
            continue
        if bw / max(bh, 1) < 3.0:
            continue
        # Caption text sits on a light plate; dark scenery does not.
        margin = max(2, int(bh * 0.5))
        band = gray[max(0, y - margin):min(h, y + bh + margin), x:x + bw]
        if float((band > 200).sum()) / max(band.size, 1) < 0.35:
            continue
        lines.append((x, y, bw, bh))

    if not lines:
        return detect_caption(image, value=value, sat=sat,
                              min_width=min_width, region=region, pad=pad)

    lines.sort(key=lambda item: item[1])
    groups = []
    for line in lines:
        x, y, bw, bh = line
        for group in groups:
            px, py, pw, ph = group[-1]
            gap = y - (py + ph)
            left, right = max(x, px), min(x + bw, px + pw)
            overlap = max(0, right - left) / max(1, min(bw, pw))
            ratio = min(bh, ph) / max(bh, ph)
            if -ph * 0.5 <= gap <= max(ph, bh) * 1.6 and overlap >= 0.35 and ratio >= 0.45:
                group.append(line)
                break
        else:
            groups.append([line])

    best, best_score = None, 0.0
    for group in groups:
        gx = min(i[0] for i in group)
        gy = min(i[1] for i in group)
        gw = max(i[0] + i[2] for i in group) - gx
        gh = max(i[1] + i[3] for i in group) - gy
        centre = gy + gh / 2
        if region == "top" and centre > h * 0.60:
            continue
        if region == "bottom" and centre < h * 0.40:
            continue
        score = sum(i[2] * i[3] for i in group) * (gw / w) * len(group) ** 0.5
        if score > best_score:
            best, best_score = (gx, gy, gw, gh, group), score

    if best is None:
        return detect_caption(image, value=value, sat=sat,
                              min_width=min_width, region=region, pad=pad)

    gx, gy, gw, gh, group = best
    line_h = sorted(i[3] for i in group)[len(group) // 2]

    # Measure the plate instead of guessing its margin: creep outward while the
    # next strip is still mostly light, so the box lands on the real plate edge
    # whatever padding this particular video uses. Capped, because a caption
    # sitting on a white shirt would otherwise grow until it swallowed the shirt.
    light = gray > 190
    step = max(1, int(line_h * 0.10))
    budget = max(2, int(line_h * grow * 4 / step))

    def strip_is_light(x0, y0, x1, y1):
        band = light[max(0, y0):max(0, y1), max(0, x0):max(0, x1)]
        return band.size > 0 and float(band.mean()) >= 0.55

    x0, y0, x1, y1 = gx, gy, gx + gw, gy + gh
    for _ in range(budget):
        moved = False
        if x0 - step >= 0 and strip_is_light(x0 - step, y0, x0, y1):
            x0 -= step; moved = True
        if x1 + step <= w and strip_is_light(x1, y0, x1 + step, y1):
            x1 += step; moved = True
        if y0 - step >= 0 and strip_is_light(x0, y0 - step, x1, y0):
            y0 -= step; moved = True
        if y1 + step <= h and strip_is_light(x0, y1, x1, y1 + step):
            y1 += step; moved = True
        if not moved:
            break
    x, y, bw, bh = x0, y0, x1 - x0, y1 - y0
    if bw < w * min_width:
        return detect_caption(image, value=value, sat=sat,
                              min_width=min_width, region=region, pad=pad)
    return x, y, bw, bh


def _caption_score(gray, box):
    """How much a rectangle looks like a caption: dark text on a light plate."""
    x, y, w, h = box
    patch = gray[y:y + h, x:x + w]
    if patch.size == 0:
        return 0.0
    dark = float((patch < 105).mean())
    light = float((patch > 190).mean())
    # Real captions carry a slab of text: some ink, mostly plate.
    if not (0.03 <= dark <= 0.55) or light < 0.35:
        return 0.05 * w
    return float(w) * (1.0 + dark)


def detect_caption_auto(image, **kwargs):
    """Run both detectors and reconcile them.

    They fail in opposite ways. The white-plate detector measures the plate
    accurately but wanders off when the caption sits on something white. The
    text-first detector is immune to the background but only bounds the glyphs,
    so it can under-cover the plate.

    When both land on the same caption their union is taken -- plate extent from
    one, text extent from the other. When they disagree, whichever actually
    looks like dark text on a light plate wins. Nothing here is tuned to a
    specific video; every number is measured from the frame in hand.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    plate = detect_caption(image, **kwargs)
    text = detect_caption_v2(image, **kwargs)

    if plate is None:
        return text
    if text is None:
        return plate
    if plate == text:
        return plate

    ax, ay, aw, ah = plate
    bx, by, bw, bh = text
    ox = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    oy = max(0, min(ay + ah, by + bh) - max(ay, by))
    overlap = (ox * oy) / max(1, min(aw * ah, bw * bh))

    if overlap >= 0.25:                     # same caption, seen two ways
        x0, y0 = min(ax, bx), min(ay, by)
        x1, y1 = max(ax + aw, bx + bw), max(ay + ah, by + bh)
        union = (x0, y0, x1 - x0, y1 - y0)
        # Only accept the union if it still reads as a caption; otherwise the
        # plate box was junk and merging would drag the box across the frame.
        if _caption_score(gray, union) >= max(_caption_score(gray, plate),
                                              _caption_score(gray, text)):
            return union

    return plate if _caption_score(gray, plate) > _caption_score(gray, text) else text


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit("\nInterrupted.")
