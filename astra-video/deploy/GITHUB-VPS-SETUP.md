# GitHub Actions → Windows VPS

Push trusted changes to `main` → GitHub packages tracked VPS code → SSH transfers
it → Astra finishes its current task → code is backed up and replaced → the open
`start.cmd` launcher restarts Astra. No pip installs and no Task Scheduler.

The deployment target is `C:\Astra\ASTRA\astra-video\vps`. It preserves
`config.json`, `data`, media, logs, keys, and the original editor. Hostinger is a
separate deployment. Original editor changes are never shipped by this workflow.

## One-time Windows VPS setup

1. While Astra is idle, close its launcher. Copy the latest `runner.py` and
   `start.cmd` into the VPS folder and run `start.cmd` again. These versions
   understand `DEPLOYING`, which lets active work finish before deployment.
2. Open PowerShell as Administrator and enable Windows OpenSSH Server:

   ```powershell
   Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
   Start-Service sshd
   Set-Service -Name sshd -StartupType Automatic
   Get-NetFirewallRule -Name OpenSSH-Server-In-TCP
   ```

   Allow your chosen SSH port in the VPS provider's firewall as well.
3. Generate a dedicated SSH key on your own computer with
   `ssh-keygen -t ed25519 -f astra-deploy`. Install **only the public key** on the
   VPS. For an Administrator account, the default Windows OpenSSH configuration
   uses `C:\ProgramData\ssh\administrators_authorized_keys`; preserve existing
   keys, and follow [Microsoft's key permissions instructions](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_keymanagement). For a regular
   account it uses that account's `.ssh\authorized_keys`.
4. Test key-based SSH from your computer. Use a Windows account that can write
   the Astra folder. The workflow does not start a GUI or Chrome over SSH.
5. Obtain the server host key and verify its fingerprint against the VPS's
   `C:\ProgramData\ssh\ssh_host_ed25519_key.pub`. Save the verified `known_hosts`
   entry, including `[hostname]:port` if using a non-default port.

## Repository configuration

In GitHub → Settings → Environments, create `windows-vps`. Restrict deployment
branches to `main`. Add these environment secrets:

| Secret | Value |
| --- | --- |
| `VPS_HOST` | VPS IP address or hostname |
| `VPS_USER` | Windows SSH username, e.g. Administrator |
| `VPS_SSH_PORT` | SSH port, normally 22 |
| `VPS_SSH_KEY` | Entire dedicated private key, including header and footer |
| `VPS_KNOWN_HOSTS` | Verified SSH host-key entry |

Never put credentials in the repository. This public repository uses a
GitHub-hosted runner, with no pull-request deployment trigger.
GitHub [warns against self-hosted runners on public repositories](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners).

Under Settings → Secrets and variables → Actions → Variables, add the repository
variable `VPS_DEPLOY_ENABLED` with value `true`. Until then deployment jobs skip.

Open Actions → Deploy Windows VPS → Run workflow → main. Once the first run
succeeds, relevant pushes to main deploy automatically. Dashboard-only edits do
not trigger VPS deployment.

## Runtime behavior

- Keep `start.cmd` open and Chrome signed in on the VPS desktop. SSH deployment
  does not sign a user into Windows or launch Chrome in a service session.
- A running task can drain for up to 30 minutes. A busy or unresolved task makes
  deployment fail without replacing code. Retry the workflow when it is idle.
- Extension files are copied, but unpacked Chrome extensions still need **Reload**
  in `chrome://extensions` after an update. Do this while no task is running.
- Code backups and a revision manifest are in `data\deployments`. A copy failure
  rolls changed code back automatically; configuration and media are never copied.
- If a machine or deployment process crashes while `DEPLOYING` exists, Astra
  waits. Inspect the deployment log and backup before removing that marker.
- Incoming release archives remain in the SSH user's `astra-incoming` folder.
