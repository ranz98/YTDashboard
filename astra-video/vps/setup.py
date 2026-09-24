"""Register this Windows worker using the dashboard administrator account."""
import getpass
import http.cookiejar
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request

from runner import save

BASE = Path(__file__).resolve().parent


def main():
    target = BASE / "config.json"
    if target.exists():
        raise SystemExit("config.json already exists. Keep its token; edit the file to configure stages.")
    config = json.loads((BASE / "config.example.json").read_text())
    base = config["url"]
    client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    html = client.open(base + "login.php", timeout=20).read().decode()
    csrf = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
    email = input("Dashboard admin email: ").strip()
    password = getpass.getpass("Dashboard admin password: ")
    body = urllib.parse.urlencode(dict(csrf=csrf, email=email, password=password)).encode()
    html = client.open(base + "login.php", data=body, timeout=20).read().decode()
    match = re.search(r'name="csrf-token" content="([^"]+)"', html)
    if not match:
        raise SystemExit("Sign-in failed. No config written.")
    name = input("Unique worker name [windows-vps-1]: ").strip() or "windows-vps-1"
    request = urllib.request.Request(base + "api.php?action=worker_register",
        data=json.dumps({"name": name}).encode(),
        headers={"Content-Type": "application/json", "X-CSRF-Token": match.group(1)})
    result = json.load(client.open(request, timeout=20))
    config["token"] = result["token"]
    save(target, config)
    print("Private config.json saved. Configure stage adapters before starting the runner.")


if __name__ == "__main__":
    main()
