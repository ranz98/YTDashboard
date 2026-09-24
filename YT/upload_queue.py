#!/usr/bin/env python3
"""Work out which processed videos are waiting to be uploaded.

Kept separate from the uploader so the queue can be inspected without touching
credentials or the network:

    python upload_queue.py            # every video and its status
    python upload_queue.py --pending  # just the ones ready to go

A video is READY when its folder holds a finished video-covered.mp4 and its id
is not already recorded in output/uploaded.json. The id comes from the folder
name, which is why the downloader puts it there.
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

BASE = Path(__file__).resolve().parent
OUTPUT = BASE / "output"
VIDEO_DIR = OUTPUT / "videos"
STATE_FILE = OUTPUT / "uploaded.json"

FINAL_DIR = "final"
VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".m4v"}
ID_RE = re.compile(r"\[([A-Za-z0-9_-]{6,})\]\s*$")


def load_state():
    """Record of what has already gone up. Never guessed - only written after
    YouTube confirms an upload, so a crash mid-run cannot mark a video done."""
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def save_state(state):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")


def mark_uploaded(video_id, youtube_id, title, privacy):
    state = load_state()
    state[video_id] = {
        "youtube_id": youtube_id,
        "url": "https://www.youtube.com/watch?v=" + str(youtube_id),
        "title": title,
        "privacy": privacy,
        "uploaded_at": datetime.now().isoformat(timespec="seconds"),
    }
    save_state(state)
    return state[video_id]


def newest_render(folder):
    """The finished video inside <folder>/final/, whatever the title named it.

    The render is named after the rewritten title, so nothing downstream can
    look for a fixed filename any more.
    """
    out = Path(folder) / FINAL_DIR
    if not out.is_dir():
        return None
    videos = [p for p in out.iterdir()
              if p.is_file() and p.suffix.lower() in VIDEO_EXTS and p.stat().st_size > 1024]
    return max(videos, key=lambda p: p.stat().st_mtime) if videos else None


def read_first_line(path):
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            return line.strip()
    return ""


def title_for(folder):
    """Prefer the rewrite, fall back to the original, then the folder name."""
    for name in ("title-new.txt", "title.txt"):
        text = read_first_line(folder / name)
        if text:
            return text, name
    return ID_RE.sub("", folder.name).strip(), "folder name"


def scan():
    """Every per-video folder, newest first, with its upload status."""
    if not VIDEO_DIR.is_dir():
        return []

    state = load_state()
    rows = []
    for folder in VIDEO_DIR.rglob("*"):
        if not folder.is_dir():
            continue
        match = ID_RE.search(folder.name)
        if not match:
            continue
        if folder.name == FINAL_DIR:
            continue                       # that is a render folder, not a video
        video_id = match.group(1)
        final = newest_render(folder)
        title, title_src = title_for(folder)

        if video_id in state:
            status = "uploaded"
        elif final is None:
            status = "not processed"
        elif final.stat().st_size < 1024:
            status = "bad file"
        else:
            status = "ready"

        rows.append({
            "id": video_id,
            "folder": folder,
            "video": final,
            "title": title,
            "title_source": title_src,
            "status": status,
            "record": state.get(video_id),
        })

    rows.sort(key=lambda r: r["folder"].stat().st_mtime, reverse=True)
    return rows


def pending(rows=None):
    return [r for r in (rows if rows is not None else scan()) if r["status"] == "ready"]


def main():
    parser = argparse.ArgumentParser(description="Show which videos are waiting to upload.")
    parser.add_argument("--pending", action="store_true", help="list only videos ready to upload")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    rows = scan()
    if args.pending:
        rows = [r for r in rows if r["status"] == "ready"]

    if args.json:
        print(json.dumps([
            {k: (str(v) if isinstance(v, Path) else v)
             for k, v in r.items() if k != "record"}
            for r in rows
        ], indent=2, ensure_ascii=False))
        return 0

    if not rows:
        print("  Nothing found. Run RUNPIPELINE.bat first.")
        return 0

    counts = {}
    print("  " + "-" * 74)
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        mark = {"ready": "->", "uploaded": "ok", "not processed": "..",
                "bad file": "!!"}.get(r["status"], "??")
        print(f"  {mark} [{r['status']:<13}] {r['title'][:56]}")
        if r["record"]:
            print(f"     {r['record']['url']}  ({r['record']['privacy']})")
    print("  " + "-" * 74)
    print("  " + ", ".join(f"{n} {s}" for s, n in sorted(counts.items())))

    ready = counts.get("ready", 0)
    if ready:
        print(f"\n  {ready} ready. Upload with:  UPLOAD.bat")
    else:
        print("\n  Nothing pending.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
