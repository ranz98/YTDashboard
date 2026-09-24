# Windows VPS runner

The runner exists and speaks to the hosted queue. **The Chrome fetch/upload
adapters are still pending. This is not yet an end-to-end video package.**
Its stage list starts empty so installing it cannot accidentally claim work
that it cannot execute. Do not connect the old screen-click uploader: it does
not reliably confirm publication.

## Copy and setup

Copy this entire `vps` folder to `C:\Astra\vps` on the VPS. Install Python 3.10
or newer with the Windows Python launcher. The runner needs no pip packages.

From PowerShell in that folder:

```powershell
py -3 setup.py
```

Enter your dashboard administrator credentials and a unique worker name.
The worker token is saved privately in `config.json`; do not share or commit it.
Do not use the FTP or database password here.

After stage adapters are installed and configured:

```powershell
py -3 runner.py --check
.\start.cmd
```

`--check` validates configuration only. It does not test network credentials,
adapter availability, media processing, or upload access.
Sign in to the dashboard and press Start to permit server claims.
Use dashboard Stop or `stop.cmd` to stop. The runner terminates the active
process tree before acknowledging cancellation. Unknown upload outcomes stay
blocked for review. Private logs are under `data`.

For automatic startup without Task Scheduler:

```powershell
powershell -ExecutionPolicy Bypass -File .\install-startup.ps1
```

This installs a shortcut for the current user's sign-in. It is not a Windows
service and will not start before sign-in. Browser automation needs the user's
Chrome session. Remove `Astra Runner.lnk` from `shell:startup` to uninstall.
Existing scheduled tasks are untouched; disable competing legacy automation
before enabling the new pipeline, once the replacement adapters are verified.

## Stage adapter contract

Add only implemented stages to `commands` in `config.json`. Each command is
an argument array, not a shell string. For example, a future editor adapter:

```json
"commands": {
  "editor": ["{python}", "C:\\Astra\\editor_adapter.py", "{task}", "{result}"]
}
```

`{task}` is an input JSON file containing the claimed task, channel and video.
`{result}` is the JSON output file the adapter must write atomically before
exiting successfully. `{base}` is the runner directory. Never send secrets or
local paths as error reasons: reasons appear on the public dashboard.

Successful results:

```json
{"state":"completed","videos":[{"id":"abcdefghijk","title":"Example","downloaded":true}]}
{"state":"completed","render_verified":true,"title":"Final title"}
{"state":"completed","publication_confirmed":true,"youtube_id":"abcdefghijk"}
```

Fetch must inspect no more than the latest five videos, skip known IDs and
report downloads only after local media verification. Editor must verify its
actual render. Uploader must verify publication on the intended destination;
process exit, an upload progress bar or a Publish click is not confirmation.

Failures use `{"state":"failed","reason":"Short public-safe explanation"}`.
The PHP API validates stage evidence. All stages share the existing server
lease and a local process lock. Heartbeats run every 15 seconds. Stage output
is stored privately in `data/tasks/<id>/stage.log`; it is not streamed to the
public dashboard yet. Dashboard task start, stop and completion events work.

## Interrupted work

An uncertain claim or interrupted process leaves `data/active.json` and stops
new work. Review the server task and any surviving process before recovery.
Do not simply delete the journal: this can hide an orphaned lease or duplicate
an upload. A saved completion is retried on startup, without rerunning the stage.
If the server accepted it but its response was lost, the next attempt will be
rejected and require manual reconciliation. Automatic recovery is deliberately
limited until a server task-status/reconciliation endpoint is available.
