"""Windows queue runner. Stage commands exchange JSON files with this process."""
import argparse
from contextlib import contextmanager
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import secrets
import http.client
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = Path(__file__).resolve().parent
LOG = logging.getLogger("astra")


class InstanceBusy(RuntimeError):
    pass


@contextmanager
def instance_lock(path):
    import msvcrt
    # Lock before opening the shared log, which may otherwise fail during rotation.
    with path.open('a+b') as lock:
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise InstanceBusy('Cannot acquire ' + str(path) + '. Another Astra runner may already be open. '
                               'Close the extra launcher; do not delete the lock or active.json.') from error
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def failure_message(error):
    if isinstance(error, PermissionError):
        target = str(error.filename or 'a Windows resource (no path reported)')
        code = getattr(error, 'winerror', None) or error.errno
        return 'Access denied: ' + target + ' (error ' + str(code) + '). Check folder permissions and other running Astra instances.'
    return str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("Worker endpoint redirected; check the configured URL.")


class Client:
    def __init__(self, config):
        self.config = config
        self.opener = urllib.request.build_opener(NoRedirect())

    def call(self, action, **values):
        delay = 5
        while True:
            try:
                return self.request(action, **values)
            except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException) as error:
                if isinstance(error, urllib.error.HTTPError) and error.code not in (408, 429, 500, 502, 503, 504):
                    raise
                if action == 'heartbeat':
                    raise
                LOG.warning('Dashboard unavailable (%s); reconnecting in %ss', type(error).__name__, delay)
                time.sleep(delay)
                delay = min(60, delay * 2)

    def request(self, action, **values):
        body = dict(values, action=action, version="windows-1.0",
                    capabilities=list(self.config["commands"]))
        request = urllib.request.Request(
            self.config["url"].rstrip("/") + "/worker.php",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.config["token"]})
        with self.opener.open(request, timeout=20) as response:
            return json.load(response)


def validate(config):
    if urllib.parse.urlsplit(config.get("url", "")).scheme != "https":
        raise ValueError("An HTTPS dashboard URL is required.")
    token = config.get("token", "")
    if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
        raise ValueError("Set the worker token in config.json.")
    bridge_token = config.get('bridge_token', '')
    if len(bridge_token) != 64 or any(c not in '0123456789abcdef' for c in bridge_token):
        raise ValueError('Run setup.py to create the local Chrome pairing key.')
    commands = config.get("commands", {})
    if not commands:
        raise ValueError("No stage adapters configured. See README.md before enabling stages.")
    for stage, command in commands.items():
        if stage not in ("fetch", "editor", "uploader") or not isinstance(command, list) or not command:
            raise ValueError("Each stage command must be a nonempty JSON argument array.")
        if not all(isinstance(arg, str) for arg in command):
            raise ValueError("Stage command arguments must be strings.")


def stop_process(process):
    if process.poll() is None:
        # Stop ffmpeg and other children before releasing the server lease.
        result = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode != 0 and process.poll() is None:
            raise RuntimeError("Could not stop the stage process; keeping its lease.")
        process.wait(timeout=20)


def editor_environment(config):
    environment = os.environ.copy()
    default = max(1, min(2, (os.cpu_count() or 2) - 1))
    threads = max(1, min(default, int(config.get('editor_threads', default))))
    for name in ('ASTRA_FFMPEG_THREADS', 'OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
        environment[name] = str(threads)
    return environment


class Runner:
    def __init__(self, config, directory=BASE):
        self.config = config
        self.client = Client(config)
        self.data = directory / "data"
        self.journal = self.data / "active.json"
        self.stop_file = directory / "STOP"
        self.bridge = None

    def deliver(self, record):
        task = record["task"]
        self.client.call("complete", **record["result"], id=task["id"], lease=task["lease"])
        save(self.data / "last-completed.json", {"id": task["id"], "state": record["result"]["state"]})
        self.journal.unlink()
        LOG.info("Task %s acknowledged", task["id"])

    def execute(self, task):
        work = self.data / "tasks" / str(task["id"])
        work.mkdir(parents=True, exist_ok=True)
        request, output = work / "request.json", work / "result.json"
        record = {"task": task, "phase": "running"}
        save(self.journal, record)
        save(request, task)
        output.unlink(missing_ok=True)
        substitutions = {"{python}": sys.executable, "{task}": str(request),
                         "{result}": str(output), "{base}": str(BASE)}
        command = self.config["commands"][task["agent"]]
        for key, value in substitutions.items():
            command = [arg.replace(key, value) for arg in command]
        process = None
        cancelled = False
        started = time.monotonic()
        try:
            with (work / "stage.log").open("ab", buffering=0) as log:
                is_editor = task['agent'] == 'editor'
                flags = subprocess.CREATE_NO_WINDOW
                if is_editor:
                    flags |= subprocess.BELOW_NORMAL_PRIORITY_CLASS
                process = subprocess.Popen(command, cwd=BASE, stdout=log, stderr=log,
                                           env=editor_environment(self.config) if is_editor else None,
                                           creationflags=flags)
                last_beat = 0
                while process.poll() is None:
                    if time.monotonic() - last_beat >= 15:
                        status_path = work / 'progress.json'
                        status = read(status_path) if status_path.exists() else {}
                        try:
                            reply = self.client.call("heartbeat", id=task["id"], lease=task["lease"],
                                                     progress=status.get('progress', 0), message=status.get('message', ''))
                        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException) as error:
                            if isinstance(error, urllib.error.HTTPError) and error.code not in (408, 429, 500, 502, 503, 504):
                                raise
                            LOG.warning('Heartbeat unavailable; keeping task %s and its execution slot', task['id'])
                            reply = {}
                        last_beat = time.monotonic()
                        cancelled = bool(reply.get("stop_requested"))
                    if cancelled or self.stop_file.exists():
                        cancelled = True
                        stop_process(process)
                        if self.bridge:
                            self.bridge.cancel()
                        break
                    if time.monotonic() - started > self.config.get("stage_timeout_seconds", 7200):
                        raise TimeoutError("Stage time limit reached")
                    time.sleep(1)
            if cancelled:
                result = {"state": "cancelled", "reason": "Worker acknowledged stop."}
            elif process.returncode != 0:
                result = {"state": "failed", "reason": "Stage process failed; inspect the private VPS stage log."}
            else:
                result = read(output)
                if result.get("state") not in ("completed", "failed", "skipped", "cancelled", "needs_attention"):
                    raise ValueError("Stage returned an invalid state")
                if "id" in result or "lease" in result:
                    raise ValueError("Stage must not override task ownership")
        except BaseException:
            if process is not None:
                stop_process(process)
            if self.bridge:
                self.bridge.cancel()
            # Upload side effects may have happened before a crash or timeout.
            result = {"state": "needs_attention" if task["agent"] == "uploader" else "failed",
                      "reason": "Stage interrupted or returned invalid output; inspect the VPS log."}
            LOG.error("Task %s interrupted; its result is saved for acknowledgement", task["id"])
        if task["agent"] == "uploader" and result["state"] != "completed":
            result["state"] = "needs_attention"
        if self.bridge:
            self.bridge.cancel()
        record.update(phase="complete", result=result)
        save(self.journal, record)
        self.deliver(record)

    def run(self):
        if self.journal.exists():
            record = read(self.journal)
            if record.get('phase') == 'claiming' and record.get('claim_lease'):
                response = self.client.call('claim', claim_lease=record['claim_lease'])
                if response.get('task'):
                    self.execute(response['task'])
                else:
                    self.journal.unlink()
            elif record.get('phase') == 'claiming' and self.client.call('recover_claim').get('clear') is True:
                self.journal.unlink()
            elif record.get("phase") != "complete":
                raise RuntimeError("An interrupted claim or stage needs review. Do not delete data/active.json or rerun the video.")
            else:
                self.deliver(record)
        LOG.info("Runner ready: %s", ", ".join(self.config["commands"]))
        while not self.stop_file.exists():
            if self.bridge and not self.bridge.ready():
                time.sleep(2)
                continue
            # A lost claim response must never lead to a second claim.
            claim_lease = secrets.token_hex(32)
            save(self.journal, {"phase": "claiming", "claim_lease": claim_lease})
            response = self.client.call("claim", claim_lease=claim_lease)
            task = response.get("task")
            if task:
                LOG.info("Starting task %s (%s)", task["id"], task["agent"])
                self.execute(task)
            else:
                self.journal.unlink()
                for _ in range(15):
                    if self.stop_file.exists():
                        break
                    time.sleep(1)
        LOG.info("Runner stopped")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if os.name != "nt":
        raise RuntimeError("This package requires Windows.")
    config = read(BASE / "config.json")
    validate(config)
    if args.check:
        print("Configuration valid. No task claimed and no video uploaded.")
        return
    (BASE / "data").mkdir(exist_ok=True)
    with instance_lock(BASE / 'data/runner.lock'):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
            logging.StreamHandler(), RotatingFileHandler(BASE / "data/runner.log", maxBytes=2_000_000, backupCount=3)])
        from bridge import Bridge
        bridge = Bridge(BASE, config['bridge_token'])
        bridge.start()
        try:
            worker = Runner(config)
            worker.bridge = bridge
            LOG.info('Waiting for the paired Chrome extension on this computer')
            worker.run()
        finally:
            bridge.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Never print HTTP bodies or task payloads containing private data.
        print("Runner stopped:", failure_message(error))
        sys.exit(2 if isinstance(error, (InstanceBusy, PermissionError)) else 1)
