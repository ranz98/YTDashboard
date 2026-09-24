"""Register this Windows worker using the dashboard administrator account."""
import getpass
import http.cookiejar
import json
from pathlib import Path
import re
import secrets
import uuid
import urllib.parse
import urllib.request

from runner import save

BASE = Path(__file__).resolve().parent


def main():
    target = BASE / "config.json"
    if target.exists():
        print('Keeping existing config.json. Run start.cmd to start.')
        return
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
    name = 'windows-' + uuid.uuid4().hex[:12]
    request = urllib.request.Request(base + "api.php?action=worker_register",
        data=json.dumps({"name": name}).encode(),
        headers={"Content-Type": "application/json", "X-CSRF-Token": match.group(1)})
    result = json.load(client.open(request, timeout=20))
    config["token"] = result["token"]
    config['bridge_token'] = secrets.token_hex(32)
    command = ['{python}', '{base}/adapter.py', '{task}', '{result}']
    config['commands'] = {stage: command for stage in ['fetch', 'editor', 'uploader']}
    save(target, config)
    key = getpass.getpass('DeepSeek API key (Enter to keep existing key): ').strip()
    key_path = BASE.parents[1] / 'config/deepseek-key.txt'
    if key:
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_text(key, encoding='utf-8')
    pairing = BASE / 'data/PAIRING-KEY.txt'
    pairing.parent.mkdir(exist_ok=True)
    pairing.write_text(config['bridge_token'], encoding='utf-8')
    print('Setup complete. Paste the key from data/PAIRING-KEY.txt into the Chrome extension settings.')


if __name__ == "__main__":
    main()
