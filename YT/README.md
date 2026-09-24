# First Short Grabber

Opens the newest Short from a YouTube channel, copies its URL to the clipboard,
and saves it to a text file. Driven by a `.bat` file — double-click and done.

Default channel: **@Clips_Edge**

---

## One command

```bash
RUNPIPELINE.bat
```

Finds the newest Short, downloads it, then detects / reads / rewrites / redraws
the caption. `RUNPIPELINE.bat @SomeHandle` targets another channel, and
`RUNPIPELINE.bat <video-url>` skips the search and uses that video.

### The colour grade

The last step grades the picture as well as replacing the caption.
`vivid` is the default; pass another as the second argument:

```bash
RUNPIPELINE.bat @Clips_Edge cinematic
```

Presets: `vivid` `punch` `warm` `cool` `bright` `fade` `cinematic` `clarity`
`bw` `vignette` `none`. Or set `FILTER` before running.

The grade runs **before** the caption is drawn, in the same ffmpeg graph, so
the caption stays crisp and exactly the colours you asked for, and the whole
job is still one encode. Grading as a separate step would re-encode the
finished video a second time and lose quality for nothing.

Comparing presets is cheap with `--preview`, which renders only the first few
seconds to `video-preview.mp4` instead of the ~2 minutes a full 4K pass takes:

```bash
python cover_caption.py --rewrite --filter cinematic --preview 3
```

### The video title

The title is rewritten too, in the same voice as the caption but with its own
system message: a title is read cold in a feed, truncated, with no picture yet
doing the work, so it leads with the searchable name and puts the hook before
the cut-off point.

| File | What |
| --- | --- |
| `output/latest-title.txt` | the title, written by the extension each run |
| `<video folder>/title.txt` | the full title from yt-dlp - the authoritative one |
| `<video folder>/title-new.txt` | the rewrite |

Two details. The folder name is **not** the title: yt-dlp truncates it to 60
characters and strips whatever Windows will not accept, so `title.txt` comes
from the metadata instead, and a folder downloaded before this existed gets its
real title fetched rather than read back off disk.

Trailing hashtags are held aside during the rewrite and reattached afterwards,
so the model spends its character budget on the sentence and the search tags
survive intact. Skip the whole step with `--no-title`.

### Resuming, and running it twice

Every stage is safe to re-run and picks up where the last one stopped.

| Situation | What happens |
| --- | --- |
| Nothing downloaded yet | downloads, then processes |
| Already downloaded, not yet processed | reuses the files, processes them |
| Already downloaded and processed | both stages report it and stop |
| In the archive but the files are gone | clears the record and re-fetches immediately |
| Downloaded earlier, missing its `frame.jpg` | regenerates the frame, then processes |

Two details make that work. `download.py` records the folder it resolved to
`output/last-folder.txt`, and the pipeline hands that exact path to the caption
stage — otherwise step 3 would fall back to "the newest folder", which is the
wrong video whenever the requested one was downloaded on an earlier day. And an
archive skip exits 0: the files are present either way, so it is a skip rather
than a failure and the pipeline continues.

`--skip-existing` is what makes the caption stage stop when `video-covered.mp4`
is already newer than its source. Manual runs omit it, so they always re-render.

## Setup — once

Double-click **`setup.bat`**.

It creates a dedicated Chrome profile in `chrome-profile\`, points that
profile's downloads at `output\`, and opens a Chrome window on the Extensions
page. In **that** window:

1. Turn on **Developer mode** (toggle, top right)
2. Click **Load unpacked**
3. Select this folder
4. Close the window once the extension is listed

> **Why a separate profile?** Chrome 137+ ignores the `--load-extension`
> command-line flag, so a `.bat` can't inject an extension at launch. The
> extension has to live in a profile that persists. Yours is Chrome 151. A
> separate profile also keeps this off your everyday browser.

## Use — every time

Double-click **`run.bat`**.

```
run.bat                 # @Clips_Edge
run.bat @SomeChannel    # any other channel
```

What happens:

1. `run.bat` looks up the extension's ID and opens its trigger page in Chrome
2. The extension opens the channel's Shorts tab and reads the **first** Short
3. If it's new, that tab navigates to the Short — so it's playing in front of you
4. Results are written to `output\`
5. `run.bat` reads them, prints the outcome, and copies the URL to your clipboard

The Chrome window shows a live log of each step while it works.

## New-video detection

Every run compares the channel's newest Short against everything captured
before, so repeat runs are cheap and the log stays clean.

| | New Short | Already captured |
| --- | --- | --- |
| Opens the Short | yes | no |
| `shorts-log.txt` | appends a line | untouched |
| `latest-short.txt` | rewritten | refreshed (same URL) |
| `no-new.txt` | deleted | written, with first-seen date |
| Terminal | `NEW SHORT` + URL | `NO NEW SHORTS` + when it was first seen |

The clipboard gets the newest URL either way, so a run is never a dead end.

Seen IDs live in `chrome.storage` (`seenIds`, capped at 5000 — far more than
the 500-entry history, so a Short can never age out of the set and reappear as
new). Deleting `chrome-profile\` resets that memory; deleting the text files
does not.

## Output

| File | Contents |
| --- | --- |
| `output\latest-short.txt` | Just the URL, one line — overwritten each run |
| `output\shorts-log.txt` | Every **new** capture, newest first: timestamp, channel, URL, title |
| `output\no-new.txt` | Only when nothing was new — the newest URL and when it was first seen |
| `output\error.txt` | Only on failure — why it failed. `run.bat` prints it and stops waiting |

## Downloading the video

`download.py` fetches the video and saves its first frame. With no arguments it
uses whatever `run.bat` just captured:

```bash
run.bat
python download.py
```

| Command | Does |
| --- | --- |
| `python download.py` | the last captured Short |
| `python download.py <url> <url>` | specific videos |
| `python download.py --from-log` | every URL in `shorts-log.txt` |
| `python download.py --max-height 1080` | cap the resolution |
| `python download.py --frame-format png` | png frame instead of jpg |
| `python download.py --audio-only` | mp3, no frame |
| `python download.py --no-archive` | re-download something already fetched |

Each video gets its own folder, grouped by the date of the run:

```
output/videos/2026-08-17/N3ON Was HAPPY When Arman... [oKy2HnwOESE]/
    video.mp4
    frame.jpg
```

The frame is the true **frame 0** — extracted by decoding from the start rather
than seeking, since a seek lands on the nearest keyframe, which is often not the
first frame.

Repeat downloads are skipped via `output/downloaded.txt`, the same
only-what's-new idea `run.bat` uses. If a download turns out corrupt, its ID is
removed from that archive so the next run retries instead of skipping forever.

### Two environment traps on this machine

**Partial files never touch OneDrive.** `.part` files are staged in
`%TEMP%\fsg-download` and only the finished video is moved into `output\`.
The output tree lives inside OneDrive, which syncs half-written files and locks
them mid-rename — that produces `WinError 32: being used by another process`
and, worse, silently corrupt mp4s.

**Avast intercepts HTTPS.** yt-dlp verifies against `certifi`'s CA bundle, which
does not contain Avast's MITM root, so it can fail with
`CERTIFICATE_VERIFY_FAILED` even though normal browsing works. `download.py`
detects this and prints the fix; `--insecure` skips verification for one run.

**Keep yt-dlp current.** YouTube rotates its player signature; a stale yt-dlp
fails confusingly — `nsig extraction failed`, then "Only images are available".
The script prints its yt-dlp version in the header and names the cure:

```bash
python -m pip install -U yt-dlp
```

## Covering the original caption

`cover_caption.py` finds the white caption box in `frame.jpg` and paints over it
for the whole video.

```bash
python download.py
python cover_caption.py
```

| Command | Does |
| --- | --- |
| `python cover_caption.py --rewrite` | rewrite with DeepSeek, draw it in the box |
| `python cover_caption.py` | newest download, cover the caption |
| `python cover_caption.py --detect-only` | find it and preview, render nothing |
| `python cover_caption.py --mode blur` | blur the region instead |
| `python cover_caption.py --mode pixelate` | pixelate it |
| `python cover_caption.py --color white` | fill with another colour |
| `python cover_caption.py --box 254,1203,1652,355` | skip detection, use these coords |
| `python cover_caption.py --no-ocr` | skip reading the caption text |

It writes these next to the video:

| File | What |
| --- | --- |
| `frame-detected.jpg` | the frame with the box outlined in red — **check this first** |
| `caption-box.txt` | `x,y,w,h`, reusable via `--box` |
| `caption-crop.png` | just the caption, as fed to OCR |
| `caption.txt` | the caption text, read out of the box |
| `video-covered.mp4` | the covered video |

### Reading the caption text

The detected rectangle is cropped and run through OCR, and the text lands in
`caption.txt`. Cropping first is what makes this reliable — the engine only ever
sees high-contrast black-on-white, never the busy video around it.

It uses **Windows.Media.Ocr**, built into Windows 10/11: no separate binary, no
model download, works offline. `pytesseract` is a fallback but only when the
Tesseract *binary* is on PATH — the Python package alone does nothing, which is
the state this machine was in. Skip the step with `--no-ocr`.

Two known limits: emoji are dropped (the 🙄 in the test caption did not survive),
and `0`/`O` is the usual OCR coin-flip — `N3ON` came back as `N30N`. Check
`caption.txt` before using it verbatim.

### How detection works

Nothing is hardcoded — the box is found fresh in each video's own `frame.jpg`,
and the caption genuinely does move (14%, 11%, 31% and 71% down the frame across
four test clips). Three findings shaped the algorithm:

**Brightness alone fails.** A white hoodie or a sunlit wall is as bright as the
caption, and the morphological close that repairs the text-perforated slab welds
them into one blob covering half the frame — 53% fill across 2160×1690 on the
first test clip, nothing like a caption. The caption is *pure* white though,
while video content is tinted, so gating on **low saturation as well as high
brightness** separates them: the same frame then yields one candidate at 94%
fill, 76% of the width, 4.8:1 aspect.

**"How solidly filled is this rectangle" is the wrong test.** These captions draw
a rounded background *per line*, and the lines have ragged widths, so a box
around all of them is mostly empty at the corners — a real three-line caption
measured 0.48 and was rejected. Each line is detected as its own solid slab and
neighbouring lines are then grouped.

**Sometimes the lines touch** and arrive as one ragged component instead, too
tall for any per-line height cap. So whole blocks are collected as candidates
too, and both shapes are scored the same way: **white pixels actually painted**,
weighted by width. That puts a ragged block and a tidy stack of lines on equal
footing, and it is what finds the bottom-of-frame caption that every earlier
version missed.

Grouping requires comparable line heights and 50% horizontal overlap — without
that, the KICK banner directly below a caption gets absorbed and the box grows
past the real text.

Detection runs once on the still; the rectangle is handed to ffmpeg, so the video
is touched exactly once rather than decoded frame-by-frame in Python.

Tuning knobs when a clip is unusual: `--region top|bottom` narrows the search,
`--value` / `--sat` loosen the white test, and `--box x,y,w,h` skips detection
entirely. Read coordinates off `frame-detected.jpg`.

**Note:** covering re-encodes the video (x264, CRF 18). The source here is AV1,
which cannot be stream-copied through a filter, so some quality loss is
unavoidable; raise `--crf` for smaller files or lower it for better quality.

## Manual runs

Click the toolbar icon for a popup with a channel box and a **Grab** button.
Useful for a second capture without relaunching Chrome. It writes the same two
files and copies the URL.

---

## How it works

```
run.bat ──reads the extension ID from the profile
        └─launches Chrome──▶ chrome-extension://<id>/trigger.html?channel=@Handle
                                        │
                            trigger.js messages the worker
                                        │
                            opens the channel's Shorts tab
                                        │
                            scrapes first /shorts/<id> anchor
                                        │
                     navigates that tab to the Short ──▶ plays
                                        │
                            writes output\*.txt
                                        │
run.bat ◀──polls for the file──────────┘  then copies to clipboard
```

**Why an extension page and not a YouTube URL?** The first design opened
`youtube.com/@Handle/shorts?ytgrab=1` and had the worker watch for that marker.
It failed silently: waking a service worker from a `tabs` event is not
guaranteed, and YouTube redirects the page on first load in a fresh profile
(appending `themeRefresh=1`), which destroys any script injected into the old
frame — `executeScript` then hangs rather than failing.

An extension page has none of those problems. It always loads, nothing can
redirect it or strip its query string, and it messages the worker directly
instead of hoping an event wakes it. The marker path is still in `background.js`
as a fallback, but nothing depends on it.

Progress is published to `chrome.storage` at each stage, so `trigger.html`
mirrors it live in the Chrome window while `run.bat` prints a heartbeat.

### Files

| File | Role |
| --- | --- |
| `manifest.json` | MV3 manifest |
| `background.js` | Service worker: scraping, retries, file writing |
| `trigger.html` / `trigger.js` | Page `run.bat` opens; starts the grab, shows the live log |
| `popup.html` / `popup.js` | Toolbar UI for manual runs, and the clipboard write |
| `offscreen.html` / `offscreen.js` | Fallback blob-URL source for downloads |
| `find-extension-id.ps1` | Resolves the unpacked extension's ID from the profile |
| `download.py` | Downloads the video and saves its first frame |
| `cover_caption.py` | Detects the white caption box and covers it |
| `setup.bat` | One-time profile creation |
| `run.bat` | Everyday entry point |

The extension only ever touches `youtube.com`, and only acts on a tab carrying
the marker — it does nothing while you browse normally.

## After editing any extension file

Unpacked extensions do **not** pick up changes on their own. Go to
`chrome://extensions` in the `chrome-profile` window and hit the **reload arrow**
on the extension card, or just close that Chrome window and run `run.bat` again.

## Troubleshooting

**`run.bat` prints an error.** That text came from `output\error.txt`, written by
the extension itself — it says which stage failed. For the full stack, open
`chrome://extensions` in that profile and click the extension's **service worker**
link.

**`run.bat` times out with nothing.** Look at the Chrome window it opened.

- *Consent or sign-in wall instead of the channel* — accept it once in that
  profile; the choice sticks for later runs.
- *Extension missing* — check `chrome://extensions` in that profile. Re-run
  `setup.bat` if it's gone.
- *Empty Shorts tab* — the channel may have no Shorts.

**No file appears but the Short opens.** Chrome is prompting for a download
location. In that profile: Settings → Downloads → turn off "Ask where to save
each file", and set the folder to this project's `output\`.

**It opens the Short but writes no file.** The `data:` URL download was refused.
The extension falls back to an offscreen document automatically; if that also
fails, `error.txt` will say so.

**YouTube changed its layout.** The scraper takes the first `/shorts/<id>` link
in the grid, trying `ytd-rich-grid-renderer #contents` first, then the browse
results container, then the whole page. If YouTube renames those, the page-wide
fallback still works — it filters by the `/shorts/<id>` URL shape, so the
sidebar's `/shorts` nav link can't match. Edit `scrapeFirstShort` in
`background.js` if it ever needs adjusting.

## Notes / limits

- **"First" means first in the grid**, which is what the channel's Shorts tab
  shows by default (newest). If you re-sort the tab, that's what gets grabbed.
- Downloads always go to the profile's download folder — `setup.bat` sets that
  to `output\`. The extension can't write to an arbitrary path; that's a Chrome
  restriction, not a design choice.
- `chrome-profile\` and `output\` are generated. Delete `chrome-profile\` to
  start over (you'd re-run `setup.bat`).
