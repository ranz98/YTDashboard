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

## What is pending

This release does not execute jobs. The persistent VPS runner, worker protocol,
Chrome upload automation and automatic scheduling still need implementation.
The dashboard displays that state explicitly. YouTube audience analytics are
also not connected.

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

## Development

Keep comments short and explain decisions rather than restating code. Commit
each completed change with a short, descriptive message. Do not commit keys,
database passwords, Chrome profiles, generated media or deployment backups.
