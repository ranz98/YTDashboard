#!/usr/bin/env python3
"""Download YouTube videos (Shorts included) and grab their first frame.

With no arguments it downloads whatever run.bat last captured, so the usual
flow is just:

    run.bat
    python download.py

Each video lands in its own folder, grouped by the date of the run:

    output/videos/2026-08-17/Some Title [oKy2HnwOESE]/
        video.mp4
        frame.jpg        <- first frame

Partial downloads are staged in the system temp folder, never in the output
tree -- OneDrive syncs half-written files and locks them mid-rename.

Already-downloaded videos are skipped via a yt-dlp download archive, matching
how run.bat only reports genuinely new Shorts.
"""

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# Windows consoles default to cp1252; an emoji in a caption would otherwise
# crash the run on the way to the screen, after all the real work was done.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

try:
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError
    from yt_dlp.version import __version__ as YTDLP_VERSION
except ImportError:
    sys.exit("yt-dlp is not installed.\n  pip install -U yt-dlp")

# YouTube rotates its player signature regularly, and an out-of-date yt-dlp
# cannot decrypt the format URLs. It fails in a confusing way -- the real
# formats vanish and only storyboard images remain -- so name the actual cure.
STALE_SIGNS = (
    "requested format is not available",
    "only images are available",
    "nsig extraction failed",
    "unable to extract",
    "failed to extract any player response",
    "sign in to confirm",
)
UPGRADE_HINT = (
    "  This usually means yt-dlp is out of date - YouTube changed its player\n"
    "  and the installed version cannot read the formats. Fix with:\n"
    "      python -m pip install -U yt-dlp"
)

SSL_SIGN = "certificate_verify_failed"
SSL_HINT = (
    "  TLS interception (Avast/Kaspersky/corporate proxy) is blocking yt-dlp:\n"
    "  it verifies against certifi's bundle, which lacks your scanner's root.\n"
    "  Point it at the system store instead:\n"
    "      set SSL_CERT_FILE=\n"
    "  or pass --insecure to skip verification for this run."
)

BASE = Path(__file__).resolve().parent
OUTPUT = BASE / "output"
LATEST_FILE = OUTPUT / "latest-short.txt"
LOG_FILE = OUTPUT / "shorts-log.txt"
DEFAULT_DIR = OUTPUT / "videos"
ARCHIVE_FILE = OUTPUT / "downloaded.txt"

URL_RE = re.compile(r"https?://[^\s]+")
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".flv"}


# --------------------------------------------------------------------------
# inputs
# --------------------------------------------------------------------------

def urls_from_file(path):
    """Pull every http(s) URL out of a text file, in order, without repeats.

    Works for both the bare-URL latest-short.txt and the tab-separated
    shorts-log.txt, so neither format needs special parsing.
    """
    if not path.exists():
        return []
    seen, found = set(), []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.lstrip().startswith("#"):
            continue
        for url in URL_RE.findall(line):
            url = url.rstrip(".,)")
            if url not in seen:
                seen.add(url)
                found.append(url)
    return found


def archive_ids(path):
    """Video IDs yt-dlp has already recorded, for the before/after diff."""
    if not path.exists():
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip()
    }


def resolve_urls(args):
    if args.urls:
        return list(dict.fromkeys(args.urls))

    if args.from_log:
        urls = urls_from_file(LOG_FILE)
        if not urls:
            sys.exit(f"No URLs found in {LOG_FILE}")
        return urls

    urls = urls_from_file(LATEST_FILE)
    if not urls:
        sys.exit(
            f"No URL given and nothing in {LATEST_FILE}.\n"
            "Run run.bat first, or pass a URL:\n"
            "  python download.py https://www.youtube.com/shorts/VIDEO_ID"
        )
    return urls


# --------------------------------------------------------------------------
# first frame
# --------------------------------------------------------------------------

def extract_first_frame(video_path, frame_path, ffmpeg):
    """Write the video's very first frame to frame_path.

    No -ss seek: seeking lands on the nearest keyframe, which is not
    necessarily frame 0. Decoding from the start and taking one frame is exact.
    """
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", str(video_path), "-frames:v", "1"]
    if frame_path.suffix.lower() in {".jpg", ".jpeg"}:
        cmd += ["-q:v", "2"]
    cmd.append(str(frame_path))

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not frame_path.exists():
        detail = (result.stderr or "").strip().splitlines()
        raise RuntimeError(detail[-1] if detail else f"ffmpeg exited {result.returncode}")
    return frame_path


def is_playable(path, ffprobe):
    """True if the file actually decodes as video.

    A download interrupted by OneDrive or antivirus can leave a full-size but
    structurally broken mp4. Without this check the archive would record it as
    done and it would be skipped forever.
    """
    if not ffprobe:
        return True  # cannot tell; assume fine rather than block the download
    result = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def forget_in_archive(video_id):
    """Drop an ID from the archive so a broken download can be retried."""
    if not video_id or not ARCHIVE_FILE.exists():
        return
    lines = ARCHIVE_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    kept = [line for line in lines if video_id not in line]
    if len(kept) != len(lines):
        ARCHIVE_FILE.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")


def fetch_title(url, insecure=False):
    """Ask YouTube for a video title without downloading anything.

    Uses its own YoutubeDL instance: the download one carries the archive, and
    a video already recorded there comes back with no metadata at all.
    """
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "nocheckcertificate": insecure,
    }
    try:
        with YoutubeDL(opts) as probe:
            info = probe.extract_info(url, download=False)
        return (info or {}).get("title")
    except Exception:
        return None

def save_title(folder, title):
    """Write the video title next to the video, for the rewrite stage.

    yt-dlp is the authority here: the folder name is truncated to 60 chars and
    stripped of characters Windows will not take, so it is not the real title.
    """
    if not title:
        return None
    path = Path(folder) / "title.txt"
    path.write_text(str(title).strip() + "\n", encoding="utf-8")
    return path


def title_from_folder(folder):
    """Best-effort title for a folder downloaded before titles were saved."""
    import re as _re
    return _re.sub(r"\s*\[[A-Za-z0-9_-]{6,}\]\s*$", "", Path(folder).name).strip()

def find_video_file(folder):
    """Locate the source media in a per-video folder.

    Never our own render: video-covered.mp4 is the largest file in the folder
    once it exists, so picking by size alone would hand a covered video back to
    the pipeline and cover it twice.
    """
    if not folder.is_dir():
        return None
    files = [p for p in folder.iterdir()
             if p.is_file() and p.suffix.lower() in VIDEO_EXTS
             and "covered" not in p.stem.lower()]
    if not files:
        return None
    canonical = [p for p in files if p.stem.lower() in ("video", "audio")]
    return canonical[0] if canonical else max(files, key=lambda p: p.stat().st_size)


# --------------------------------------------------------------------------
# download
# --------------------------------------------------------------------------


def video_id_from_url(url):
    """Pull the 11-ish char video id out of any normal YouTube URL."""
    m = re.search(r"(?:shorts/|watch\?v=|youtu\.be/|/embed/)([A-Za-z0-9_-]{6,})", url or "")
    return m.group(1) if m else None


def find_existing_folder(video_id, *roots):
    """Locate a previously downloaded video's folder by its id.

    The id is in every folder name precisely so a video can be found again
    after the archive says it is already downloaded.
    """
    if not video_id:
        return None
    hits = []
    for root in roots:
        root = Path(root) if root else None
        if root and root.is_dir():
            hits += [p for p in root.rglob("*")
                     if p.is_dir() and f"[{video_id}]" in p.name]
    return max(hits, key=lambda p: p.stat().st_mtime) if hits else None


def ensure_frame(media, folder, args, ffmpeg):
    """Guarantee a first frame exists for a video we did not just download."""
    if args.audio_only or args.no_frame or not ffmpeg or not media:
        return None
    target = folder / f"frame.{args.frame_format}"
    if target.exists():
        return target
    try:
        frame = extract_first_frame(media, target, ffmpeg)
        print(f"  first frame -> {frame.name}")
        return frame
    except RuntimeError as err:
        print(f"  WARNING: could not extract the frame: {err}")
        return None

def build_options(args, outdir, day):
    # Dated day folder, then one folder per video. The ID is in the folder name
    # because Shorts titles collide and get truncated; the inner filename is
    # fixed so downstream steps have a predictable path.
    #
    # Relative template + paths["home"]: that is what lets paths["temp"] send
    # the .part files somewhere else entirely.
    name = "audio" if args.audio_only else "video"
    template = str(Path(day) / "%(title).60s [%(id)s]" / f"{name}.%(ext)s")

    # Partial files must never live in OneDrive: it syncs them mid-write, which
    # locks the .part file and makes the final rename fail with WinError 32.
    staging = Path(tempfile.gettempdir()) / "fsg-download"
    staging.mkdir(parents=True, exist_ok=True)

    opts = {
        "outtmpl": template,
        "paths": {"home": str(outdir), "temp": str(staging)},
        "windowsfilenames": True,
        "noplaylist": True,
        "quiet": args.quiet,
        "no_warnings": args.quiet,
        "consoletitle": False,
        "retries": 5,
        "fragment_retries": 5,
        "ignoreerrors": False,
        "nocheckcertificate": args.insecure,
    }

    if not args.no_archive:
        ARCHIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
        opts["download_archive"] = str(ARCHIVE_FILE)

    if args.audio_only:
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
        ]
    else:
        height = f"[height<={args.max_height}]" if args.max_height else ""
        # bestvideo+bestaudio needs ffmpeg to mux; `best` covers a box without it.
        opts["format"] = f"bestvideo{height}+bestaudio/best{height}/best"
        opts["merge_output_format"] = "mp4"

    return opts


def downloaded_path(ydl, info):
    """Where the media actually ended up, after any merge or postprocessing."""
    for entry in info.get("requested_downloads") or []:
        if entry.get("filepath"):
            return Path(entry["filepath"])
    # Archive skip: nothing was downloaded now, so fall back to the folder the
    # template points at and reuse whatever is already sitting there.
    return find_video_file(Path(ydl.prepare_filename(info)).parent)


def main():
    parser = argparse.ArgumentParser(
        description="Download YouTube videos and save each one's first frame.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python download.py                       # the last captured Short\n"
            "  python download.py <url> <url>           # specific videos\n"
            "  python download.py --from-log            # everything in shorts-log.txt\n"
            "  python download.py --frame-format png    # png instead of jpg\n"
            "  python download.py --max-height 720      # cap the resolution\n"
            "  python download.py --audio-only          # mp3, no frame\n"
        ),
    )
    parser.add_argument("urls", nargs="*", help="video URLs (default: output/latest-short.txt)")
    parser.add_argument("--from-log", action="store_true", help="download every URL in shorts-log.txt")
    parser.add_argument("-o", "--outdir", default=str(DEFAULT_DIR), help=f"output folder (default: {DEFAULT_DIR})")
    parser.add_argument("--audio-only", action="store_true", help="extract audio as mp3 (no frame)")
    parser.add_argument("--max-height", type=int, metavar="PX", help="cap video height, e.g. 1080")
    parser.add_argument("--no-frame", action="store_true", help="skip first-frame extraction")
    parser.add_argument("--frame-format", default="jpg", choices=["jpg", "png"], help="frame image format (default: jpg)")
    parser.add_argument("--no-archive", action="store_true", help="re-download even if already fetched")
    parser.add_argument("--insecure", action="store_true", help="skip TLS verification (TLS-intercepting antivirus)")
    parser.add_argument("--date", metavar="YYYY-MM-DD", help="date folder to use (default: today)")
    parser.add_argument("-q", "--quiet", action="store_true", help="less output")
    args = parser.parse_args()

    urls = resolve_urls(args)
    outdir = Path(args.outdir).expanduser().resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    want_frame = not args.no_frame and not args.audio_only
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if want_frame and not ffmpeg:
        print("  NOTE: ffmpeg not found - frames will be skipped.\n")
        want_frame = False

    day = args.date or datetime.now().strftime("%Y-%m-%d")

    print(f"  yt-dlp  : {YTDLP_VERSION}")
    print(f"  Videos  : {len(urls)}")
    print(f"  Output  : {outdir / day}")
    print(f"  Frame   : {'first frame -> frame.' + args.frame_format if want_frame else 'disabled'}")
    print(f"  Archive : {'disabled' if args.no_archive else ARCHIVE_FILE}")
    print("  " + "-" * 62)

    before = archive_ids(ARCHIVE_FILE)
    failed, results, reused = [], [], []

    opts = build_options(args, outdir, day)
    # One URL per call so a single bad link cannot abort the rest.
    with YoutubeDL(opts) as ydl:
        for i, url in enumerate(urls, 1):
            print(f"\n  [{i}/{len(urls)}] {url}")
            try:
                info = ydl.extract_info(url, download=True)

                if not info:
                    # yt-dlp returns nothing when this video is already in the
                    # archive. That is a skip, not a failure -- find what was
                    # fetched last time so later stages can carry straight on.
                    vid = video_id_from_url(url)
                    folder = find_existing_folder(vid, outdir, DEFAULT_DIR)

                    if folder is not None:
                        media = find_video_file(folder)
                        if not (folder / "title.txt").exists():
                            # Folder names are truncated to 60 chars and stripped
                            # of characters Windows rejects, so ask YouTube for
                            # the real title rather than reading it back off disk.
                            real = fetch_title(url, args.insecure)
                            save_title(folder, real or title_from_folder(folder))
                        frame = ensure_frame(media, folder, args, ffmpeg)
                        print(f"  already downloaded -> {folder.name}")
                        reused.append((folder, media, frame))
                        continue

                    # Recorded as done but the files are gone (moved, deleted,
                    # a failed earlier run). Clear the record and fetch it now
                    # rather than making the user run the whole thing again.
                    print("  in the archive but its files are missing - re-fetching")
                    forget_in_archive(vid)
                    # yt-dlp caches the archive in memory at startup, so
                    # rewriting the file alone would not stop it skipping again.
                    if getattr(ydl, "archive", None):
                        stale = {e for e in ydl.archive if e.endswith(f" {vid}")}
                        ydl.archive.difference_update(stale)
                    info = ydl.extract_info(url, download=True)
                    if not info:
                        failed.append((url, "could not re-fetch after clearing the archive"))
                        continue


                media = downloaded_path(ydl, info)
                if not media or not media.exists():
                    failed.append((url, "could not locate the downloaded file"))
                    continue

                if not args.audio_only and not is_playable(media, ffprobe):
                    # Un-record it so the next run retries instead of skipping.
                    forget_in_archive(info.get("id"))
                    failed.append((
                        url,
                        f"downloaded file is corrupt: {media}\n"
                        "      removed from the archive so the next run retries it",
                    ))
                    continue

                save_title(media.parent, info.get("title"))

                frame = None
                if want_frame:
                    target = media.parent / f"frame.{args.frame_format}"
                    try:
                        frame = extract_first_frame(media, target, ffmpeg)
                        print(f"  first frame -> {frame.name}")
                    except RuntimeError as err:
                        print(f"  WARNING: could not extract the frame: {err}")

                results.append((media.parent, media, frame))

            except DownloadError as err:
                text = str(err).strip().splitlines()
                failed.append((url, text[-1] if text else "download error"))
            except Exception as err:  # noqa: BLE001 - report and keep going
                failed.append((url, f"{type(err).__name__}: {err}"))

    added = archive_ids(ARCHIVE_FILE) - before

    print("\n  " + "=" * 62)
    print(f"  Downloaded : {len(added)}")
    if reused:
        print(f"  Skipped    : {len(reused)} (already downloaded, reusing them)")
    if failed:
        print(f"  Failed     : {len(failed)}")
        for url, reason in failed:
            print(f"    - {url}\n      {reason}")

        blob = " ".join(reason for _, reason in failed).lower()
        if SSL_SIGN in blob:
            print("\n" + SSL_HINT)
        elif any(sign in blob for sign in STALE_SIGNS):
            print("\n" + UPGRADE_HINT)

    for folder, media, frame in results + reused:
        print(f"\n  {folder}")
        if media:
            print(f"    {media.name}")
        if frame:
            print(f"    {frame.name}")
    print("  " + "=" * 62)

    # Hand the exact folder to the next stage. Without this it would fall back
    # to "the newest folder", which is the wrong video whenever the one we were
    # asked for had already been downloaded on an earlier day.
    ready = results + reused
    if ready:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        (OUTPUT / "last-folder.txt").write_text(str(ready[-1][0]) + "\n", encoding="utf-8")

    # Nothing new to fetch is a success: the files are there either way.
    return 0 if ready else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit("\nInterrupted.")
