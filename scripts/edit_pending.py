#!/usr/bin/env python3
"""Find downloaded videos that have not been edited yet, and edit them.

Stage 2 of the split pipeline. Stage 1 (1-DOWNLOAD.bat) only fetches videos;
this walks the output folder, works out which ones are still raw, and runs the
caption stage on each. Anything already finished is skipped without touching
ffmpeg, so running this repeatedly is cheap.

    python edit_pending.py              # edit everything fresh
    python edit_pending.py --list       # show what would be done
    python edit_pending.py --limit 1    # just the next one
"""

import argparse
import subprocess
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

SCRIPT_DIR = Path(__file__).resolve().parent
BASE = SCRIPT_DIR.parent
VIDEO_DIR = BASE / "output" / "videos"
COVER = SCRIPT_DIR / "cover_caption.py"

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".m4v", ".webm"}
# Lower-cased on comparison: the staging folder is full of title-named
# mp4s and would otherwise look exactly like a video folder needing work.
SKIP_DIRS = {"final", "toupload"}


def source_video(folder):
    """The raw download in a video folder, never one of our own renders."""
    files = [p for p in folder.iterdir()
             if p.is_file() and p.suffix.lower() in VIDEO_EXTS
             and "covered" not in p.stem.lower() and "preview" not in p.stem.lower()]
    if not files:
        return None
    canonical = [p for p in files if p.stem.lower() == "video"]
    return canonical[0] if canonical else max(files, key=lambda p: p.stat().st_size)


def newest_render(folder):
    out = folder / "final"
    if not out.is_dir():
        return None
    videos = [p for p in out.iterdir()
              if p.is_file() and p.suffix.lower() in VIDEO_EXTS and p.stat().st_size > 1024]
    return max(videos, key=lambda p: p.stat().st_mtime) if videos else None


def scan():
    """Every video folder with a status: fresh, done, or why it cannot run."""
    if not VIDEO_DIR.is_dir():
        return []

    rows = []
    for folder in sorted(VIDEO_DIR.rglob("*")):
        if not folder.is_dir() or folder.name.lower() in SKIP_DIRS:
            continue
        if folder.parent.name.lower() in SKIP_DIRS:
            continue
        source = source_video(folder)
        if source is None:
            continue                       # a date folder, not a video folder

        render = newest_render(folder)
        frame = next((folder / n for n in ("frame.jpg", "frame.png") if (folder / n).exists()), None)

        if render is not None and render.stat().st_mtime >= source.stat().st_mtime:
            status = "done"
        elif frame is None:
            # download.py writes the frame; without it there is nothing to detect on.
            status = "no frame"
        else:
            status = "fresh"

        rows.append({"folder": folder, "source": source, "render": render, "status": status})

    rows.sort(key=lambda r: r["source"].stat().st_mtime)
    return rows


def main():
    parser = argparse.ArgumentParser(
        description="Edit every downloaded video that has not been edited yet.")
    parser.add_argument("--list", action="store_true", help="show what would run, do nothing")
    parser.add_argument("--limit", type=int, default=0, help="stop after N videos (0 = no limit)")
    parser.add_argument("--filter", default="vivid", help="colour grade (default: vivid)")
    parser.add_argument("--no-rewrite", action="store_true",
                        help="cover the caption without calling DeepSeek")
    args = parser.parse_args()

    rows = scan()
    fresh = [r for r in rows if r["status"] == "fresh"]
    done = [r for r in rows if r["status"] == "done"]
    broken = [r for r in rows if r["status"] == "no frame"]

    print()
    print("  " + "=" * 66)
    print("   STAGE 2 - EDIT")
    print("  " + "=" * 66)
    print(f"  {len(rows)} downloaded, {len(done)} already edited, {len(fresh)} fresh")

    for r in broken:
        print(f"  !! no frame.jpg, cannot edit: {r['folder'].name[:52]}")

    if not fresh:
        print("\n  Nothing fresh to edit - skipping.")
        return 0

    batch = fresh[:args.limit] if args.limit > 0 else fresh
    print(f"\n  Editing {len(batch)}:")
    for r in batch:
        print(f"    - {r['folder'].name[:60]}")

    if args.list:
        return 0

    failed = 0
    for i, r in enumerate(batch, 1):
        print("\n  " + "-" * 66)
        print(f"  [{i}/{len(batch)}] {r['folder'].name[:56]}")
        print("  " + "-" * 66)
        cmd = [sys.executable, str(COVER), "--skip-existing", "--filter", args.filter]
        if not args.no_rewrite:
            cmd.append("--rewrite")
        cmd.append(str(r["folder"]))
        if subprocess.run(cmd).returncode != 0:
            print(f"  FAILED on {r['folder'].name[:50]}")
            failed += 1

    print("\n  " + "=" * 66)
    print(f"  Edited {len(batch) - failed}, failed {failed}")
    print("  Finished videos are in output/videos/toupload/")
    print("  " + "=" * 66)
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit("\nInterrupted.")
