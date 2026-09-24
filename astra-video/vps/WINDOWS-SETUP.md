# Run Astra on your Windows VPS

1. Extract the complete `ASTRA` folder to `C:\Astra`. Keep its subfolders together.
2. Use your existing **Python 3.10 or newer (64-bit)** and editor packages,
   **Google Chrome**, and **FFmpeg**. Add FFmpeg's `bin` folder to PATH.
   Both `ffmpeg` and `ffprobe` must work in a new Command Prompt. Windows OCR
   needs an English language pack. If unavailable on Windows Server, install
   Tesseract with English data and add it to PATH. The installer checks this.
   Setup selects the installed Python with the most required packages. It does
   not create an environment, install packages, or upgrade anything. Python 3.11
   specifically and the Python launcher are not required. If your working scripts
   use a custom Python path, set `ASTRA_PYTHON` to that executable before setup.
   Keep your working yt-dlp version and its existing Deno or Node runtime, if used.
3. Double-click `C:\Astra\astra-video\vps\install.cmd`.
   Enter the **dashboard admin login** and your DeepSeek API key when prompted.
4. In the Chrome profile you will keep running, sign in to YouTube Studio and
   select the intended destination channel. Set Studio's language to English.
5. Open `chrome://extensions`, enable **Developer mode**, choose **Load unpacked**,
   and select `C:\Astra\astra-video\vps\extension`.
6. Open the extension's Options. Paste the key from
   `C:\Astra\astra-video\vps\data\PAIRING-KEY.txt` and click **Pair with runner**.
7. Double-click `start.cmd`. Keep Chrome and this Windows user signed in.
   Disable the old scheduled pipeline before starting this replacement: old
   scripts do not obey the new dashboard lock.
8. Sign in to the dashboard, press **Start**, then **Fetch now** for the first
   scan. Check the queue and Errors tab. New downloads enter editing immediately;
   uploads wait for a post slot. The first live upload needs observation on your
   VPS because Studio's controls can vary by account.

The extension uses the **not made for kids** audience selection, matching the
current clips workflow. Do not enable uploads for a different audience without
changing that selection. Uploads are Public at the configured post slot.

## Lightweight update

Astra now uses local port **18765** to avoid older scripts on port 8765. Update
both the runner files and the Chrome extension together. Only one server can
bind the new port; a conflict stops startup with an error. Pairing keys stay valid.

Stop the runner and wait for any active task to stop. Extract this package over
the existing Astra folder. Run `install.cmd` to save the chosen Python path;
existing dashboard configuration and pairing are preserved. In `chrome://extensions`,
reload Astra VPS Agents and accept the new request-blocking permission if Chrome
asks. Then run `start.cmd`. Do not delete the media folder or task journal.

The original editor files are unchanged. The runner lowers the editor process
priority; the original editor chooses its own FFmpeg settings. The adapter limits
its separate verification pass. No caption, OCR or render logic is rewritten.

To use the exact working copy on your VPS, configure `editor_script` with its
absolute `cover_caption.py` path and `editor_python` with the Python executable
used by that installation in `config.json`. Keep its companion files and original
DeepSeek key in place. The runner invokes this editor without modifying its files.

The extension blocks image/media requests only in its channel-scan tab, pauses
previews, and removes the rules after the scan. Studio upload traffic is untouched.
UI checks run every 3 seconds, or 10 seconds during a long upload wait. Server
heartbeats remain every 15 seconds. Only one pipeline stage runs at once.

`requirements.txt` is a reference for fresh machines, not an automatic installation
step. If checks find something missing, setup lists it and stops without changes.

## Start automatically without Task Scheduler

Once the first run works, right-click PowerShell in the `vps` folder and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\install-startup.ps1
```

This starts the runner at Windows sign-in. Open Chrome after signing in too.
It is not a background Windows service and does not sign in for you after a
reboot. Chrome must remain running; the dashboard can be closed.

## Stop and inspect

Use dashboard **Stop** to pause claims and cancel active work, or double-click
`stop.cmd` to stop this runner. Browser work must acknowledge cancellation before
the shared slot is released. If Chrome disconnects, the runner holds the slot.

Public stage messages appear in the dashboard console. Detailed private output
is in `data/tasks/<task id>/stage.log`; runner status is in `data/runner.log`.
Never share `config.json`, pairing keys, browser profiles or API keys.

If `data/active.json` remains after a crash, do not delete it or repeat the
upload. Review the browser and dashboard first. Unknown upload outcomes are
blocked, so the same video is not published twice by an automatic retry.

## What has been verified

Offline contract tests and syntax checks cover the mailbox, task journal,
authentication, media path selection and cancellation. No real YouTube upload
was performed on your VPS. Studio selectors, account permissions, OCR support,
DeepSeek credentials and YouTube download access must pass the first live run.

Chrome's service worker scans and uploads; yt-dlp downloads media on the VPS,
and Python/FFmpeg edit it. No VPS access credentials were provided, so installation
on that machine still requires the steps above.

YouTube extraction uses the runtime and EJS package described in the
[official yt-dlp setup guide](https://github.com/yt-dlp/yt-dlp/wiki/EJS).
File selection uses Chrome's [debugger API](https://developer.chrome.com/docs/extensions/reference/api/debugger).
