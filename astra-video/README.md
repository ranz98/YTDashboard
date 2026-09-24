# Astra Video

Public, read-only video operations dashboard built with PHP, MySQL and plain JavaScript.

Live: https://lightblue-mantis-659122.hostingersite.com/astra/

## What works

- Public overview, channels, jobs, schedules, video library, analytics and console.
- Admin sign-in for saving channels, queuing jobs, pausing schedules and account changes.
- MySQL persistence and console updates every two seconds while visible.
- Responsive navigation and layouts for phones.
- Dark surfaces and high-contrast text throughout the dashboard.
- FTPS deployment with certificate checks, file verification and local backups.
- Fetch, editor and uploader agent cards, countdowns and an Errors tab.
- Sri Lanka time throughout, including posted times and daily analytics.
- Three daily fetches of the latest five videos; duplicate video IDs are ignored.
- US Eastern post slots at noon, 6 PM and 9 PM; fetches run 45 minutes earlier.
- Every downloaded video enters the edit queue. Only verified edits with titles can upload.
- One shared execution slot, lease ownership and conservative stale-worker handling.
- A worker API for claiming, reporting progress and confirming completion.

## What is pending

The persistent VPS runner and Chrome execution adapters are not connected.
The PHP scheduler is advanced by authenticated worker polls, so a closed dashboard
does not stop it. Until a worker connects, countdowns show planned slots and no
videos are fetched, edited or uploaded. YouTube audience analytics are also not connected.

The original Task Scheduler setup is unchanged.

## Files

```text
dashboard/public/       PHP app and static assets uploaded to Hostinger
dashboard/public/private/  Schema and server-only files; HTTP access is denied
deploy/                Python upload and first-time setup scripts
tests/                 Hosted API and authentication checks
data/                  Local credentials and deployment backups; never committed
```

## Deploy

Use Python 3.10 or newer. The deploy scripts use the standard library.

```powershell
python deploy/push_hostinger.py --inspect
python deploy/push_hostinger.py
python deploy/push_hostinger.py --root-redirect
python deploy/update_operations.py
```

The script prompts for the FTP password. It uploads only `dashboard/public/`
to `/public_html/astra/`, preserves the installed private configuration, verifies
each uploaded file and backs up changed remote files under `data/`.
Other files in `public_html` are not touched. FTPS validates Hostinger's provider
certificate (`hstgr.io`) while connecting to the configured FTP IP.

Use `--root-redirect` to also install a small `public_html/index.php` redirect
to `/astra/`. An existing root index is backed up before replacement.

On a new installation, create a private `bootstrap.php` file returning an array
with a cryptographically random `setup_token`, then deploy. Run
`python deploy/configure_hostinger.py` to configure MySQL over HTTPS.
Existing installations do not need this step. Setup locks after installation.

Admin access is at `login.php`. Public visitors do not need an account.
Local admin details are stored in `data/ADMIN-ACCESS.txt` after setup.

## Verify

```powershell
node --check dashboard/public/assets/app.js
python -m py_compile deploy/push_hostinger.py deploy/configure_hostinger.py
python tests/test_hosted.py
```

The hosted checks need the local `data/admin-access.json`. They verify public
reads, authenticated reads, denied anonymous writes, CSRF, input validation,
installer locking, private file protection and logout. They do not upload videos.
The queue diagnostics use a transaction and roll back every fixture and event.
They cover deduplication, exclusive claims, stale leases, skipped-video blocking,
publication confirmation, completion checkmarks and US daylight saving.

## Queue rules

Start/stop controls require an admin session. Public access remains read-only.
Stop blocks new claims and requests cancellation of active work. The execution
slot is released only when its owner acknowledges completion or cancellation.
There is no automatic lock stealing when a worker disappears.

The default schedule follows `America/New_York`; dates are displayed using
`Asia/Colombo`. Editing the clock times in the dashboard saves fixed Sri Lankan
times. The editor runs after downloads and drains the queue sequentially.
At most three confirmed posts are allowed per Sri Lankan calendar day.

Failed and skipped edits cannot publish. Uncertain uploads are held for
reconciliation and cannot be blindly retried. A post is marked complete only
after the worker reports a confirmed YouTube video ID.

## Worker contract

An admin can provision a worker through `api.php?action=worker_register` with
`{ "name": "vps-1" }`. Store the returned token privately; it is only returned once.
Worker requests use `POST worker.php` with `Authorization: Bearer <token>`.
Every request declares `capabilities` from `fetch`, `editor`, and `uploader`.

- `claim` advances due schedules and claims one eligible task under the global lock.
- `heartbeat` takes `id`, `lease`, and `progress`; its reply includes `stop_requested`.
- `complete` takes `id`, `lease`, `state`, and stage-specific results.
- Fetch results contain at most five `{id,title,downloaded:true}` entries.
- Editor success requires `render_verified:true` and a nonempty final `title`.
- Upload success requires `publication_confirmed:true` and `youtube_id`.

Workers must heartbeat at least every 30 seconds, handle stop requests, and
finish local processes before acknowledging cancellation. Never expose worker
tokens, signed upload URLs or local file paths in the public console.

## Development

Keep comments short and explain decisions rather than restating code. Commit
each completed change with a short, descriptive message. Do not commit keys,
database passwords, Chrome profiles, generated media or deployment backups.
