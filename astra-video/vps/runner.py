"""Windows queue runner. Stage commands exchange JSON files with this process."""
import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = Path(__file__).resolve().parent
LOG = logging.getLogger("astra")


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


class Runner:
    def __init__(self, config, directory=BASE):
        self.config = config
        self.client = Client(config)
        self.data = directory / "data"
        self.journal = self.data / "active.json"
        self.stop_file = directory / "STOP"

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
                process = subprocess.Popen(command, cwd=BASE, stdout=log, stderr=log,
                                           creationflags=subprocess.CREATE_NO_WINDOW)
                last_beat = 0
                while process.poll() is None:
                    if time.monotonic() - last_beat >= 15:
                        reply = self.client.call("heartbeat", id=task["id"], lease=task["lease"], progress=0)
                        last_beat = time.monotonic()
                        cancelled = bool(reply.get("stop_requested"))
                    if cancelled or self.stop_file.exists():
                        cancelled = True
                        stop_process(process)
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
            # Upload side effects may have happened before a crash or timeout.
            result = {"state": "needs_attention" if task["agent"] == "uploader" else "failed",
                      "reason": "Stage interrupted or returned invalid output; inspect the VPS log."}
            LOG.error("Task %s interrupted; its result is saved for acknowledgement", task["id"])
        if task["agent"] == "uploader" and result["state"] != "completed":
            result["state"] = "needs_attention"
        record.update(phase="complete", result=result)
        save(self.journal, record)
        self.deliver(record)

    def run(self):
        if self.journal.exists():
            record = read(self.journal)
            if record.get("phase") != "complete":
                raise RuntimeError("An interrupted claim or stage needs review. Do not delete data/active.json or rerun the video.")
            self.deliver(record)
        LOG.info("Runner ready: %s", ", ".join(self.config["commands"]))
        while not self.stop_file.exists():
            # A lost claim response must never lead to a second claim.
            save(self.journal, {"phase": "claiming"})
            response = self.client.call("claim")
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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), RotatingFileHandler(BASE / "data/runner.log", maxBytes=2_000_000, backupCount=3)])
    import msvcrt
    with (BASE / "data/runner.lock").open("a+b") as lock:
        lock.seek(0)
        lock.write(b"0")
        lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        Runner(config).run()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Never print HTTP bodies or task payloads containing private data.
        print("Runner stopped:", str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__)
        sys.exit(1)
