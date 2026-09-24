"""
click_patch.py -- fix the click that does not register.

Your log shows detection is perfect (score 0.969 at 960,664) and the click
produces nothing. Two causes, both handled here:

  1. Chrome does not have focus. Your .bat opens Chrome, waits, then starts
     Python -- so the console window is foreground. A click into a background
     window gets consumed activating it and never reaches the button.

  2. active_file_dialog() only looks at getActiveWindow(). If the picker
     opens without taking focus, the script never sees it and burns the full
     30s timeout, which looks exactly like a dead click.

HOW TO APPLY
------------
Save this next to trainder.py, then make three edits:

  (a) Near the top of trainder.py, after the other imports:

          from click_patch import robust_click, wait_for_file_dialog

      That import shadows the existing wait_for_file_dialog. Put it AFTER
      the function definitions or just delete the old one.

  (b) In main(), replace:

          log(f"Select files button at ({button_x}, {button_y}); clicking")
          pyautogui.moveTo(button_x, button_y, duration=0.2)
          pyautogui.click(button_x, button_y)

      with:

          log(f"Select files button at ({button_x}, {button_y}); clicking")
          if not robust_click(button_x, button_y, expect=file_dialog_open):
              raise RuntimeError("Select files click never opened a dialog")

  (c) Do the same for the Next and Publish clicks (no `expect` needed there;
      leave it None and it will just verify the screen changed).

Test it standalone first -- this runs the same click the uploader would:

    python click_patch.py 960 664
"""

import ctypes
import sys
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

import pyautogui  # noqa: E402
from PIL import Image  # noqa: E402


# --------------------------------------------------------------------------
# Window focus
# --------------------------------------------------------------------------

GA_ROOT = 2
SW_RESTORE = 9


def _window_at(x, y):
    point = wintypes.POINT(int(x), int(y))
    hwnd = user32.WindowFromPoint(point)
    if not hwnd:
        return None
    return user32.GetAncestor(hwnd, GA_ROOT) or hwnd


def _window_title(hwnd):
    if not hwnd:
        return None
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def activate_window_at(x, y):
    """Bring whatever is under (x, y) to the foreground, and mean it.

    SetForegroundWindow is refused when the calling process does not own the
    current foreground window -- which is our exact situation, since the
    console owns it. AttachThreadInput to the foreground thread first is the
    documented way around that.
    """
    hwnd = _window_at(x, y)
    if not hwnd:
        return None

    if user32.GetForegroundWindow() == hwnd:
        return hwnd

    user32.ShowWindow(hwnd, SW_RESTORE)

    foreground = user32.GetForegroundWindow()
    our_thread = ctypes.windll.kernel32.GetCurrentThreadId()
    their_thread = user32.GetWindowThreadProcessId(foreground, None)

    attached = False
    if their_thread and their_thread != our_thread:
        attached = bool(user32.AttachThreadInput(our_thread, their_thread, True))

    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetActiveWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(our_thread, their_thread, False)

    time.sleep(0.4)
    return hwnd


# --------------------------------------------------------------------------
# File dialog detection -- enumerate ALL windows, not just the active one
# --------------------------------------------------------------------------

FILE_DIALOG_CLASS = "#32770"

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _class_name(hwnd):
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def find_file_dialog():
    """Return the HWND of a visible Windows file picker, anywhere on screen.

    Class #32770 is the standard Win32 dialog class. Matching on class is far
    stronger than matching on title: the original code tested
    `"open" in title`, which also matches any Chrome tab whose page title
    happens to contain "open".
    """
    found = []

    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        if _class_name(hwnd) != FILE_DIALOG_CLASS:
            return True
        # A real picker has a filename edit box. Dialog class alone also
        # matches things like Chrome's print dialog shell.
        if user32.FindWindowExW(hwnd, None, "ComboBoxEx32", None) or \
           user32.FindWindowExW(hwnd, None, "DirectUIHWND", None):
            found.append(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return found[0] if found else None


def file_dialog_open():
    return find_file_dialog() is not None


def wait_for_file_dialog(timeout_seconds=30.0):
    """Replacement for trainder.py's version. Returns the HWND."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        hwnd = find_file_dialog()
        if hwnd:
            # Make sure it has focus before we start typing a path into it.
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.3)
            return hwnd
        time.sleep(0.25)
    raise TimeoutError("Timed out waiting for the Windows file picker.")


# --------------------------------------------------------------------------
# The click itself
# --------------------------------------------------------------------------

def _snapshot():
    return pyautogui.screenshot().convert("L").resize((160, 160), Image.LANCZOS)


def _changed(before, after, threshold=500):
    count = 0
    for a, b in zip(before.getdata(), after.getdata()):
        if abs(a - b) > 12:
            count += 1
    return count > threshold, count


def _press(x, y, hold=0.09):
    """Hover in, then press with a real hold duration.

    pyautogui.click() sends mousedown and mouseup with no gap. Polymer
    components like YouTube's ytcp-button sometimes miss a press that arrives
    in a single frame. Approaching from an offset also gives the button a
    genuine hover event first.
    """
    pyautogui.moveTo(x - 30, y - 15, duration=0.15)
    pyautogui.moveTo(x, y, duration=0.18)
    time.sleep(0.2)
    pyautogui.mouseDown(x, y)
    time.sleep(hold)
    pyautogui.mouseUp(x, y)


def robust_click(x, y, expect=None, attempts=3, settle=2.5, verbose=True):
    """Click (x, y) and confirm it actually did something.

    expect: optional zero-arg callable returning True once the click has had
            its intended effect (e.g. file_dialog_open). If None, falls back
            to "the screen changed", which is weaker but still catches a
            completely dead click.

    Returns True on success, False if every attempt went nowhere.
    """
    def say(message):
        if verbose:
            print(f"[click] {message}", flush=True)

    for attempt in range(1, attempts + 1):
        hwnd = activate_window_at(x, y)
        say(f"attempt {attempt}/{attempts}: target window "
            f"{_window_title(hwnd)!r}")

        before = None if expect else _snapshot()

        _press(x, y)
        say(f"attempt {attempt}/{attempts}: pressed at ({x}, {y})")

        deadline = time.monotonic() + settle
        while time.monotonic() < deadline:
            time.sleep(0.3)
            if expect:
                if expect():
                    say(f"attempt {attempt}/{attempts}: confirmed")
                    return True
            else:
                changed, amount = _changed(before, _snapshot())
                if changed:
                    say(f"attempt {attempt}/{attempts}: screen changed "
                        f"({amount} px)")
                    return True

        say(f"attempt {attempt}/{attempts}: nothing happened")

        # A window that was not foreground eats the first click activating
        # itself. The retry lands on an already-focused window.
        time.sleep(0.6)

    say("all attempts failed")
    return False


# --------------------------------------------------------------------------
# Standalone test
# --------------------------------------------------------------------------

def main():
    if len(sys.argv) >= 3:
        x, y = int(sys.argv[1]), int(sys.argv[2])
    else:
        print("Hover over the Select files button. Reading position in 6s...")
        for remaining in range(6, 0, -1):
            print(f"  {remaining}...", end="\r", flush=True)
            time.sleep(1)
        x, y = pyautogui.position()

    print(f"\nTarget: ({x}, {y})")
    print(f"Window under cursor: {_window_title(_window_at(x, y))!r}")
    print(f"Current foreground:  {_window_title(user32.GetForegroundWindow())!r}")
    print(f"File dialog already open? {file_dialog_open()}")
    print()

    ok = robust_click(x, y, expect=file_dialog_open)

    print()
    if ok:
        print("SUCCESS -- the file picker opened.")
        print("Apply the three edits at the top of this file to trainder.py.")
        return 0

    print("FAILED -- no file picker after 3 attempts.")
    print()
    print("Next things to check, in order:")
    print("  1. Is Chrome running elevated while this script is not? Windows")
    print("     silently drops synthetic clicks into a higher-integrity window")
    print("     while still allowing the cursor to move -- exactly your symptom.")
    print("     Close Chrome and relaunch it WITHOUT 'Run as administrator',")
    print("     or run this from the same elevation as Chrome.")
    print("  2. Is the button actually enabled? A greyed-out Select files")
    print("     still matches the template at high confidence.")
    print("  3. Try diagnose_click.py, which also tests a raw SendInput path.")
    return 1


if __name__ == "__main__":
    sys.exit(main())