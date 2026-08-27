#!/usr/bin/env python3
"""Derive the whole pipeline's state from disk and emit it as JSON.

This is the single source of truth the dashboard reads. It does not track
anything of its own - every field is derived from the files the pipeline
already writes, so it cannot drift from reality:

    output/videos/<date>/<Title> [videoId]/
        video.mp4          <- download.py            => downloaded
        frame.jpg          <- download.py            => can be edited
        title.txt          <- download.py            (original title)
        title-new.txt      <- cover_caption.py       (rewritten title)
        caption.txt        <- cover_caption.py       (OCR of the original)
        final/<Title>.mp4  <- cover_caption.py       => edited
    output/videos/toupload/        <- staged copies awaiting upload
    output/videos/toupload/uploaded/ <- moved there by trainer.py after upload
    output/uploaded.json           <- upload record  => uploaded / successful
    output/shorts-log.txt          <- captured URLs  => scheduled
    output/downloaded.txt          <- yt-dlp archive

Usage:
    python scripts/pipeline_status.py                     # print JSON
    python scripts/pipeline_status.py --out dashboard/data/pipeline.json
    python scripts/pipeline_status.py --demo --out ...    # sample data, badged
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

BASE = Path(__file__).resolve().parent.parent
OUTPUT = BASE / "output"
VIDEO_DIR = OUTPUT / "videos"
STATE_FILE = OUTPUT / "uploaded.json"
LOG_FILE = OUTPUT / "shorts-log.txt"

FINAL_DIR = "final"
STAGE_DIR = "toupload"
VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".m4v", ".webm"}
ID_RE = re.compile(r"\[([A-Za-z0-9_-]{6,})\]\s*$")
URL_ID_RE = re.compile(r"(?:shorts/|watch\?v=|youtu\.be/)([A-Za-z0-9_-]{6,})")

# Statuses a folder may pin manually via status-override.txt. The pipeline has
# no concept of cancelling a video, so that state can only ever come from a
# human writing it down - which is exactly what this file is for.
OVERRIDE_FILE = "status-override.txt"
VALID_STATUSES = {
    "scheduled", "processing", "downloaded", "edited",
    "uploaded", "successful", "failed", "cancelled",
}


def iso(ts):
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def read_first_line(path):
    if not path.exists():
        return ""
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip():
                return line.strip()
    except OSError:
        return ""
    return ""


def load_upload_state():
    """Records of what has gone up.

    Two writers use this file with different keys: upload_queue.py keys by
    video id, trainer.py keys by the staged filename (the render is named
    after the rewritten title and carries no id). Both are read here.
    """
    if not STATE_FILE.exists():
        return {}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def newest_render(folder):
    out = folder / FINAL_DIR
    if not out.is_dir():
        return None
    try:
        vids = [p for p in out.iterdir()
                if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
    except OSError:
        return None
    return max(vids, key=lambda p: p.stat().st_mtime) if vids else None


def source_video(folder):
    """The raw download, never one of our own renders."""
    try:
        files = [p for p in folder.iterdir()
                 if p.is_file() and p.suffix.lower() in VIDEO_EXTS
                 and "covered" not in p.stem.lower()
                 and "preview" not in p.stem.lower()]
    except OSError:
        return None
    if not files:
        return None
    canonical = [p for p in files if p.stem.lower() == "video"]
    return canonical[0] if canonical else max(files, key=lambda p: p.stat().st_size)


def has_partial(folder):
    """A download or render still in flight leaves a part file behind."""
    try:
        return any(p.suffix.lower() in {".part", ".tmp", ".ytdl"}
                   for p in folder.iterdir() if p.is_file())
    except OSError:
        return False


def parse_shorts_log():
    """Captured URLs, newest first: timestamp, channel, URL, title (tab-separated)."""
    rows = {}
    if not LOG_FILE.exists():
        return rows
    try:
        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return rows

    for line in lines:
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split("\t")]
        url = next((p for p in parts if "http" in p), "")
        if not url:
            continue
        match = URL_ID_RE.search(url)
        if not match:
            continue
        vid = match.group(1)
        if vid in rows:
            continue                      # newest wins; the log is newest-first
        stamp = parts[0] if parts and "http" not in parts[0] else ""
        channel = next((p for p in parts if p.startswith("@")), "")
        title = parts[-1] if len(parts) > 2 and "http" not in parts[-1] else ""
        rows[vid] = {"url": url, "capturedAt": stamp, "channel": channel, "title": title}
    return rows


def derive_status(folder, source, render, upload_record):
    """Mirror of the rules the pipeline scripts already apply.

    Order matters: the furthest-along fact wins, so a video that has been
    uploaded reads as successful even though its earlier artifacts are all
    still on disk.
    """
    override = read_first_line(folder / OVERRIDE_FILE).lower()
    if override in VALID_STATUSES:
        return override, None

    if upload_record is not None:
        return "successful", None
    if has_partial(folder):
        return "processing", None
    if render is not None:
        if render.stat().st_size < 1024:
            return "failed", "render is truncated (under 1 KB)"
        if source is not None and render.stat().st_mtime >= source.stat().st_mtime:
            return "edited", None
        return "downloaded", None         # render is stale, needs re-editing
    if source is None:
        return "failed", "no source video in the folder"

    frame = next((folder / n for n in ("frame.jpg", "frame.png")
                  if (folder / n).exists()), None)
    if frame is None:
        return "failed", "no frame.jpg - cover_caption cannot detect the caption"
    return "downloaded", None


def collect():
    state = load_upload_state()
    log_rows = parse_shorts_log()
    videos = []
    seen_ids = set()

    if VIDEO_DIR.is_dir():
        for folder in VIDEO_DIR.rglob("*"):
            if not folder.is_dir():
                continue
            name = folder.name
            if name in (FINAL_DIR, STAGE_DIR, "uploaded"):
                continue
            if folder.parent.name in (STAGE_DIR,):
                continue
            match = ID_RE.search(name)
            if not match:
                continue

            video_id = match.group(1)
            seen_ids.add(video_id)

            source = source_video(folder)
            render = newest_render(folder)

            record = state.get(video_id)
            if record is None and render is not None:
                record = state.get(render.name)

            status, error = derive_status(folder, source, render, record)

            original = read_first_line(folder / "title.txt")
            rewritten = read_first_line(folder / "title-new.txt")
            title = rewritten or original or ID_RE.sub("", name).strip()

            stamps = [p.stat().st_mtime for p in folder.rglob("*") if p.is_file()]
            created = min(stamps) if stamps else folder.stat().st_mtime
            updated = max(stamps) if stamps else folder.stat().st_mtime

            uploaded_at = None
            if isinstance(record, dict):
                uploaded_at = record.get("uploaded_at")

            # Wall-clock from first artifact to upload - what the operator
            # actually waited, not CPU time.
            duration_ms = None
            if uploaded_at:
                try:
                    duration_ms = int(
                        (datetime.fromisoformat(uploaded_at).timestamp() - created) * 1000)
                    if duration_ms < 0:
                        duration_ms = None
                except ValueError:
                    duration_ms = None

            log_row = log_rows.get(video_id, {})

            videos.append({
                "id": video_id,
                "title": title,
                "originalTitle": original or None,
                "rewrittenTitle": rewritten or None,
                "caption": read_first_line(folder / "caption.txt") or None,
                "status": status,
                "error": error,
                "folder": str(folder.relative_to(BASE)).replace("\\", "/"),
                "batchDate": folder.parent.name if folder.parent != VIDEO_DIR else None,
                "sourceUrl": log_row.get("url")
                             or f"https://www.youtube.com/shorts/{video_id}",
                "channel": log_row.get("channel") or None,
                "scheduledAt": log_row.get("capturedAt") or None,
                "download": {
                    "done": source is not None,
                    "at": iso(source.stat().st_mtime) if source else None,
                    "sizeBytes": source.stat().st_size if source else None,
                    "hasFrame": any((folder / n).exists()
                                    for n in ("frame.jpg", "frame.png")),
                },
                "edit": {
                    "done": render is not None,
                    "at": iso(render.stat().st_mtime) if render else None,
                    "sizeBytes": render.stat().st_size if render else None,
                    "fileName": render.name if render else None,
                },
                "upload": {
                    "done": record is not None,
                    "at": uploaded_at,
                    "url": record.get("url") if isinstance(record, dict) else None,
                    "privacy": record.get("privacy") if isinstance(record, dict) else None,
                },
                "createdAt": iso(created),
                "updatedAt": iso(updated),
                "processingMs": duration_ms,
            })

    # Captured but never downloaded - the genuine "scheduled" bucket.
    for video_id, row in log_rows.items():
        if video_id in seen_ids:
            continue
        videos.append({
            "id": video_id,
            "title": row.get("title") or video_id,
            "originalTitle": row.get("title") or None,
            "rewrittenTitle": None,
            "caption": None,
            "status": "scheduled",
            "error": None,
            "folder": None,
            "batchDate": None,
            "sourceUrl": row.get("url"),
            "channel": row.get("channel") or None,
            "scheduledAt": row.get("capturedAt") or None,
            "download": {"done": False, "at": None, "sizeBytes": None, "hasFrame": False},
            "edit": {"done": False, "at": None, "sizeBytes": None, "fileName": None},
            "upload": {"done": False, "at": None, "url": None, "privacy": None},
            "createdAt": row.get("capturedAt") or None,
            "updatedAt": row.get("capturedAt") or None,
            "processingMs": None,
        })

    videos.sort(key=lambda v: v.get("updatedAt") or "", reverse=True)
    return videos


def summarise(videos):
    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week = today - timedelta(days=today.weekday())
    month = today.replace(day=1)

    def touched_since(v, when):
        stamp = v.get("updatedAt")
        if not stamp:
            return False
        try:
            return datetime.fromisoformat(stamp) >= when
        except ValueError:
            return False

    counts = {s: 0 for s in sorted(VALID_STATUSES)}
    for v in videos:
        counts[v["status"]] = counts.get(v["status"], 0) + 1

    durations = [v["processingMs"] for v in videos if v.get("processingMs")]

    return {
        "total": len(videos),
        "byStatus": counts,
        "downloaded": sum(1 for v in videos if v["download"]["done"]),
        "edited": sum(1 for v in videos if v["edit"]["done"]),
        "uploaded": sum(1 for v in videos if v["upload"]["done"]),
        "processedToday": sum(1 for v in videos if touched_since(v, today)),
        "processedThisWeek": sum(1 for v in videos if touched_since(v, week)),
        "processedThisMonth": sum(1 for v in videos if touched_since(v, month)),
        "avgProcessingMs": int(sum(durations) / len(durations)) if durations else None,
    }


def demo_videos():
    """Clearly-badged sample rows, so the UI can be reviewed before the first
    real run. The snapshot records source="demo" and the dashboard shows a
    banner - this is never presented as real pipeline data."""
    now = datetime.now()

    def ago(**kw):
        return (now - timedelta(**kw)).isoformat(timespec="seconds")

    rows = [
        ("dQw4w9WgXcQ", "He Tried To Outrun The Wave And Lost", "successful", 2, 40),
        ("kJQP7kiw5Fk", "The Cheapest City In Europe Right Now", "successful", 1, 26),
        ("9bZkp7q19f0", "Nobody Expected The Second Drop", "uploaded", 0, 9),
        ("3JZ_D3ELwOQ", "This Trick Saves You 40 Minutes A Day", "edited", 0, 4),
        ("L_jWHffIx5E", "Why Every Kitchen Gets This Wrong", "edited", 0, 3),
        ("fJ9rUzIMcZQ", "The Island That Runs On One Generator", "downloaded", 0, 2),
        ("ZbZSe6N_BXs", "He Bought It For $12 And Sold It For", "processing", 0, 1),
        ("hTWKbfoikeg", "The Rule Nobody Reads Until Too Late", "failed", 0, 5),
        ("YQHsXMglC9A", "She Found It Behind The Wall", "scheduled", 0, 0),
        ("CevxZvSJLk8", "The Recipe That Broke The Internet", "cancelled", 3, 70),
    ]

    videos = []
    for vid, title, status, days, hours in rows:
        created = now - timedelta(days=days, hours=hours)
        # Never let a sample row claim it was updated in the future.
        updated = min(now, created + timedelta(minutes=42))
        done = status in ("successful", "uploaded")
        edited = done or status == "edited"
        downloaded = edited or status in ("downloaded", "processing", "failed")
        videos.append({
            "id": vid,
            "title": title,
            "originalTitle": title,
            "rewrittenTitle": title if edited else None,
            "caption": None,
            "status": status,
            "error": "no frame.jpg - cover_caption cannot detect the caption"
                     if status == "failed" else None,
            "folder": f"output/videos/{created:%Y-%m-%d}/{title[:40]} [{vid}]",
            "batchDate": f"{created:%Y-%m-%d}",
            "sourceUrl": f"https://www.youtube.com/shorts/{vid}",
            "channel": "@Clips_Edge",
            "scheduledAt": created.isoformat(timespec="seconds"),
            "download": {
                "done": downloaded,
                "at": created.isoformat(timespec="seconds") if downloaded else None,
                "sizeBytes": 18_400_000 if downloaded else None,
                "hasFrame": downloaded and status != "failed",
            },
            "edit": {
                "done": edited,
                "at": (created + timedelta(minutes=12)).isoformat(timespec="seconds")
                      if edited else None,
                "sizeBytes": 21_900_000 if edited else None,
                "fileName": f"{title}.mp4" if edited else None,
            },
            "upload": {
                "done": done,
                "at": updated.isoformat(timespec="seconds") if done else None,
                "url": f"https://www.youtube.com/watch?v={vid}" if done else None,
                "privacy": "public" if done else None,
            },
            "createdAt": created.isoformat(timespec="seconds"),
            "updatedAt": updated.isoformat(timespec="seconds"),
            "processingMs": int(timedelta(minutes=42).total_seconds() * 1000) if done else None,
        })
    videos.sort(key=lambda v: v["updatedAt"], reverse=True)
    return videos


def main():
    parser = argparse.ArgumentParser(
        description="Emit the pipeline's current state as JSON for the dashboard.")
    parser.add_argument("--out", help="write here instead of stdout")
    parser.add_argument("--demo", action="store_true",
                        help="emit badged sample data instead of scanning disk")
    parser.add_argument("--quiet", action="store_true", help="no progress output")
    args = parser.parse_args()

    videos = demo_videos() if args.demo else collect()
    payload = {
        "source": "demo" if args.demo else "live",
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "root": str(BASE),
        "summary": summarise(videos),
        "videos": videos,
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    if args.out:
        out = Path(args.out)
        if not out.is_absolute():
            out = BASE / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        if not args.quiet:
            print(f"  {payload['source']} snapshot -> {out}")
            print(f"  {payload['summary']['total']} video(s)")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
