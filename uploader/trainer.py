"""YouTube Studio upload automation.

Buttons are found with saved reference images (template matching) instead of
colour guessing, because the layout and button art are identical on every run.

    Select files  ->  buttons/select_files_*.png
    Next          ->  buttons/next_*.png
    Publish       ->  buttons/publish_*.png

SETUP
-----
    pip install pyautogui opencv-python pillow numpy pygetwindow

TEACH IT THE BUTTONS (do this once per button)
----------------------------------------------
    1. Get the button on screen in YouTube Studio.
    2. Run the matching capture command below.
       A frozen screenshot appears - drag a tight box around the button and
       release. Esc cancels.
    3. Capture 2-3 variants of each (normal state, hover state, a different
       window size). More images = more reliable.

        python trainder.py --capture select_files      (or --capture-button)
        python trainder.py --capture next              (or --capture-next)
        python trainder.py --capture publish           (or --capture-publish)

    Capture Next while you are ON the details screen, where Next actually
    shows. Crop the button only - no surrounding page, no drop shadow.

CHECK IT WORKS (never clicks anything)
--------------------------------------
    python trainder.py --list-buttons
    python trainder.py --test-detect            (defaults to select_files)
    python trainder.py --test-detect next
    python trainder.py --test-detect publish

    Prints the match score and writes buttons/debug/<time>.png with a box
    drawn where it thinks the button is.

TUNING
------
    --button-confidence  0.80   threshold for Select files
    --next-confidence    0.72   threshold for Next (busier toolbar, so it
                                usually wants a lower number)
    --publish-confidence 0.80   threshold for Publish on its own

    --strict-publish            never click Publish on a guess. Without a
                                saved publish_*.png the run stops instead of
                                reusing the Next images or blind-clicking the
                                bottom-right corner. Recommended once you have
                                captured Publish - the click is public and
                                cannot be undone.

NORMAL RUN
----------
    python trainder.py
    python trainder.py "D:\\testvideos\\myclip.mp4"
"""

import argparse
import faulthandler
import os
import random
import platform
import sys
import time
import traceback
import shutil  # <-- Added for moving files
from datetime import datetime
from pathlib import Path

import pyautogui
from PIL import Image, ImageDraw

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


# Checked in order when no path is passed on the command line.
# UPLOAD_VIDEO_SOURCE (env var) is always tried first.
DEFAULT_VIDEO_SOURCES = [
    r"C:\Users\Administrator\Pictures\YTchromeNEON\output\videos\toupload",
    r"D:\testvideos",
]
VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".m4v",
    ".avi",
    ".mkv",
    ".webm",
    ".wmv",
    ".flv",
}

SCRIPT_DIR = Path(__file__).resolve().parent
BUTTON_DIR = SCRIPT_DIR / "buttons"
DEBUG_DIR = BUTTON_DIR / "debug"
LOG_DIR = SCRIPT_DIR / "logs"
SELECT_FILES_PREFIX = "select_files"
NEXT_PREFIX = "next"
PUBLISH_PREFIX = "publish"

# Every button the script can learn.  Used by --capture / --test-detect.
BUTTON_PREFIXES = {
    "select_files": SELECT_FILES_PREFIX,
    "next": NEXT_PREFIX,
    "publish": PUBLISH_PREFIX,
}

# Friendly names for the capture overlay and the log lines.
BUTTON_LABELS = {
    SELECT_FILES_PREFIX: "Select files",
    NEXT_PREFIX: "Next",
    PUBLISH_PREFIX: "Publish",
}

# Template matching is done on a downscaled copy of the screen for speed.
MATCH_MAX_WIDTH = 1280

pyautogui.PAUSE = 0.15
pyautogui.FAILSAFE = True


# --------------------------------------------------------------------------
# logging / small helpers
# --------------------------------------------------------------------------


class _Tee:
    """Mirror a stream to the console and the log file, line by line."""

    def __init__(self, stream, handle):
        self._stream = stream
        self._handle = handle

    def write(self, text):
        if self._stream is not None:
            try:
                self._stream.write(text)
                self._stream.flush()
            except Exception:
                pass
        if self._handle is not None:
            try:
                self._handle.write(text)
                self._handle.flush()
            except Exception:
                pass
        return len(text)

    def flush(self):
        for target in (self._stream, self._handle):
            if target is not None:
                try:
                    target.flush()
                except Exception:
                    pass

    def isatty(self):
        return bool(self._stream) and getattr(self._stream, "isatty", lambda: False)()

    def fileno(self):
        if self._stream is None:
            raise OSError("no fileno")
        return self._stream.fileno()


_log_handle = None
_log_path = None


def resolve_log_path():
    """--log-file wins, then UPLOAD_LOG_FILE, then ./logs/upload_<date>.log."""
    argv = sys.argv[1:]
    for index, value in enumerate(argv):
        if value == "--no-log-file":
            return None
        if value == "--log-file" and index + 1 < len(argv):
            return Path(argv[index + 1]).expanduser()
        if value.startswith("--log-file="):
            return Path(value.split("=", 1)[1]).expanduser()

    env_path = os.environ.get("UPLOAD_LOG_FILE", "").strip()
    if env_path:
        return Path(env_path).expanduser()

    return LOG_DIR / f"upload_{datetime.now().strftime('%Y-%m-%d')}.log"


def start_logging():
    """Tee stdout and stderr into the log file. Safe to call once."""
    global _log_handle, _log_path

    if _log_handle is not None:
        return _log_path

    path = resolve_log_path()
    if path is None:
        return None

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _log_handle = open(path, "a", encoding="utf-8", errors="replace", buffering=1)
        _log_path = path
    except Exception as error:  # logging must never take the script down
        print(f"WARNING: could not open log file {path}: {error}", flush=True)
        return None

    sys.stdout = _Tee(sys.__stdout__, _log_handle)
    sys.stderr = _Tee(sys.__stderr__, _log_handle)

    _log_handle.write("\n" + "=" * 78 + "\n")
    _log_handle.write(f"RUN STARTED {datetime.now().isoformat(timespec='seconds')}\n")
    _log_handle.write("=" * 78 + "\n")
    _log_handle.flush()

    # Catches segfaults / native crashes that never reach Python's except blocks.
    try:
        faulthandler.enable(file=_log_handle, all_threads=True)
    except Exception as error:
        print(f"WARNING: faulthandler unavailable: {error}", flush=True)

    return path


def stop_logging(exit_code):
    global _log_handle
    if _log_handle is None:
        return
    try:
        _log_handle.write(
            f"RUN ENDED {datetime.now().isoformat(timespec='seconds')} "
            f"exit={exit_code}\n"
        )
        _log_handle.flush()
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        _log_handle.close()
    except Exception:
        pass
    finally:
        _log_handle = None


def log(message):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def log_exception(prefix, error):
    """Log the message plus the whole traceback, every frame."""
    log(f"{prefix}: {type(error).__name__}: {error}")
    for line in traceback.format_exc().rstrip().splitlines():
        log(f"    {line}")


def log_environment(args=None):
    log(f"Log file: {_log_path if _log_path else '(disabled)'}")
    log(f"Command line: {' '.join(sys.argv)}")
    log(f"Working dir: {os.getcwd()}")
    log(f"Script dir: {SCRIPT_DIR}")
    log(f"Python: {sys.version.split()[0]} ({sys.executable})")
    log(f"OS: {platform.platform()}")
    log(f"pyautogui: {getattr(pyautogui, '__version__', 'unknown')}")
    log(f"opencv: {cv2.__version__ if cv2 is not None else 'NOT INSTALLED'}")
    log(f"numpy: {np.__version__ if np is not None else 'NOT INSTALLED'}")

    try:
        width, height = pyautogui.size()
        log(f"Screen (mouse coords): {width}x{height}")
    except Exception as error:
        log(f"Screen size unavailable: {error}")

    try:
        shot_w, shot_h = grab_screen().size
        log(f"Screen (screenshot px): {shot_w}x{shot_h}")
    except Exception as error:
        log(f"Screenshot unavailable: {error}")

    log(f"Button images in {BUTTON_DIR}:")
    for prefix in BUTTON_PREFIXES.values():
        paths = load_template_paths(prefix)
        label = BUTTON_LABELS.get(prefix, prefix)
        log(f"    {label}: {len(paths)}")
        for path in paths:
            log(f"        {path.name}")


def save_crash_screenshot(tag="crash"):
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        path = LOG_DIR / f"{tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        grab_screen().save(path)
        log(f"Saved screen at time of failure: {path}")
        return path
    except Exception as error:
        log(f"Could not save crash screenshot: {error}")
        return None


_screen_scale_cache = None


def grab_screen():
    """Full screenshot as an RGB PIL image (raw pixels, may be > logical size)."""
    return pyautogui.screenshot().convert("RGB")


def screen_scale():
    """Ratio between screenshot pixels and pyautogui click coordinates.

    On Windows with display scaling (125% / 150% / 4K) the screenshot is
    bigger than the coordinate space the mouse uses. Everything found in a
    screenshot must be divided by this before clicking.
    """
    global _screen_scale_cache
    if _screen_scale_cache is None:
        shot_w, shot_h = grab_screen().size
        click_w, click_h = pyautogui.size()
        _screen_scale_cache = (shot_w / click_w, shot_h / click_h)
        if abs(_screen_scale_cache[0] - 1.0) > 0.01:
            log(
                "Display scaling detected: screenshot is "
                f"{_screen_scale_cache[0]:.2f}x the mouse coordinate space"
            )
    return _screen_scale_cache


def to_click_coords(x, y):
    """Convert screenshot pixel coordinates to mouse coordinates."""
    scale_x, scale_y = screen_scale()
    return int(round(x / scale_x)), int(round(y / scale_y))


def ensure_dirs():
    BUTTON_DIR.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# arguments
# --------------------------------------------------------------------------


def parse_args():
    parser = argparse.ArgumentParser(
        description="Click YouTube Studio's Select files button and upload a video."
    )
    parser.add_argument(
        "source",
        nargs="*",
        help=(
            "Video file or folder to pick from. If omitted, UPLOAD_VIDEO_SOURCE "
            "then the built-in DEFAULT_VIDEO_SOURCES list are tried in order."
        ),
    )

    # --- button-image (template) options -------------------------------
    parser.add_argument(
        "--capture",
        metavar="NAME",
        choices=sorted(BUTTON_PREFIXES),
        default=None,
        help=(
            "Capture a reference image for NAME (%(choices)s), then exit. "
            "Drag a tight box around the button on the frozen screenshot."
        ),
    )
    parser.add_argument(
        "--capture-button",
        action="store_true",
        help="Shorthand for --capture select_files.",
    )
    parser.add_argument(
        "--capture-next",
        action="store_true",
        help="Shorthand for --capture next.",
    )
    parser.add_argument(
        "--capture-publish",
        action="store_true",
        help="Shorthand for --capture publish.",
    )
    parser.add_argument(
        "--capture-delay",
        type=float,
        default=3.0,
        help="Seconds before the capture screenshot is frozen.",
    )
    parser.add_argument(
        "--capture-at-mouse",
        action="store_true",
        help="Capture a fixed box centred on the mouse instead of drag-select.",
    )
    parser.add_argument(
        "--capture-size",
        default="260x90",
        help="Box size for --capture-at-mouse, e.g. 260x90.",
    )
    parser.add_argument(
        "--list-buttons",
        action="store_true",
        help="List the saved button reference images and exit.",
    )
    parser.add_argument(
        "--test-detect",
        metavar="NAME",
        nargs="?",
        const="select_files",
        choices=sorted(BUTTON_PREFIXES),
        default=None,
        help=(
            "Try to find NAME once (%(choices)s, default select_files), "
            "save a debug image, exit. Does not click."
        ),
    )
    parser.add_argument(
        "--button-confidence",
        type=float,
        default=float(os.environ.get("UPLOAD_BUTTON_CONFIDENCE", "0.80")),
        help="Match score (0-1) required to accept a template hit.",
    )
    parser.add_argument(
        "--next-confidence",
        type=float,
        default=(
            float(os.environ["UPLOAD_NEXT_CONFIDENCE"])
            if os.environ.get("UPLOAD_NEXT_CONFIDENCE")
            else None
        ),
        help=(
            "Match score for the Next/Publish images. Defaults to "
            "--button-confidence. Next sits on a busy toolbar, so it often "
            "wants a lower value (e.g. 0.72)."
        ),
    )
    parser.add_argument(
        "--publish-confidence",
        type=float,
        default=(
            float(os.environ["UPLOAD_PUBLISH_CONFIDENCE"])
            if os.environ.get("UPLOAD_PUBLISH_CONFIDENCE")
            else None
        ),
        help=(
            "Match score for the Publish images. Falls back to "
            "--next-confidence, then --button-confidence. Publish is a solid "
            "filled button, so it usually scores higher than Next."
        ),
    )
    parser.add_argument(
        "--strict-publish",
        action="store_true",
        help=(
            "Only click Publish on a real publish_*.png match: no reusing the "
            "Next images, no blind bottom-right click. Publishing is public "
            "and cannot be undone, so this stops instead of guessing."
        ),
    )
    parser.add_argument(
        "--scale-min",
        type=float,
        default=0.70,
        help="Smallest template scale tried during a full sweep.",
    )
    parser.add_argument(
        "--scale-max",
        type=float,
        default=1.35,
        help="Largest template scale tried during a full sweep.",
    )
    parser.add_argument(
        "--scale-steps",
        type=int,
        default=14,
        help="Number of scales tried during a full sweep.",
    )
    parser.add_argument(
        "--rescan-every",
        type=int,
        default=4,
        help="Do a slow multi-scale sweep every N polls (1 = always).",
    )
    parser.add_argument(
        "--no-templates",
        action="store_true",
        help="Ignore saved images and use the old colour detection only.",
    )
    parser.add_argument(
        "--debug-shots",
        action="store_true",
        help="Save an annotated screenshot every time the button is found/lost.",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Where to append the run log. Default ./logs/upload_<date>.log",
    )
    parser.add_argument(
        "--no-log-file",
        action="store_true",
        help="Console output only, do not write a log file.",
    )
    parser.add_argument(
        "--no-clipboard",
        action="store_true",
        help="Type the file path key by key instead of using the clipboard.",
    )
    parser.add_argument(
        "--stall-dump",
        type=float,
        default=0.0,
        help="If > 0, dump all thread stacks to the log every N seconds (hang debugging).",
    )

    # --- timing options (unchanged) ------------------------------------
    parser.add_argument(
        "--wait-button",
        type=float,
        default=float(os.environ.get("UPLOAD_WAIT_BUTTON", "90")),
        help="Seconds to wait for the Select files button.",
    )
    parser.add_argument(
        "--wait-dialog",
        type=float,
        default=float(os.environ.get("UPLOAD_WAIT_DIALOG", "30")),
        help="Seconds to wait for the Windows file picker.",
    )
    parser.add_argument(
        "--folder-wait",
        type=float,
        default=float(os.environ.get("UPLOAD_FOLDER_WAIT", "1.5")),
        help="Seconds to wait after opening the video folder in the picker.",
    )
    parser.add_argument(
        "--wait-details",
        type=float,
        default=float(os.environ.get("UPLOAD_WAIT_DETAILS", "90")),
        help="Seconds to wait for YouTube's details screen after selecting a file.",
    )
    parser.add_argument(
        "--details-settle",
        type=float,
        default=float(os.environ.get("UPLOAD_DETAILS_SETTLE", "5")),
        help="Extra seconds to let the details form finish drawing before typing.",
    )
    parser.add_argument(
        "--wait-next",
        type=float,
        default=float(os.environ.get("UPLOAD_WAIT_NEXT", "30")),
        help="Seconds to wait for the Next button.",
    )
    parser.add_argument(
        "--next-clicks",
        type=int,
        default=int(os.environ.get("UPLOAD_NEXT_CLICKS", "3")),
        help="How many times to click Next as a fail-safe.",
    )
    parser.add_argument(
        "--next-delay-min",
        type=float,
        default=float(os.environ.get("UPLOAD_NEXT_DELAY_MIN", "4")),
        help="Minimum random delay between Next clicks.",
    )
    parser.add_argument(
        "--next-delay-max",
        type=float,
        default=float(os.environ.get("UPLOAD_NEXT_DELAY_MAX", "7")),
        help="Maximum random delay between Next clicks.",
    )
    parser.add_argument(
        "--wait-publish",
        type=float,
        default=float(os.environ.get("UPLOAD_WAIT_PUBLISH", "120")),
        help="Seconds to wait for the Publish button.",
    )
    parser.add_argument(
        "--publish-click-delay",
        type=float,
        default=float(os.environ.get("UPLOAD_PUBLISH_CLICK_DELAY", "3")),
        help="Seconds to wait after finding Publish before clicking it.",
    )

    args = parser.parse_args()
    # A quoted Windows path can arrive split across argv entries; rejoin it.
    args.source = " ".join(args.source).strip() if args.source else None
    return args


def confidence_for(args, prefix):
    """Each button can carry its own threshold, falling back to the general one.

        publish -> --publish-confidence -> --next-confidence -> --button-confidence
        next    -> --next-confidence                           -> --button-confidence
        others  ->                                              --button-confidence
    """
    if prefix == PUBLISH_PREFIX:
        for value in (args.publish_confidence, args.next_confidence):
            if value is not None:
                return value
    elif prefix == NEXT_PREFIX:
        if args.next_confidence is not None:
            return args.next_confidence
    return args.button_confidence


def build_scales(args):
    if args.scale_steps <= 1:
        return [1.0]
    step = (args.scale_max - args.scale_min) / (args.scale_steps - 1)
    scales = [args.scale_min + step * i for i in range(args.scale_steps)]
    if not any(abs(s - 1.0) < 1e-6 for s in scales):
        scales.append(1.0)
    # Try scales closest to 1.0 first so the common case exits early.
    return sorted(scales, key=lambda s: abs(s - 1.0))


# --------------------------------------------------------------------------
# capturing button reference images
# --------------------------------------------------------------------------


def next_template_path(prefix):
    ensure_dirs()
    index = 1
    while True:
        candidate = BUTTON_DIR / f"{prefix}_{index:02d}.png"
        if not candidate.exists():
            return candidate
        index += 1


def select_region_with_overlay(image, label="Select files"):
    """Show the frozen screenshot fullscreen and let the user drag a box.

    Returns (left, top, right, bottom) in image pixels, or None if cancelled.
    """
    import tkinter as tk

    from PIL import ImageTk

    root = tk.Tk()
    root.title(f"Drag a box around the {label} button - Esc to cancel")
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)

    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()

    display_image = image
    if image.size != (screen_w, screen_h):
        display_image = image.resize((screen_w, screen_h), Image.LANCZOS)

    photo = ImageTk.PhotoImage(display_image)
    canvas = tk.Canvas(root, cursor="cross", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    canvas.create_image(0, 0, anchor="nw", image=photo)
    canvas.create_text(
        screen_w // 2,
        30,
        text=f"Drag a tight box around the {label} button  (Esc = cancel)",
        fill="#ff2d55",
        font=("Segoe UI", 18, "bold"),
    )

    state = {"start": None, "end": None, "rect": None, "cancelled": False}

    def on_press(event):
        state["start"] = (event.x, event.y)
        if state["rect"] is not None:
            canvas.delete(state["rect"])
        state["rect"] = canvas.create_rectangle(
            event.x, event.y, event.x, event.y, outline="#ff2d55", width=2
        )

    def on_drag(event):
        if state["start"] is None:
            return
        canvas.coords(
            state["rect"], state["start"][0], state["start"][1], event.x, event.y
        )

    def on_release(event):
        if state["start"] is None:
            return
        state["end"] = (event.x, event.y)
        root.destroy()

    def on_cancel(_event=None):
        state["cancelled"] = True
        root.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", on_cancel)
    root.mainloop()

    if state["cancelled"] or not state["start"] or not state["end"]:
        return None

    scale_x = image.width / screen_w
    scale_y = image.height / screen_h
    x1, y1 = state["start"]
    x2, y2 = state["end"]
    left = int(min(x1, x2) * scale_x)
    right = int(max(x1, x2) * scale_x)
    top = int(min(y1, y2) * scale_y)
    bottom = int(max(y1, y2) * scale_y)
    if right - left < 8 or bottom - top < 6:
        return None
    return left, top, right, bottom


def region_around_mouse(image, size_text):
    try:
        width_text, height_text = size_text.lower().split("x")
        box_w, box_h = int(width_text), int(height_text)
    except Exception:
        box_w, box_h = 260, 90

    scale_x, scale_y = screen_scale()
    mouse_x, mouse_y = pyautogui.position()
    center_x = mouse_x * scale_x
    center_y = mouse_y * scale_y
    half_w = box_w * scale_x / 2
    half_h = box_h * scale_y / 2

    left = int(max(0, center_x - half_w))
    top = int(max(0, center_y - half_h))
    right = int(min(image.width, center_x + half_w))
    bottom = int(min(image.height, center_y + half_h))
    return left, top, right, bottom


def capture_button(args, prefix=SELECT_FILES_PREFIX):
    ensure_dirs()
    label = BUTTON_LABELS.get(prefix, prefix)
    log(f"Capture [{label}]: freezing the screen in {args.capture_delay:.1f}s ...")
    if args.capture_at_mouse:
        log(f"Capture [{label}]: hover the mouse over the CENTRE of the {label} button now")
    time.sleep(args.capture_delay)

    shot = grab_screen()

    if args.capture_at_mouse:
        box = region_around_mouse(shot, args.capture_size)
    else:
        try:
            box = select_region_with_overlay(shot, label)
        except Exception as error:
            log(f"Capture [{label}]: overlay unavailable ({error}); using mouse box")
            log(f"Capture [{label}]: hover over the button; grabbing in 4s")
            time.sleep(4)
            shot = grab_screen()
            box = region_around_mouse(shot, args.capture_size)

    if not box:
        log(f"Capture [{label}]: cancelled, nothing saved")
        return 1

    crop = shot.crop(box)
    target = next_template_path(prefix)
    crop.save(target)
    log(f"Capture [{label}]: saved {target.name} ({crop.width}x{crop.height} px)")
    log(f"Capture [{label}]: run --capture {prefix} again for a hover-state variant")
    log(f"Capture [{label}]: verify with  --test-detect {prefix}")
    return 0


def list_templates():
    ensure_dirs()
    script = Path(sys.argv[0]).name
    total = 0

    log(f"Button images in {BUTTON_DIR}:")
    for prefix in BUTTON_PREFIXES.values():
        label = BUTTON_LABELS.get(prefix, prefix)
        paths = load_template_paths(prefix)
        if not paths:
            log(f"  {label}: none yet  ->  python {script} --capture {prefix}")
            continue
        log(f"  {label}: {len(paths)} image(s)")
        for path in paths:
            with Image.open(path) as image:
                log(f"      {path.name}  {image.width}x{image.height}")
        total += len(paths)

    if total == 0:
        log(f"Nothing captured yet. Start with: python {script} --capture-button")
        return 1
    return 0


# --------------------------------------------------------------------------
# template matching
# --------------------------------------------------------------------------


def load_template_paths(prefix=SELECT_FILES_PREFIX):
    if not BUTTON_DIR.is_dir():
        return []
    # The trailing underscore keeps "next_01.png" from also matching a
    # future "next_step_01.png" - and keeps prefixes from bleeding together.
    return sorted(
        path
        for path in BUTTON_DIR.iterdir()
        if path.is_file()
        and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp"}
        and path.stem.startswith(f"{prefix}_")
    )


def load_templates(prefix=SELECT_FILES_PREFIX):
    templates = []
    for path in load_template_paths(prefix):
        try:
            with Image.open(path) as image:
                templates.append((path.name, image.convert("RGB").copy()))
        except Exception as error:
            log(f"Templates: could not read {path.name}: {error}")
    return templates


def proc_scale_for(width):
    if width <= MATCH_MAX_WIDTH:
        return 1.0
    return MATCH_MAX_WIDTH / float(width)


def to_gray_array(image, scale):
    array = np.array(image.convert("L"))
    if scale != 1.0:
        height, width = array.shape
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        array = cv2.resize(array, new_size, interpolation=cv2.INTER_AREA)
    return array


def match_one_template(screen_gray, template_gray, scales, use_edges):
    """Return (best_score, (center_x, center_y), (w, h)) in processed pixels."""
    screen_image = cv2.Canny(screen_gray, 60, 160) if use_edges else screen_gray
    screen_h, screen_w = screen_gray.shape

    best_score = -1.0
    best_center = None
    best_size = None

    for scale in scales:
        width = int(round(template_gray.shape[1] * scale))
        height = int(round(template_gray.shape[0] * scale))
        if width < 10 or height < 8 or width > screen_w or height > screen_h:
            continue

        interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
        resized = cv2.resize(template_gray, (width, height), interpolation=interpolation)
        if use_edges:
            resized = cv2.Canny(resized, 60, 160)

        result = cv2.matchTemplate(screen_image, resized, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val > best_score:
            best_score = float(max_val)
            best_center = (max_loc[0] + width / 2.0, max_loc[1] + height / 2.0)
            best_size = (width, height)

    return best_score, best_center, best_size


def find_button_by_template(templates, scales, confidence, want_debug=False):
    """Returns dict with click coords + score, or a dict with score only on miss."""
    if not templates or cv2 is None or np is None:
        return None

    shot = grab_screen()
    scale = proc_scale_for(shot.width)
    screen_gray = to_gray_array(shot, scale)

    best = {"score": -1.0, "name": None, "center": None, "size": None, "mode": "gray"}

    for name, template_image in templates:
        template_gray = to_gray_array(template_image, scale)
        score, center, size = match_one_template(
            screen_gray, template_gray, scales, use_edges=False
        )
        if score > best["score"]:
            best = {
                "score": score,
                "name": name,
                "center": center,
                "size": size,
                "mode": "gray",
            }

    # Edge fallback: survives theme / brightness / anti-aliasing differences.
    if best["score"] < confidence:
        edge_threshold = max(0.45, confidence * 0.72)
        for name, template_image in templates:
            template_gray = to_gray_array(template_image, scale)
            score, center, size = match_one_template(
                screen_gray, template_gray, scales, use_edges=True
            )
            if score >= edge_threshold and score > best["score"]:
                best = {
                    "score": score,
                    "name": name,
                    "center": center,
                    "size": size,
                    "mode": "edges",
                }
        accepted = best["center"] is not None and best["score"] >= edge_threshold and best["mode"] == "edges"
    else:
        accepted = True

    if best["center"] is None:
        return {"found": False, "score": best["score"], "name": best["name"]}

    shot_x = best["center"][0] / scale
    shot_y = best["center"][1] / scale
    click_x, click_y = to_click_coords(shot_x, shot_y)

    result = {
        "found": bool(accepted),
        "score": best["score"],
        "name": best["name"],
        "mode": best["mode"],
        "click": (click_x, click_y),
        "shot_box": (
            int(shot_x - best["size"][0] / scale / 2),
            int(shot_y - best["size"][1] / scale / 2),
            int(shot_x + best["size"][0] / scale / 2),
            int(shot_y + best["size"][1] / scale / 2),
        ),
    }

    if want_debug:
        result["debug_path"] = save_debug_shot(shot, result)

    return result


def save_debug_shot(shot, result):
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    annotated = shot.copy()
    draw = ImageDraw.Draw(annotated)
    box = result.get("shot_box")
    if box:
        colour = (0, 220, 0) if result.get("found") else (255, 40, 40)
        draw.rectangle(box, outline=colour, width=4)
        draw.text(
            (box[0], max(0, box[1] - 18)),
            f"{result.get('name')} {result.get('score', 0):.3f} ({result.get('mode')})",
            fill=colour,
        )
    path = DEBUG_DIR / f"detect_{datetime.now().strftime('%H%M%S')}.png"
    annotated.save(path)
    return path


def locate_on_screen_fallback(paths):
    """Exact-pixel match via pyautogui, used when OpenCV is missing."""
    for path in paths:
        try:
            box = pyautogui.locateOnScreen(str(path))
        except Exception:
            box = None
        if box:
            center = pyautogui.center(box)
            return int(center.x), int(center.y), path.name
    return None


# --------------------------------------------------------------------------
# legacy colour detection (fallback only)
# --------------------------------------------------------------------------


def near_white(pixel):
    r, g, b = pixel
    return r >= 235 and g >= 235 and b >= 235 and max(pixel) - min(pixel) <= 25


def is_youtube_blue(pixel):
    r, g, b = pixel
    return b >= 145 and g >= 85 and r <= 90 and b - r >= 70


def find_button_by_color(matches_color, prefer="center"):
    screenshot = grab_screen()
    screen_width, screen_height = screenshot.size
    scale = 0.5 if screen_width > 1400 else 1.0

    if scale != 1.0:
        image = screenshot.resize(
            (int(screen_width * scale), int(screen_height * scale))
        )
    else:
        image = screenshot

    width, height = image.size
    pixels = image.load()
    visited = bytearray(width * height)
    candidates = []

    if prefer == "bottom_right":
        x_min = int(width * 0.45)
        x_max = int(width * 0.99)
        y_min = int(height * 0.70)
        y_max = int(height * 0.99)
    else:
        x_min = int(width * 0.05)
        x_max = int(width * 0.95)
        y_min = int(height * 0.08)
        y_max = int(height * 0.92)

    for start_y in range(y_min, y_max):
        for start_x in range(x_min, x_max):
            start_index = start_y * width + start_x
            if visited[start_index] or not matches_color(pixels[start_x, start_y]):
                continue

            stack = [(start_x, start_y)]
            visited[start_index] = 1
            area = 0
            min_x = max_x = start_x
            min_y = max_y = start_y

            while stack:
                x, y = stack.pop()
                area += 1
                min_x = min(min_x, x)
                max_x = max(max_x, x)
                min_y = min(min_y, y)
                max_y = max(max_y, y)

                for next_x, next_y in (
                    (x + 1, y),
                    (x - 1, y),
                    (x, y + 1),
                    (x, y - 1),
                ):
                    if not (x_min <= next_x < x_max and y_min <= next_y < y_max):
                        continue
                    index = next_y * width + next_x
                    if visited[index] or not matches_color(pixels[next_x, next_y]):
                        continue
                    visited[index] = 1
                    stack.append((next_x, next_y))

            box_width = (max_x - min_x + 1) / scale
            box_height = (max_y - min_y + 1) / scale
            if box_height == 0:
                continue

            aspect = box_width / box_height
            fill_ratio = area / ((max_x - min_x + 1) * (max_y - min_y + 1))
            if (
                45 <= box_width <= 230
                and 24 <= box_height <= 70
                and 1.6 <= aspect <= 5.5
                and fill_ratio >= 0.45
            ):
                center_x = ((min_x + max_x) / 2) / scale
                center_y = ((min_y + max_y) / 2) / scale
                if prefer == "bottom_right":
                    score = (
                        abs(center_x - screen_width * 0.94) * 0.8
                        + abs(center_y - screen_height * 0.96)
                    )
                else:
                    center_score = abs(center_x - screen_width / 2)
                    lower_middle_score = abs(center_y - screen_height * 0.62) * 0.4
                    score = center_score + lower_middle_score
                candidates.append((score, center_x, center_y))

    if not candidates:
        return None

    _, button_x, button_y = min(candidates, key=lambda item: item[0])
    return to_click_coords(button_x, button_y)


def find_bright_button():
    return find_button_by_color(near_white, prefer="center")


def find_blue_next_button():
    return find_button_by_color(is_youtube_blue, prefer="bottom_right")


def find_white_next_button():
    return find_button_by_color(near_white, prefer="bottom_right")


def find_next_button():
    return find_white_next_button() or find_blue_next_button()


# --------------------------------------------------------------------------
# waiting
# --------------------------------------------------------------------------


def wait_for_result(description, timeout_seconds, check, interval_seconds=0.5):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(interval_seconds)
    raise TimeoutError(f"Timed out waiting for {description}.")


def wait_for_template_button(
    args, prefix, timeout_seconds, confidence, colour_fallback=None
):
    """Find a saved button image on screen. Returns (x, y) or raises TimeoutError.

    Templates first; the old colour heuristic is only a last resort.
    """
    label = BUTTON_LABELS.get(prefix, prefix)
    templates = [] if args.no_templates else load_templates(prefix)
    template_paths = [] if args.no_templates else load_template_paths(prefix)
    scales = build_scales(args)

    if args.no_templates:
        log(f"{label}: template matching disabled (--no-templates)")
    elif not templates:
        log(f"{label}: no reference images found in ./buttons")
        log(f"{label}: run --capture {prefix} once to teach it the button")
    elif cv2 is None or np is None:
        log(f"{label}: opencv-python/numpy missing -> exact-pixel fallback")
        log(f"{label}: install with  pip install opencv-python numpy")
    else:
        log(f"{label}: using {len(templates)} reference image(s), "
            f"confidence >= {confidence:.2f}")

    deadline = time.monotonic() + timeout_seconds
    attempt = 0
    best_seen = -1.0

    while time.monotonic() < deadline:
        attempt += 1
        full_sweep = (attempt % max(1, args.rescan_every) == 1) or attempt == 1

        if templates and cv2 is not None and np is not None:
            result = find_button_by_template(
                templates,
                scales if full_sweep else [1.0],
                confidence,
            )
            if result:
                best_seen = max(best_seen, result["score"])
                if result["found"]:
                    log(
                        f"{label}: matched {result['name']} "
                        f"score={result['score']:.3f} mode={result['mode']} "
                        f"at {result['click']}"
                    )
                    if args.debug_shots:
                        path = save_debug_shot(grab_screen(), result)
                        log(f"{label}: debug image {path}")
                    return result["click"]
                if attempt % 8 == 0:
                    log(
                        f"{label}: still searching, best score so far "
                        f"{best_seen:.3f} (need {confidence:.2f})"
                    )
        elif template_paths:
            hit = locate_on_screen_fallback(template_paths)
            if hit:
                x, y, name = hit
                log(f"{label}: exact-pixel match on {name} at ({x}, {y})")
                return x, y

        time.sleep(0.6)

    if colour_fallback is not None:
        log(f"{label}: templates did not match in time, trying colour detection")
        colour_hit = colour_fallback()
        if colour_hit:
            log(f"{label}: colour fallback found a button at {colour_hit}")
            return colour_hit

    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        path = DEBUG_DIR / f"miss_{prefix}_{datetime.now().strftime('%H%M%S')}.png"
        grab_screen().save(path)
        log(f"{label}: saved the screen it could not match to {path}")
    except Exception as error:
        log(f"{label}: could not save the miss screenshot: {error}")

    raise TimeoutError(
        f"Timed out waiting for the {label} button. Capture a fresh reference "
        f"image with --capture {prefix}, or lower the match threshold "
        f"(currently {confidence:.2f})."
    )


def wait_for_select_files_button(args):
    return wait_for_template_button(
        args,
        SELECT_FILES_PREFIX,
        args.wait_button,
        confidence_for(args, SELECT_FILES_PREFIX),
        colour_fallback=find_bright_button,
    )


def wait_for_next_button(args, timeout_seconds):
    return wait_for_template_button(
        args,
        NEXT_PREFIX,
        timeout_seconds,
        confidence_for(args, NEXT_PREFIX),
        colour_fallback=find_next_button,
    )


def wait_for_publish_button(args, timeout_seconds):
    """Find Publish. The fussiest of the three, because the click is public.

    With publish_*.png saved it matches those. Without them it reuses the Next
    images, which is only a guess: Next and Publish occupy the same corner, so
    a wizard that stalled on an earlier step hands back the Next button and the
    run clicks the wrong thing. --strict-publish refuses that guess.
    """
    if load_template_paths(PUBLISH_PREFIX):
        return wait_for_template_button(
            args,
            PUBLISH_PREFIX,
            timeout_seconds,
            confidence_for(args, PUBLISH_PREFIX),
            # The colour blob finder cannot tell Next from Publish either.
            colour_fallback=None if args.strict_publish else find_next_button,
        )

    if args.strict_publish:
        raise TimeoutError(
            "No publish_*.png saved and --strict-publish is on. "
            "Capture the button first:  --capture-publish"
        )

    log("Publish: no publish_*.png saved, reusing the Next images (a guess)")
    log("Publish: capture the real button with  --capture-publish")
    return wait_for_next_button(args, timeout_seconds)


def active_file_dialog():
    try:
        window = pyautogui.getActiveWindow()
    except Exception:
        return None

    if not window:
        return None

    title = (window.title or "").lower()
    if "open" in title or "choose file" in title or "file upload" in title:
        return window
    return None


def wait_for_file_dialog(timeout_seconds):
    return wait_for_result(
        "the Windows file picker",
        timeout_seconds,
        active_file_dialog,
        interval_seconds=0.25,
    )


def wait_for_details_screen(timeout_seconds):
    def details_ready():
        if active_file_dialog():
            return None
        return True

    return wait_for_result(
        "YouTube's details screen",
        timeout_seconds,
        details_ready,
        interval_seconds=0.5,
    )


# --------------------------------------------------------------------------
# the upload flow
# --------------------------------------------------------------------------


def candidate_sources(source):
    """Explicit path wins outright; otherwise env var, then the built-in list."""
    if source:
        return [source], True

    candidates = []
    env_source = os.environ.get("UPLOAD_VIDEO_SOURCE", "").strip()
    if env_source:
        candidates.append(env_source)
    candidates.extend(DEFAULT_VIDEO_SOURCES)
    return candidates, False


def newest_video_in(folder):
    videos = [
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    ]
    if not videos:
        return None
    # Newest file, so dropping a fresh export into the folder just works.
    return max(videos, key=lambda path: path.stat().st_mtime).resolve()


def choose_video(source):
    candidates, explicit = candidate_sources(source)
    tried = []

    for candidate in candidates:
        source_path = Path(candidate).expanduser()
        tried.append(str(source_path))

        if source_path.is_file():
            if source_path.suffix.lower() not in VIDEO_EXTENSIONS:
                raise ValueError(f"Not a supported video file: {source_path}")
            return source_path.resolve()

        if not source_path.is_dir():
            if explicit:
                raise FileNotFoundError(f"Video source does not exist: {source_path}")
            log(f"Source: {source_path} not found, trying next")
            continue

        video = newest_video_in(source_path)
        if video:
            log(f"Source: using folder {source_path}")
            return video

        if explicit:
            raise FileNotFoundError(f"No supported video files found in: {source_path}")
        log(f"Source: {source_path} has no videos, trying next")

    raise FileNotFoundError(
        "No usable video source. Tried: "
        + " | ".join(tried)
        + "  -- pass a path as an argument, set UPLOAD_VIDEO_SOURCE, or edit "
        "DEFAULT_VIDEO_SOURCES at the top of this file."
    )


CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def _win32_handles():
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE

    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL

    return ctypes, user32, kernel32


def _open_clipboard(user32, attempts=12, delay=0.15):
    """Another process can hold the clipboard; retry rather than fail."""
    for attempt in range(attempts):
        if user32.OpenClipboard(None):
            return True
        time.sleep(delay)
    return False


def set_clipboard_win32(text):
    ctypes, user32, kernel32 = _win32_handles()

    buffer = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(buffer)

    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
    if not handle:
        raise OSError("GlobalAlloc failed")

    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        kernel32.GlobalFree(handle)
        raise OSError("GlobalLock failed")

    ctypes.memmove(pointer, buffer, size)
    kernel32.GlobalUnlock(handle)

    if not _open_clipboard(user32):
        kernel32.GlobalFree(handle)
        raise OSError("OpenClipboard failed (another app is holding it)")

    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            raise OSError("SetClipboardData failed")
        # On success Windows owns the memory - do not free it.
    finally:
        user32.CloseClipboard()


def get_clipboard_win32():
    ctypes, user32, kernel32 = _win32_handles()

    if not _open_clipboard(user32):
        return None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return None
        try:
            return ctypes.c_wchar_p(pointer).value
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def set_clipboard(text):
    """Win32 first, then pyperclip, then clip.exe. Never tkinter.

    tkinter is deliberately avoided here: creating a Tk root while a modal
    Windows file dialog holds the foreground can kill the interpreter
    outright, and Tk drops the clipboard contents when the root is destroyed.
    """
    if os.name == "nt":
        try:
            set_clipboard_win32(text)
            readback = get_clipboard_win32()
            if readback == text:
                log("Clipboard: set via Win32 and verified")
                return True
            log(f"Clipboard: Win32 readback mismatch (got {readback!r})")
        except Exception as error:
            log(f"Clipboard: Win32 method failed: {error}")

    try:
        import pyperclip

        pyperclip.copy(text)
        if pyperclip.paste() == text:
            log("Clipboard: set via pyperclip and verified")
            return True
        log("Clipboard: pyperclip readback mismatch")
    except Exception as error:
        log(f"Clipboard: pyperclip unavailable/failed: {error}")

    if os.name == "nt":
        try:
            import subprocess

            subprocess.run(
                ["clip.exe"],
                input=text.encode("utf-16-le"),
                check=True,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            log("Clipboard: set via clip.exe (unverified)")
            return True
        except Exception as error:
            log(f"Clipboard: clip.exe failed: {error}")

    return False


def type_text(text):
    """Slow but dependency-free fallback."""
    log(f"Input: typing {len(text)} characters directly")
    pyautogui.write(text, interval=0.02)


def enter_text(text, prefer_clipboard=True):
    """Put text into the focused field, clearing whatever is there first."""
    pyautogui.hotkey("ctrl", "a")

    if prefer_clipboard and set_clipboard(text):
        pyautogui.hotkey("ctrl", "v")
        log("Input: pasted from clipboard")
        return

    type_text(text)


def dialog_closed_within(seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if active_file_dialog() is None:
            return True
        time.sleep(0.25)
    return False


def log_active_window(prefix):
    try:
        window = pyautogui.getActiveWindow()
        title = window.title if window else None
        log(f"{prefix}: active window = {title!r}")
    except Exception as error:
        log(f"{prefix}: could not read active window ({error})")

def focus_youtube_studio():
    """Find the YouTube Studio Chrome window and bring it to the foreground."""
    try:
        import pygetwindow as gw

        windows = gw.getWindowsWithTitle("YouTube Studio")

        if not windows:
            # Chrome title may be different depending on the current page
            windows = [
                w for w in gw.getAllWindows()
                if "youtube studio" in (w.title or "").lower()
            ]

        if not windows:
            log("Focus: YouTube Studio window not found")
            return False

        window = windows[0]

        if window.isMinimized:
            window.restore()
            time.sleep(0.5)

        window.activate()
        time.sleep(0.5)

        log(f"Focus: activated YouTube Studio -> {window.title!r}")
        return True

    except Exception as error:
        log(f"Focus: failed -> {error}")
        return False

def select_video_in_dialog(video_path, folder_wait, prefer_clipboard=True):
    """Type the full path into the filename box; fall back to folder-then-name."""
    log_active_window("File picker")

    log(f"File picker: entering full path {video_path}")
    pyautogui.hotkey("alt", "n")
    time.sleep(0.3)
    enter_text(str(video_path), prefer_clipboard)
    time.sleep(0.3)
    pyautogui.press("enter")
    log("File picker: pressed Enter on the full path")

    if dialog_closed_within(6):
        log("File picker: dialog closed, file accepted")
        return

    log("File picker: dialog still open, falling back to folder-then-filename")
    log_active_window("File picker")

    log(f"File picker: opening folder {video_path.parent}")
    pyautogui.hotkey("alt", "d")
    time.sleep(0.3)
    enter_text(str(video_path.parent), prefer_clipboard)
    pyautogui.press("enter")
    log(f"File picker: waiting {folder_wait:.1f}s for folder to load")
    time.sleep(folder_wait)

    log(f"File picker: entering filename {video_path.name}")
    pyautogui.hotkey("alt", "n")
    time.sleep(0.3)
    enter_text(video_path.name, prefer_clipboard)
    pyautogui.press("enter")
    log("File picker: pressed Enter/Open")

    if dialog_closed_within(6):
        log("File picker: dialog closed, file accepted")
    else:
        log("File picker: WARNING - dialog is still open after both attempts")
        save_crash_screenshot("filepicker_stuck")


def upload_window_bounds():
    try:
        window = pyautogui.getActiveWindow()
    except Exception:
        window = None

    if window and window.width and window.height:
        return window.left, window.top, window.width, window.height

    width, height = pyautogui.size()
    return 0, 0, width, height


def fallback_next_coordinates():
    left, top, width, height = upload_window_bounds()
    return left + int(width * 0.945), top + int(height * 0.965)


def click_next_fail_safe(args):
    clicks = args.next_clicks
    delay_min = args.next_delay_min
    delay_max = args.next_delay_max

    if clicks < 1:
        raise ValueError("--next-clicks must be at least 1.")
    if delay_min < 0 or delay_max < 0 or delay_min > delay_max:
        raise ValueError("Next delay values must be positive and min must be <= max.")

    for attempt in range(1, clicks + 1):
        log(f"Next attempt {attempt}/{clicks}: looking for the Next button")
        try:
            next_x, next_y = wait_for_next_button(args, args.wait_next)
            log(f"Next attempt {attempt}/{clicks}: found button at ({next_x}, {next_y})")
        except TimeoutError as error:
            next_x, next_y = fallback_next_coordinates()
            log(
                f"Next attempt {attempt}/{clicks}: {error} "
                f"Using bottom-right fallback at ({next_x}, {next_y})"
            )

        pyautogui.moveTo(next_x, next_y, duration=0.2)
        pyautogui.click(next_x, next_y)
        log(f"Next attempt {attempt}/{clicks}: clicked at ({next_x}, {next_y})")

        if attempt < clicks:
            delay = random.uniform(delay_min, delay_max)
            log(
                f"Next attempt {attempt}/{clicks}: waiting {delay:.2f}s "
                "before the next fail-safe click"
            )
            time.sleep(delay)


def click_publish(args):
    log("Publish: waiting for the Publish button")
    try:
        publish_x, publish_y = wait_for_publish_button(args, args.wait_publish)
        log(f"Publish: button found at ({publish_x}, {publish_y})")
    except TimeoutError as error:
        # Publishing is public and cannot be undone, so a blind click on a
        # guessed coordinate is a worse outcome than stopping the run.
        if args.strict_publish:
            log(f"Publish: {error}")
            log("Publish: --strict-publish is on, refusing to click a guess")
            raise
        publish_x, publish_y = fallback_next_coordinates()
        log(
            f"Publish: {error} "
            f"Using bottom-right fallback at ({publish_x}, {publish_y})"
        )

    log(f"Publish: waiting {args.publish_click_delay:.1f}s before clicking")
    time.sleep(args.publish_click_delay)
    pyautogui.moveTo(publish_x, publish_y, duration=0.2)
    pyautogui.click(publish_x, publish_y)
    log(f"Publish: clicked at ({publish_x}, {publish_y})")


def run_test_detect(args, prefix=SELECT_FILES_PREFIX):
    label = BUTTON_LABELS.get(prefix, prefix)
    confidence = confidence_for(args, prefix)

    templates = load_templates(prefix)
    if not templates:
        log(f"Test [{label}]: no reference images. Run --capture {prefix} first.")
        return 1
    if cv2 is None or np is None:
        log("Test: opencv-python and numpy are required. pip install opencv-python numpy")
        return 1

    log(f"Test [{label}]: matching {len(templates)} reference image(s) ...")
    started = time.monotonic()
    result = find_button_by_template(
        templates, build_scales(args), confidence, want_debug=True
    )
    elapsed = time.monotonic() - started

    if not result:
        log(f"Test [{label}]: no match at all")
        return 1

    log(
        f"Test [{label}]: best={result['name']} score={result['score']:.3f} "
        f"mode={result.get('mode')} in {elapsed:.2f}s"
    )
    if result.get("debug_path"):
        log(f"Test [{label}]: annotated screenshot -> {result['debug_path']}")
    if result["found"]:
        log(f"Test [{label}]: PASS - would click {result['click']}")
        return 0

    log(
        f"Test [{label}]: FAIL - score below {confidence:.2f}. "
        "Capture a tighter/cleaner crop, or lower the confidence."
    )
    return 1


def main():
    args = parse_args()
    focus_youtube_studio()
    log("=" * 60)
    log_environment(args)
    log("=" * 60)

    if args.stall_dump and args.stall_dump > 0 and _log_handle is not None:
        try:
            faulthandler.dump_traceback_later(
                args.stall_dump, repeat=True, exit=False, file=_log_handle
            )
            log(f"Stall watchdog: dumping stacks every {args.stall_dump:.0f}s")
        except Exception as error:
            log(f"Stall watchdog unavailable: {error}")

    if args.list_buttons:
        return list_templates()

    capture_target = args.capture
    if args.capture_button:
        capture_target = "select_files"
    if args.capture_next:
        capture_target = "next"
    if args.capture_publish:
        capture_target = "publish"
    if capture_target:
        return capture_button(args, BUTTON_PREFIXES[capture_target])

    if args.test_detect:
        return run_test_detect(args, BUTTON_PREFIXES[args.test_detect])

    log("Upload automation started")
    log(f"Source setting: {args.source or '(auto - searching known folders)'}")
    log(
        "Wait settings: "
        f"select={args.wait_button:.1f}s, dialog={args.wait_dialog:.1f}s, "
        f"folder={args.folder_wait:.1f}s, details={args.wait_details:.1f}s, "
        f"settle={args.details_settle:.1f}s, next={args.wait_next:.1f}s, "
        f"publish={args.wait_publish:.1f}s, "
        f"publish_click_delay={args.publish_click_delay:.1f}s"
    )
    log(
        "Next fail-safe: "
        f"{args.next_clicks} clicks with random {args.next_delay_min:.1f}-"
        f"{args.next_delay_max:.1f}s delays"
    )

    video_path = choose_video(args.source)
    log(f"Selected video: {video_path}")

    log("Waiting for the YouTube Studio Select files button")
    button_x, button_y = wait_for_select_files_button(args)
    log(f"Select files button at ({button_x}, {button_y}); clicking")
    pyautogui.moveTo(button_x, button_y, duration=0.2)
    pyautogui.click(button_x, button_y)

    log("Waiting for the Windows file picker")
    wait_for_file_dialog(args.wait_dialog)
    log("Windows file picker is active")
    select_video_in_dialog(
        video_path, args.folder_wait, prefer_clipboard=not args.no_clipboard
    )

    log("Waiting for YouTube's details screen")
    wait_for_details_screen(args.wait_details)
    log(f"Details screen is available; settling for {args.details_settle:.1f}s")
    time.sleep(args.details_settle)

    click_next_fail_safe(args)
    click_publish(args)
    
    # --- ADDED: Move the file to an "uploaded" directory ---
    log("Upload complete. Moving file to prevent re-uploading...")
    try:
        uploaded_dir = video_path.parent / "uploaded"
        uploaded_dir.mkdir(exist_ok=True)
        destination = uploaded_dir / video_path.name
        
        shutil.move(str(video_path), str(destination))
        log(f"Moved video to: {destination}")
    except Exception as e:
        log(f"Failed to move file after upload: {e}")
    # --------------------------------------------------------

    log("Upload automation finished")
    return 0


def _run():
    # Start logging before anything else so even argparse errors are captured.
    start_logging()

    try:
        return main() or 0
    except KeyboardInterrupt:
        log("Interrupted by user (Ctrl+C)")
        return 130
    except SystemExit as error:  # argparse --help / bad flags
        code = error.code if isinstance(error.code, int) else 0
        log(f"Exiting with code {code}")
        return code
    except Exception as error:
        log_exception("CRASH", error)
        log_environment()
        save_crash_screenshot("crash")
        return 1


if __name__ == "__main__":
    exit_code = 1
    try:
        exit_code = _run()
    finally:
        log(f"Exit code: {exit_code}")
        stop_logging(exit_code)
    sys.exit(exit_code)