# Pipeline Dashboard

Live view of the YouTube Shorts pipeline: what is scheduled, downloading,
editing, uploading, what succeeded and what failed.

Next.js (App Router) + TypeScript + Tailwind. No database, no ORM, three
runtime dependencies.

---

## How the data actually gets here

The pipeline runs on a **Windows VPS** under Task Scheduler. Vercel is
serverless and cannot read that machine's disk, so the VPS **pushes** state out:

```
VPS (Task Scheduler)                        Vercel
────────────────────                        ──────
1-DOWNLOAD.bat ─┐
2-EDIT.bat      ├─ dashboard_report.py ──►  POST /api/events    ─┐
uploader.bat   ─┘         │                                      ├─► KV store
                          └──────────────►  POST /api/pipeline  ─┘      │
                                                                        ▼
                                        browser ──► GET /api/pipeline ──┘
                                        (polls every 10s)
```

- **`POST /api/events`** — one call when a stage starts, one when it finishes.
  Carries stage, result, duration, exit code, host and any error message.
- **`POST /api/pipeline`** — the full video list, rebuilt from disk by
  `scripts/pipeline_status.py` after every stage.
- Both require the `INGEST_TOKEN` shared secret in an `X-Ingest-Token` header.

**Without a KV store configured the dashboard still deploys and works** — it
falls back to the snapshot committed at `data/pipeline.json` and shows a
"Demo data" banner. Nothing is hardcoded in the components.

---

## Deploying to Vercel

1. **Import the repo** in Vercel and set the **Root Directory** to `dashboard`.
   Framework preset: Next.js. Build command and output are auto-detected.

2. **Add a KV store**: project → Storage → Create → KV (Upstash Redis). Connect
   it to the project. `KV_REST_API_URL` and `KV_REST_API_TOKEN` are injected
   automatically.

3. **Add the ingest secret**: project → Settings → Environment Variables:

   | Name | Value |
   | --- | --- |
   | `INGEST_TOKEN` | a long random string |

   Generate one with:

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

4. **Redeploy** so the new variables are picked up.

---

## Wiring up the VPS

Set these as **System** environment variables on the VPS, so Task Scheduler
sees them (not just your interactive shell):

| Variable | Value |
| --- | --- |
| `DASHBOARD_URL` | `https://your-project.vercel.app` |
| `DASHBOARD_TOKEN` | the same value as `INGEST_TOKEN` |

```powershell
[Environment]::SetEnvironmentVariable('DASHBOARD_URL','https://your-project.vercel.app','Machine')
[Environment]::SetEnvironmentVariable('DASHBOARD_TOKEN','<the token>','Machine')
```

The three batch files already call the reporter — nothing else to wire. Verify
it end to end with:

```bash
python scripts/dashboard_report.py sync
```

That rebuilds the snapshot from `output/videos` and pushes it. If the token or
URL is wrong it prints the reason and exits 0, so it can never break a
scheduled run.

### Task Scheduler notes

- Set `NOPAUSE=1` in the task's environment, or the upload stage waits on a
  `pause` prompt that nobody will ever press.
- Each `.bat` returns a real exit code now (`0` success, non-zero failure), so
  "Last Run Result" in Task Scheduler is meaningful.

---

## Local development

```bash
npm install
npm run dev
```

Reads `data/pipeline.json` on every request. Regenerate it from the real
pipeline output with:

```bash
npm run sync
```

Or seed sample rows to look at the UI without running the pipeline:

```bash
npm run sync:demo
```

To exercise the live path locally, put `INGEST_TOKEN`, `KV_REST_API_URL` and
`KV_REST_API_TOKEN` in `.env.local` (see `.env.example`).

---

## Status model

Status is **derived from files on disk**, never stored separately, so it cannot
drift from what the pipeline actually did:

| Status | Derived from |
| --- | --- |
| `scheduled` | in `output/shorts-log.txt`, no folder on disk yet |
| `processing` | a `.part` / `.tmp` file is present in the folder |
| `downloaded` | a source video exists (and a frame, ready to edit) |
| `edited` | `final/*.mp4` exists and is newer than the source |
| `uploaded` / `successful` | recorded in `output/uploaded.json` |
| `failed` | no frame to detect on, or a truncated render |
| `cancelled` | only from a manual `status-override.txt` in the folder |

The stage tabs (Downloaded / Edited / Uploaded) are **cumulative** — a video
that reached upload still appears under Downloaded, because it genuinely was
downloaded. Filtering on the literal status would empty the earlier tabs as
soon as the pipeline moved on.

---

## API

| Route | Method | Auth | Purpose |
| --- | --- | --- | --- |
| `/api/pipeline` | GET | none | snapshot + runs for the UI |
| `/api/pipeline` | POST | `X-Ingest-Token` | VPS pushes a full snapshot |
| `/api/events` | GET | none | recent runs |
| `/api/events` | POST | `X-Ingest-Token` | VPS reports a stage start/finish |
