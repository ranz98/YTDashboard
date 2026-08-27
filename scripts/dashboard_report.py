#!/usr/bin/env python3
"""Report pipeline activity from the VPS to the dashboard.

The scheduled .bat files call this at the start and end of every stage, so the
dashboard shows what is running right now, what finished, and what failed -
without anyone opening the VPS.

Configure once on the VPS (System environment variables, so Task Scheduler
sees them too):

    DASHBOARD_URL     https://your-dashboard.vercel.app
    DASHBOARD_TOKEN   the same value as INGEST_TOKEN in the Vercel project

Usage:
    python scripts/dashboard_report.py start   --stage download
    python scripts/dashboard_report.py finish  --stage download --exit-code 0
    python scripts/dashboard_report.py finish  --stage edit --exit-code 1 \
        --message "ffmpeg failed"
    python scripts/dashboard_report.py sync            # push a full snapshot

Every failure here is non-fatal and exits 0: reporting is observability, and a
dashboard being unreachable must never take down the pipeline that feeds it.
"""

import argparse
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

BASE = Path(__file__).resolve().parent.parent
OUTPUT = BASE / "output"
# Records the start time of each stage so `finish` can report a duration
# without the .bat having to carry state between two separate processes.
RUN_DIR = OUTPUT / "runs"

TIMEOUT = 10


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def config():
    url = os.environ.get("DASHBOARD_URL", "").strip().rstrip("/")
    token = os.environ.get("DASHBOARD_TOKEN", "").strip()
    return url, token


def post(path, payload):
    """POST JSON. Returns True on success; never raises."""
    url, token = config()
    if not url or not token:
        print("  dashboard: DASHBOARD_URL / DASHBOARD_TOKEN not set - skipping")
        return False

    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{url}{path}",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Ingest-Token": token,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            if 200 <= response.status < 300:
                print(f"  dashboard: {path} ok")
                return True
            print(f"  dashboard: {path} returned {response.status}")
            return False
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:300]
        print(f"  dashboard: {path} HTTP {error.code} - {detail}")
    except (urllib.error.URLError, OSError, ValueError) as error:
        print(f"  dashboard: {path} unreachable - {error}")
    return False


def run_id(stage):
    return RUN_DIR / f"{stage}.json"


def cmd_start(args):
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    started = now_iso()
    ident = f"{args.stage}-{started.replace(':', '').replace('-', '')}"

    run_id(args.stage).write_text(
        json.dumps({"id": ident, "startedAt": started}), encoding="utf-8")

    post("/api/events", {
        "id": ident,
        "stage": args.stage,
        "status": "running",
        "startedAt": started,
        "host": socket.gethostname(),
        "message": args.message,
    })
    return 0


def cmd_finish(args):
    started = None
    ident = None
    marker = run_id(args.stage)
    if marker.exists():
        try:
            saved = json.loads(marker.read_text(encoding="utf-8"))
            started = saved.get("startedAt")
            ident = saved.get("id")
        except (ValueError, OSError):
            pass

    finished = now_iso()
    started = started or finished
    ident = ident or f"{args.stage}-{finished.replace(':', '').replace('-', '')}"

    if args.skipped:
        status = "skipped"
    elif args.exit_code == 0:
        status = "success"
    else:
        status = "failed"

    duration = None
    try:
        duration = int(
            (datetime.fromisoformat(finished).timestamp()
             - datetime.fromisoformat(started).timestamp()) * 1000)
    except ValueError:
        duration = None

    post("/api/events", {
        "id": ident,
        "stage": args.stage,
        "status": status,
        "startedAt": started,
        "finishedAt": finished,
        "durationMs": duration,
        "exitCode": args.exit_code,
        "message": args.message,
        "host": socket.gethostname(),
        "videoId": args.video_id,
        "videoTitle": args.video_title,
    })

    try:
        marker.unlink(missing_ok=True)
    except OSError:
        pass

    # A finished stage changed the video tree, so push the new state too.
    cmd_sync(args)
    return 0


def cmd_sync(args):
    """Rebuild the snapshot from disk and push it."""
    sys.path.insert(0, str(BASE / "scripts"))
    try:
        import pipeline_status
    except ImportError as error:
        print(f"  dashboard: cannot import pipeline_status - {error}")
        return 0

    try:
        videos = pipeline_status.collect()
        payload = {
            "source": "live",
            "generatedAt": datetime.now().isoformat(timespec="seconds"),
            "root": str(BASE),
            "summary": pipeline_status.summarise(videos),
            "videos": videos,
        }
    except Exception as error:                       # never break the pipeline
        print(f"  dashboard: could not build snapshot - {error}")
        return 0

    # Keep a local copy so the committed snapshot and the pushed one agree.
    try:
        out = BASE / "dashboard" / "data" / "pipeline.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    except OSError:
        pass

    post("/api/pipeline", payload)
    return 0


def main():
    parser = argparse.ArgumentParser(description="Report pipeline activity to the dashboard.")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--stage", required=True,
                        choices=["download", "edit", "upload", "pipeline"])
    common.add_argument("--message", default=None)
    common.add_argument("--video-id", default=None)
    common.add_argument("--video-title", default=None)

    sub.add_parser("start", parents=[common]).set_defaults(func=cmd_start)

    finish = sub.add_parser("finish", parents=[common])
    finish.add_argument("--exit-code", type=int, default=0)
    finish.add_argument("--skipped", action="store_true",
                        help="finished cleanly with nothing to do")
    finish.set_defaults(func=cmd_finish)

    syncer = sub.add_parser("sync")
    syncer.add_argument("--stage", default="pipeline")
    syncer.add_argument("--message", default=None)
    syncer.add_argument("--video-id", default=None)
    syncer.add_argument("--video-title", default=None)
    syncer.set_defaults(func=cmd_sync)

    args = parser.parse_args()
    try:
        return args.func(args)
    except Exception as error:
        print(f"  dashboard: reporter error (ignored) - {error}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
