# Run Astra on your Windows VPS

1. Extract the complete `ASTRA` folder to `C:\Astra`. Keep its subfolders together.
2. Use your installed **Python 3.10 or newer (64-bit)**, **Google Chrome**,
   **Node.js 22 or newer**, and **FFmpeg**. Add FFmpeg's `bin` folder to PATH.
   Both `ffmpeg` and `ffprobe` must work in a new Command Prompt. Windows OCR
   needs an English language pack. If unavailable on Windows Server, install
   Tesseract with English data and add it to PATH. The installer checks this.
   The installer detects Python automatically; Python 3.11 specifically and the
   Python launcher are not required. It preserves an existing working environment.
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
