"""
diagnose_session.py -- why "screen grab failed"?

Run this the SAME WAY you run the upload script (same .bat, same Task
Scheduler entry, same elevation). If you run it by double-clicking while
sitting at an RDP window, it will report a healthy session and tell you
nothing useful.

    python diagnose_session.py

It reports which Windows session the process is in, whether that session has
a live desktop, and which screen-capture backends actually work. Then it
tells you what to change.

The bottom half is a hardened grab_screen() to paste into trainder.py.
"""

import ctypes
import os
import sys
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
try:
    wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
except Exception:
    wtsapi32 = None


# --------------------------------------------------------------------------
# Session identity
# --------------------------------------------------------------------------

WTS_CURRENT_SERVER_HANDLE = 0
WTS_CONNECT_STATE = 8

CONNECT_STATES = {
    0: "Active (a real, connected session -- capture should work)",
    1: "Connected (connected but no user logged on)",
    2: "ConnectQuery",
    3: "Shadow",
    4: "DISCONNECTED (RDP was closed -- this is why capture fails)",
    5: "Idle",
    6: "Listen",
    7: "Reset",
    8: "Down",
    9: "Init",
}


def current_session_id():
    sid = wintypes.DWORD()
    if not kernel32.ProcessIdToSessionId(kernel32.GetCurrentProcessId(),
                                         ctypes.byref(sid)):
        return None
    return sid.value


def session_connect_state(session_id):
    if wtsapi32 is None or session_id is None:
        return None
    buffer = ctypes.c_void_p()
    returned = wintypes.DWORD()
    ok = wtsapi32.WTSQuerySessionInformationW(
        WTS_CURRENT_SERVER_HANDLE,
        session_id,
        WTS_CONNECT_STATE,
        ctypes.byref(buffer),
        ctypes.byref(returned),
    )
    if not ok or not buffer:
        return None
    try:
        return ctypes.cast(buffer, ctypes.POINTER(ctypes.c_int)).contents.value
    finally:
        wtsapi32.WTSFreeMemory(buffer)


# --------------------------------------------------------------------------
# Desktop identity
#
# A locked machine switches the input desktop to "Winlogon". A service in
# session 0 sits on "Default" of a window station with no display. Neither
# can be screenshotted.
# --------------------------------------------------------------------------

DESKTOP_READOBJECTS = 0x0001
UOI_NAME = 2


def _object_name(handle):
    if not handle:
        return None
    size = wintypes.DWORD(0)
    user32.GetUserObjectInformationW(handle, UOI_NAME, None, 0, ctypes.byref(size))
    buffer = ctypes.create_unicode_buffer(max(2, size.value))
    if user32.GetUserObjectInformationW(
        handle, UOI_NAME, buffer, size.value, ctypes.byref(size)
    ):
        return buffer.value
    return None


def input_desktop_name():
    handle = user32.OpenInputDesktop(0, False, DESKTOP_READOBJECTS)
    if not handle:
        return None, ctypes.get_last_error()
    try:
        return _object_name(handle), 0
    finally:
        user32.CloseDesktop(handle)


def thread_desktop_name():
    handle = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
    return _object_name(handle)


# --------------------------------------------------------------------------
# Display metrics + raw GDI capture test
# --------------------------------------------------------------------------

SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
SM_CMONITORS = 80
SRCCOPY = 0x00CC0020


def virtual_screen():
    return (
        user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CMONITORS),
    )


def raw_bitblt_test():
    """Try the GDI screen copy directly, so we get a real error code."""
    screen_dc = user32.GetDC(None)
    if not screen_dc:
        return False, f"GetDC(NULL) returned NULL (err {ctypes.get_last_error()})"

    memory_dc = bitmap = None
    try:
        memory_dc = gdi32.CreateCompatibleDC(screen_dc)
        if not memory_dc:
            return False, f"CreateCompatibleDC failed (err {ctypes.get_last_error()})"
        bitmap = gdi32.CreateCompatibleBitmap(screen_dc, 64, 64)
        if not bitmap:
            return False, f"CreateCompatibleBitmap failed (err {ctypes.get_last_error()})"
        gdi32.SelectObject(memory_dc, bitmap)
        ok = gdi32.BitBlt(memory_dc, 0, 0, 64, 64, screen_dc, 0, 0, SRCCOPY)
        if not ok:
            return False, f"BitBlt failed (err {ctypes.get_last_error()})"
        return True, "BitBlt succeeded"
    finally:
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if memory_dc:
            gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(None, screen_dc)


# --------------------------------------------------------------------------
# Capture backends
# --------------------------------------------------------------------------

def try_pil_default():
    from PIL import ImageGrab
    return ImageGrab.grab()


def try_pil_all_screens():
    from PIL import ImageGrab
    return ImageGrab.grab(all_screens=True)


def try_pyautogui():
    import pyautogui
    return pyautogui.screenshot()


def try_mss():
    import mss
    from PIL import Image

    with mss.mss() as grabber:
        monitor = grabber.monitors[0]
        raw = grabber.grab(monitor)
        return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")


BACKENDS = [
    ("PIL ImageGrab.grab()", try_pil_default),
    ("PIL ImageGrab.grab(all_screens=True)", try_pil_all_screens),
    ("pyautogui.screenshot()", try_pyautogui),
    ("mss (pip install mss)", try_mss),
]


def image_looks_real(image):
    """A black or uniform grab means a driver is present but not rendering."""
    try:
        import numpy as np

        array = np.array(image.convert("L").resize((64, 64)))
        return float(array.std()) >= 4.0, float(array.std())
    except ImportError:
        return None, None


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main():
    print("=" * 72)
    print("SESSION / DESKTOP DIAGNOSTIC")
    print("=" * 72)
    print(f"Python:        {sys.version.split()[0]}")
    print(f"PID:           {os.getpid()}")
    print(f"Working dir:   {os.getcwd()}")
    if os.getcwd().lower().endswith(r"\windows\system32"):
        print("  NOTE: a working directory of System32 means this was started by")
        print("        Task Scheduler, a service, or 'Run as administrator'.")

    session_id = current_session_id()
    print(f"\nSession ID:    {session_id}")

    fatal = []

    if session_id == 0:
        print("  ** SESSION 0. **")
        print("  ** There is no desktop here and there never will be. This is")
        print("  ** what 'Run whether user is logged on or not' does in Task")
        print("  ** Scheduler. GUI automation cannot work from session 0.")
        print("  ** FIX: open the task, General tab, select")
        print("  **      'Run only when user is logged on'.")
        fatal.append("session 0")

    state = session_connect_state(session_id)
    if state is not None:
        print(f"Connect state: {state} -- {CONNECT_STATES.get(state, 'unknown')}")
        if state == 4:
            print("  ** The RDP session is DISCONNECTED. Windows Server tears")
            print("  ** down the graphics stack on disconnect, so every screen")
            print("  ** capture fails while GetSystemMetrics keeps returning")
            print("  ** the cached resolution -- exactly what your log shows.")
            fatal.append("disconnected session")

    desktop_name, desktop_error = input_desktop_name()
    print(f"Input desktop: {desktop_name!r}"
          + (f" (OpenInputDesktop err {desktop_error})" if desktop_error else ""))
    if desktop_name and desktop_name.lower() == "winlogon":
        print("  ** The machine is LOCKED. The secure desktop is in front and")
        print("  ** cannot be captured or clicked.")
        print("  ** FIX: do not lock the session. If you must disconnect, use")
        print("  **      tscon to redirect to console instead of locking.")
        fatal.append("locked (Winlogon desktop)")
    if desktop_name is None:
        print("  ** Could not open the input desktop at all. Usually session 0,")
        print("  ** or a different window station.")
        fatal.append("no input desktop")

    print(f"Thread desktop:{thread_desktop_name()!r}")

    width, height, monitors = virtual_screen()
    print(f"\nVirtual screen: {width}x{height} across {monitors} monitor(s)")
    if width == 0 or height == 0 or monitors == 0:
        print("  ** No display attached. A headless VPS with no virtual display")
        print("  ** driver has nothing to render to.")
        print("  ** FIX: install a virtual display driver (IddSampleDriver,")
        print("  **      usbmmidd, or Parsec's virtual display).")
        fatal.append("no display device")

    ok, message = raw_bitblt_test()
    print(f"Raw GDI BitBlt: {'OK' if ok else 'FAILED'} -- {message}")

    print("\n" + "-" * 72)
    print("Capture backends")
    print("-" * 72)

    working = []
    for name, backend in BACKENDS:
        try:
            image = backend()
        except ImportError as error:
            print(f"  {name}: not installed ({error})")
            continue
        except Exception as error:
            print(f"  {name}: FAILED -- {type(error).__name__}: {error}")
            continue

        real, spread = image_looks_real(image)
        if real is False:
            print(f"  {name}: returned {image.size} but it is BLANK "
                  f"(stddev {spread:.1f}) -- driver present, nothing rendering")
        else:
            detail = f" (stddev {spread:.1f})" if spread is not None else ""
            print(f"  {name}: OK {image.size}{detail}")
            working.append(name)

    print("\n" + "=" * 72)
    if working:
        print("VERDICT: capture works via -> " + ", ".join(working))
        if "PIL ImageGrab.grab()" not in working and "mss (pip install mss)" in working:
            print("Your current backend fails but mss works. Use the")
            print("grab_screen() below, which prefers mss.")
    else:
        print("VERDICT: no capture backend works in this session.")
        print("Cause(s) detected: " + (", ".join(fatal) if fatal else "unclear"))
        print()
        print("This is an environment problem, not a code problem. In order:")
        print("  1. Task Scheduler -> 'Run only when user is logged on'.")
        print("  2. On your RDP client machine, set registry DWORD")
        print("     HKCU\\Software\\Microsoft\\Terminal Server Client")
        print("       RemoteDesktop_SuppressWhenMinimized = 2")
        print("     so minimising the RDP window stops killing the desktop.")
        print("  3. Before disconnecting, redirect the session to console:")
        print("       query session")
        print("       tscon <ID> /dest:console")
        print("  4. Permanent fix: install a virtual display driver and enable")
        print("     autologon so the console session always has a framebuffer.")
    print("=" * 72)
    return 0 if working else 1


# ==========================================================================
# HARDENED grab_screen() -- paste this into trainder.py, replacing the
# existing three-line version.
#
# Two changes that matter:
#   - Tries mss before Pillow. mss uses a different code path and often
#     survives conditions where ImageGrab throws.
#   - On total failure, raises an error that says what is wrong instead of
#     "OSError: screen grab failed" from six frames deep.
#
# Also add preflight_display() and call it at the top of main(), so the run
# aborts in one line rather than crashing mid-flow.
# ==========================================================================

_CAPTURE_BACKEND = None


def grab_screen():
    """Full screenshot as an RGB PIL image, via whichever backend works."""
    global _CAPTURE_BACKEND

    errors = []

    if _CAPTURE_BACKEND is not None:
        try:
            return _CAPTURE_BACKEND().convert("RGB")
        except Exception as error:
            errors.append(f"cached backend: {error}")
            _CAPTURE_BACKEND = None

    for name, backend in BACKENDS:
        try:
            image = backend().convert("RGB")
        except Exception as error:
            errors.append(f"{name}: {error}")
            continue
        _CAPTURE_BACKEND = backend
        return image

    raise RuntimeError(
        "Screen capture failed on every backend. The process has no viewable "
        "desktop.\n"
        "  - Task Scheduler set to 'Run whether user is logged on or not'? "
        "That is session 0 and cannot work. Switch to 'Run only when user is "
        "logged on'.\n"
        "  - RDP session disconnected or minimised? Windows Server tears down "
        "the display on disconnect. Use tscon /dest:console, or install a "
        "virtual display driver.\n"
        "  - Machine locked? The Winlogon desktop cannot be captured.\n"
        "Run diagnose_session.py the same way you run this script for a "
        "specific answer.\n"
        "Backend errors: " + " | ".join(errors)
    )


def preflight_display():
    """Call this first thing in main(). Fails fast with a usable message."""
    session_id = current_session_id()
    if session_id == 0:
        raise RuntimeError(
            "Running in session 0 -- no desktop exists. Change the scheduled "
            "task to 'Run only when user is logged on'."
        )

    state = session_connect_state(session_id)
    if state == 4:
        raise RuntimeError(
            "This RDP session is disconnected, so there is no rendering "
            "surface. Redirect it to the console before disconnecting: "
            "query session, then tscon <ID> /dest:console"
        )

    desktop = input_desktop_name()[0]
    if desktop and desktop.lower() == "winlogon":
        raise RuntimeError(
            "The machine is locked (Winlogon desktop is in front). Unlock it, "
            "or stop locking on disconnect."
        )

    image = grab_screen()  # raises with a full explanation if it cannot
    real, spread = image_looks_real(image)
    if real is False:
        raise RuntimeError(
            f"Screen capture returns a blank image (stddev {spread:.1f}). A "
            "display driver is present but nothing is being rendered -- "
            "typically a minimised RDP window. Set "
            "HKCU\\Software\\Microsoft\\Terminal Server Client\\"
            "RemoteDesktop_SuppressWhenMinimized = 2 on the client machine."
        )

    return image.size


if __name__ == "__main__":
    sys.exit(main())