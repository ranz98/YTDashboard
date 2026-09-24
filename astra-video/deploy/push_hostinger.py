"""Deploy via verified FTPS. Passwords are prompted, never saved in source.

python deploy/push_hostinger.py --inspect
python deploy/push_hostinger.py
"""
import argparse
import ftplib
import getpass
import hashlib
import io
import json
from pathlib import Path
import posixpath
import ssl
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def ensure_dir(ftp, path):
    for part in path.strip('/').split('/'):
        try:
            ftp.cwd(part)
        except ftplib.error_perm:
            ftp.mkd(part)
            ftp.cwd(part)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host', default='31.170.167.1')
    p.add_argument('--tls-name', default='hstgr.io', help='Expected Hostinger FTPS certificate identity')
    p.add_argument('--user', default='u518245900.lightblue-mantis-659122.hostingersite.com')
    p.add_argument('--remote', default='/public_html/astra')
    p.add_argument('--inspect', action='store_true')
    p.add_argument('--root-redirect', action='store_true', help='Make the main website address open /astra/')
    args = p.parse_args()
    if not args.remote.startswith('/public_html/') or '..' in args.remote.split('/'):
        p.error('Destination must be a subdirectory of /public_html')
    password = getpass.getpass('FTP password: ')
    context = ssl.create_default_context()
    with ftplib.FTP_TLS(context=context, timeout=45) as ftp:
        ftp.connect(args.host, 21)
        # Hostinger's FTP endpoint uses its provider certificate, not the IP.
        # Keep CA/hostname validation enabled for both control and data sockets.
        ftp.host = args.tls_name
        ftp.login(args.user, password)
        ftp.prot_p()
        del password
        print('Connected using verified FTPS; current directory:', ftp.pwd())
        if args.inspect:
            print('\n'.join(ftp.nlst()))
            return
        source = ROOT / 'dashboard' / 'public'
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        backup = ROOT / 'data' / 'deployment-backups' / stamp
        manifest = []
        files = [(local, local.relative_to(source).as_posix()) for local in sorted(source.rglob('*'))]
        if args.root_redirect:
            files.append((ROOT / 'deploy/site-root/index.php', '../index.php'))
        for local, relative in files:
            if not local.is_file() or '__pycache__' in local.parts:
                continue
            if relative == 'private/config.php':
                continue
            remote = '/public_html/index.php' if relative == '../index.php' else posixpath.join(args.remote, relative)
            ftp.cwd('/')
            ensure_dir(ftp, posixpath.dirname(remote))
            name = posixpath.basename(remote)
            existing = io.BytesIO()
            try:
                ftp.retrbinary('RETR ' + name, existing.write)
                found = True
            except ftplib.error_perm as error:
                if not str(error).startswith('550'):
                    raise
                found = False
            # An existing installation keeps its original setup identity.
            if relative == 'private/bootstrap.php' and found:
                print('Preserved setup identity')
                continue
            payload = local.read_bytes()
            if found and payload == existing.getvalue():
                continue
            if found:
                saved = backup / ('site-root/index.php' if relative == '../index.php' else relative)
                saved.parent.mkdir(parents=True, exist_ok=True)
                saved.write_bytes(existing.getvalue())
            temporary = '.' + name + '.upload-' + stamp
            ftp.storbinary('STOR ' + temporary, io.BytesIO(payload))
            verify = io.BytesIO()
            ftp.retrbinary('RETR ' + temporary, verify.write)
            if verify.getvalue() != payload:
                raise RuntimeError('Verification failed: ' + relative)
            ftp.rename(temporary, name)
            manifest.append({'file': relative, 'sha256': hashlib.sha256(payload).hexdigest()})
            print('Uploaded and verified:', relative)
        backup.mkdir(parents=True, exist_ok=True)
        (backup / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        print('Deployment complete. Manifest:', backup / 'manifest.json')


if __name__ == '__main__':
    main()
