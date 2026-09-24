"""Complete the one-time HTTPS installer. Database password is prompted."""
import getpass
import http.cookiejar
import json
from pathlib import Path
import re
import secrets
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://lightblue-mantis-659122.hostingersite.com/astra/'


def main():
    jar = http.cookiejar.CookieJar()
    client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    health = json.load(client.open(BASE+'api.php?action=health', timeout=30))
    if health['installed']:
        print('Already installed; configuration left unchanged.')
        return
    bootstrap = (ROOT/'dashboard/public/private/bootstrap.php').read_text()
    token = re.search(r"'setup_token'\s*=>\s*'([^']+)'", bootstrap).group(1)
    html = client.open(BASE+'setup.php', timeout=30).read().decode()
    csrf = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
    password = getpass.getpass('Database password: ')
    admin = {'url':BASE, 'email':'admin@astra.local', 'password':secrets.token_urlsafe(22)}
    private = ROOT/'data'
    private.mkdir(exist_ok=True)
    (private/'admin-access.json').write_text(json.dumps(admin,indent=2), encoding='utf-8')
    payload = dict(setup_token=token, csrf=csrf, db_host='localhost',
                   db_name='u518245900_ytauto', db_user='u518245900_ytauto',
                   db_password=password, email=admin['email'], password=admin['password'])
    request = urllib.request.Request(BASE+'setup.php',data=urllib.parse.urlencode(payload).encode())
    response = client.open(request,timeout=45)
    html = response.read().decode()
    if 'csrf-token' not in html:
        error = re.search(r'<p class="error">(.*?)</p>',html)
        raise RuntimeError(error.group(1) if error else 'Installation did not complete.')
    (private/'ADMIN-ACCESS.txt').write_text(
        'ASTRA VIDEO — ADMIN ACCESS\n\nDashboard: '+BASE+'\nEmail: '+admin['email']+
        '\nPassword: '+admin['password']+'\n\nChange the password in Settings after signing in.\n'
        'This file is local only and is never uploaded by the deployment script.\n', encoding='utf-8')
    print('MySQL configured; admin created; installer locked.')
    print('Access details saved locally:', private/'ADMIN-ACCESS.txt')


if __name__=='__main__':
    main()
