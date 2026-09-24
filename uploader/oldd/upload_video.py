import argparse
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import pyautogui


DEFAULT_VIDEO_SOURCE = r"D:\testvideos"
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

pyautogui.PAUSE = 0.15


def log(message):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Click YouTube Studio's Select files button and choose a video."
    )
    parser.add_argument(
        "source",
        nargs="*",
        help="Video file or folder to pick from. Defaults to D:\\testvideos.",
    )
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
    if args.source:
        args.source = " ".join(args.source)
    else:
        args.source = os.environ.get("UPLOAD_VIDEO_SOURCE", DEFAULT_VIDEO_SOURCE)
    return args


def choose_video(source):
    source_path = Path(source).expanduser()

    if source_path.is_file():
        if source_path.suffix.lower() not in VIDEO_EXTENSIONS:
            raise ValueError(f"Not a supported video file: {source_path}")
        return source_path.resolve()

    if not source_path.is_dir():
        raise FileNotFoundError(f"Video source does not exist: {source_path}")

    videos = [
        path
        for path in source_path.iterdir()
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    ]
    if not videos:
        raise FileNotFoundError(f"No supported video files found in: {source_path}")

    # Pick the newest file so dropping a fresh export into the folder just works.
    return max(videos, key=lambda path: path.stat().st_mtime).resolve()


def wait_for_result(description, timeout_seconds, check, interval_seconds=0.5):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(interval_seconds)
    raise TimeoutError(f"Timed out waiting for {description}.")


def near_white(pixel):
    r, g, b = pixel
    return r >= 235 and g >= 235 and b >= 235 and max(pixel) - min(pixel) <= 25


def is_youtube_blue(pixel):
    r, g, b = pixel
    return b >= 145 and g >= 85 and r <= 90 and b - r >= 70


def find_button_by_color(matches_color, prefer="center"):
    screenshot = pyautogui.screenshot().convert("RGB")
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
    return int(button_x), int(button_y)


def find_bright_button():
    return find_button_by_color(near_white, prefer="center")


def find_blue_next_button():
    return find_button_by_color(is_youtube_blue, prefer="bottom_right")


def find_white_next_button():
    return find_button_by_color(near_white, prefer="bottom_right")


def find_next_button():
    return find_white_next_button() or find_blue_next_button()


def wait_for_select_files_button(timeout_seconds):
    return wait_for_result(
        "the Select files button",
        timeout_seconds,
        find_bright_button,
        interval_seconds=0.75,
    )


def wait_for_next_button(timeout_seconds):
    return wait_for_result(
        "the Next button",
        timeout_seconds,
        find_next_button,
        interval_seconds=0.5,
    )


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


def paste_text(text):
    try:
        import tkinter

        root = tkinter.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        pyautogui.hotkey("ctrl", "v")
    except Exception:
        pyautogui.write(text, interval=0.01)


def select_video_in_dialog(video_path, folder_wait):
    log(f"File picker: opening folder {video_path.parent}")
    pyautogui.hotkey("alt", "d")
    paste_text(str(video_path.parent))
    pyautogui.press("enter")
    log(f"File picker: waiting {folder_wait:.1f}s for folder to load")
    time.sleep(folder_wait)

    log(f"File picker: entering filename {video_path.name}")
    pyautogui.hotkey("alt", "n")
    paste_text(video_path.name)
    pyautogui.press("enter")
    log("File picker: pressed Enter/Open")


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


def click_publish(wait_timeout, click_delay):
    log("Publish: waiting for the Publish button")
    try:
        publish_x, publish_y = wait_for_next_button(wait_timeout)
        log(f"Publish: button found at ({publish_x}, {publish_y})")
    except TimeoutError as error:
        publish_x, publish_y = fallback_next_coordinates()
        log(
            f"Publish: {error} "
            f"Using bottom-right fallback at ({publish_x}, {publish_y})"
        )

    log(f"Publish: waiting {click_delay:.1f}s before clicking")
    time.sleep(click_delay)
    pyautogui.moveTo(publish_x, publish_y, duration=0.2)
    pyautogui.click(publish_x, publish_y)
    log(f"Publish: clicked at ({publish_x}, {publish_y})")


def click_next_fail_safe(clicks, delay_min, delay_max, wait_timeout):
    if clicks < 1:
        raise ValueError("--next-clicks must be at least 1.")
    if delay_min < 0 or delay_max < 0 or delay_min > delay_max:
        raise ValueError("Next delay values must be positive and min must be <= max.")

    for attempt in range(1, clicks + 1):
        log(f"Next attempt {attempt}/{clicks}: looking for the Next button")
        try:
            next_x, next_y = wait_for_next_button(wait_timeout)
            log(f"Next attempt {attempt}/{clicks}: found button at ({next_x}, {next_y})")
        except TimeoutError as error:
            next_x, next_y = fallback_next_coordinates()
            pyautogui.click(next_x, next_y)

            log(
                f"Next attempt {attempt}/{clicks}: {error} "
                f"Using bottom-right fallback at ({next_x}, {next_y})"
            )

        pyautogui.click(next_x, next_y)
        pyautogui.click(next_x, next_y)

        log(f"Next attempt {attempt}/{clicks}: clicked at ({next_x}, {next_y})")

        if attempt < clicks:
            delay = random.uniform(delay_min, delay_max)
            log(
                f"Next attempt {attempt}/{clicks}: waiting {delay:.2f}s "
                "before the next fail-safe click"
            )
            time.sleep(delay)


def main():
    args = parse_args()
    log("Upload automation started")
    log(f"Source setting: {args.source}")
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
    button_x, button_y = wait_for_select_files_button(args.wait_button)
    log(f"Select files button found at ({button_x}, {button_y}); clicking")
    pyautogui.click(button_x, button_y)

    log("Waiting for the Windows file picker")
    wait_for_file_dialog(args.wait_dialog)
    log("Windows file picker is active")
    select_video_in_dialog(video_path, args.folder_wait)

    log("Waiting for YouTube's details screen")
    wait_for_details_screen(args.wait_details)
    log(f"Details screen is available; settling for {args.details_settle:.1f}s")
    time.sleep(args.details_settle)

    click_next_fail_safe(
        args.next_clicks,
        args.next_delay_min,
        args.next_delay_max,
        args.wait_next,
    )
    click_publish(args.wait_publish, args.publish_click_delay)
    log("Upload automation finished")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        log(f"Upload selection failed: {error}")
        sys.exit(1)
