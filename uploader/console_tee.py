"""
console_tee.py -- always write console output to a file, however the script
is launched.

Shell redirection breaks the moment something starts the script without a
shell (Task Scheduler, a service, py.exe file association). This handles it
from inside the process instead, so there is always a log.

USAGE
-----
Drop this next to your scripts, then add two lines at the very top of
diagnose_session.py, diagnose_click.py, or anything else:

    from console_tee import start_console_log
    start_console_log("diagnostics")

That is it. Output still appears on the console; it is also appended to
logs/diagnostics_<date>.txt.

To pick the path yourself:

    start_console_log("diagnostics", path=r"D:\\logs\\mydiag.txt")

Or set an environment variable, which is handy from a scheduled task:

    set CONSOLE_LOG_FILE=D:\logs\mydiag.txt
"""

import atexit
import faulthandler
import os
import sys
from datetime import datetime
from pathlib import Path

_handle = None
_path = None


class _Tee:
    """Write to the real stream and the log file, flushing after every write.

    Flushing every time is deliberate. Buffered output is lost when the
    process dies hard -- which is exactly the run you most want the log for.
    """

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


def _resolve_path(name, path):
    if path:
        return Path(path).expanduser()

    from_env = os.environ.get("CONSOLE_LOG_FILE", "").strip()
    if from_env:
        return Path(from_env).expanduser()

    script_dir = Path(sys.argv[0]).resolve().parent
    stamp = datetime.now().strftime("%Y-%m-%d")
    return script_dir / "logs" / f"{name}_{stamp}.txt"


def start_console_log(name="console", path=None, header=True):
    """Mirror stdout and stderr into a text file. Returns the path, or None."""
    global _handle, _path

    if _handle is not None:
        return _path

    target = _resolve_path(name, path)

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        _handle = open(target, "a", encoding="utf-8", errors="replace", buffering=1)
        _path = target
    except Exception as error:
        # Logging must never be the thing that kills the run.
        print(f"WARNING: could not open log file {target}: {error}", flush=True)
        return None

    sys.stdout = _Tee(sys.__stdout__, _handle)
    sys.stderr = _Tee(sys.__stderr__, _handle)

    if header:
        _handle.write("\n" + "=" * 72 + "\n")
        _handle.write(f"RUN {datetime.now().isoformat(timespec='seconds')}\n")
        _handle.write(f"script:  {' '.join(sys.argv)}\n")
        _handle.write(f"cwd:     {os.getcwd()}\n")
        _handle.write(f"python:  {sys.version.split()[0]} ({sys.executable})\n")
        _handle.write(f"user:    {os.environ.get('USERNAME', '?')}\n")
        _handle.write("=" * 72 + "\n")
        _handle.flush()

    # Native crashes (segfaults, access violations) never reach a Python
    # except block, so they never reach the log unless faulthandler is on.
    try:
        faulthandler.enable(file=_handle, all_threads=True)
    except Exception:
        pass

    atexit.register(stop_console_log)
    return _path


def stop_console_log():
    global _handle
    if _handle is None:
        return
    try:
        _handle.write(f"ENDED {datetime.now().isoformat(timespec='seconds')}\n")
        _handle.flush()
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        _handle.close()
    except Exception:
        pass
    finally:
        _handle = None


def log_path():
    return _path