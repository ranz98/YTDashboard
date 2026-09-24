"""Apply the additive queue schema and run rollback-only queue diagnostics."""
import http.cookiejar
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    access = json.loads((ROOT/'data/admin-access.json').read_text())
    base = access['url']
    client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    html = client.open(base+'login.php', timeout=30).read().decode()
    csrf = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
    payload = urllib.parse.urlencode(dict(csrf=csrf,email=access['email'],password=access['password'])).encode()
    html = client.open(base+'login.php',data=payload,timeout=30).read().decode()
    csrf = re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)
    for action in ['operations_migrate','queue_checks']:
        request = urllib.request.Request(base+'api.php?action='+action,data=b'{}',headers={'Content-Type':'application/json','X-CSRF-Token':csrf})
        result = json.load(client.open(request, timeout=60))
        print(action+':', json.dumps(result))


if __name__ == '__main__':
    main()
