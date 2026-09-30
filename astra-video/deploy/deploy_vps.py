"""Apply a code-only release after the Windows runner drains its active task."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import time
import zipfile


def allowed(name):
    path = PurePosixPath(name)
    return (not path.is_absolute() and '..' not in path.parts and '\\' not in name and ':' not in name and
            ((len(path.parts) == 1 and (path.suffix in ('.py', '.cmd', '.ps1', '.md') or
                                      name in ('requirements.txt', 'config.example.json'))) or
             (len(path.parts) == 2 and path.parts[0] == 'extension' and path.suffix in ('.js', '.json', '.html', '.css'))))


@contextmanager
def idle_lock(target, timeout):
    import msvcrt
    lock_path = target / 'data/runner.lock'
    lock_path.parent.mkdir(exist_ok=True)
    with lock_path.open('a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Runner is still busy. No files changed; retry after the task finishes.')
                time.sleep(5)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def deploy(archive, target, revision, timeout):
    if os.name != 'nt':
        raise RuntimeError('Deploy on the Windows VPS.')
    if not (target / 'config.json').is_file():
        raise RuntimeError('Destination is not an installed Astra VPS folder.')
    if (target / 'DEPLOYING').exists():
        raise RuntimeError('An earlier deployment marker exists. Review it before retrying.')
    if not (target / 'runner.py').is_file() or 'DEPLOYING' not in (target / 'runner.py').read_text(encoding='utf-8'):
        raise RuntimeError('One-time setup: copy the new runner.py and start.cmd while Astra is stopped, then restart Astra.')
    with tempfile.TemporaryDirectory(prefix='astra-release-') as temporary:
        staging = Path(temporary)
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
            if not names or len(names) != len(set(names)) or not all(allowed(name) for name in names):
                raise RuntimeError('Release contains an unsupported path.')
            if any(target not in (target / name).resolve().parents for name in names):
                raise RuntimeError('A deployment path points outside the Astra folder.')
            for name in names:
                data = bundle.read(name)
                if name.endswith('.py'):
                    compile(data, name, 'exec')
                destination = staging / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
        marker = target / 'DEPLOYING'
        marker.write_text(revision, encoding='utf-8')
        keep_marker = False
        try:
            with idle_lock(target, timeout):
                if (target / 'data/active.json').exists() or (target / 'data/browser-command.json').exists():
                    raise RuntimeError('Unresolved local work remains. Deployment stopped without changing files.')
                backup = target / 'data/deployments' / (time.strftime('%Y%m%d-%H%M%S') + '-' + revision[:12])
                backup.mkdir(parents=True)
                changed = []
                try:
                    for name in names:
                        destination = target / name
                        if destination.exists() and destination.read_bytes() == (staging / name).read_bytes():
                            continue
                        existed = destination.exists()
                        if existed:
                            saved = backup / name
                            saved.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(destination, saved)
                        changed.append((name, existed))
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(staging / name, destination)
                        if hashlib.sha256(destination.read_bytes()).digest() != hashlib.sha256((staging / name).read_bytes()).digest():
                            raise RuntimeError('File transfer verification failed: ' + name)
                except BaseException:
                    # Keep the runner stopped if restoring a backup fails.
                    keep_marker = True
                    for name, existed in reversed(changed):
                        if existed:
                            shutil.copy2(backup / name, target / name)
                        else:
                            (target / name).unlink(missing_ok=True)
                    keep_marker = False
                    raise
                (backup / 'manifest.json').write_text(json.dumps({'revision': revision, 'changed': changed}), encoding='utf-8')
                print('Deployed ' + revision + '; ' + str(len(changed)) + ' files updated.')
                if any(name.startswith('extension/') for name, _ in changed):
                    print('Chrome extension files changed: reload Astra in chrome://extensions when idle.')
        finally:
            if not keep_marker:
                marker.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--target', default=r'C:\Astra\ASTRA\astra-video\vps', type=Path)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--timeout', default=1800, type=int)
    args = parser.parse_args()
    deploy(args.archive, args.target.resolve(), args.revision, args.timeout)
