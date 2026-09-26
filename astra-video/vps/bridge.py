"""Authenticated loopback mailbox for the Chrome extension."""
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import socket
import threading
import time

from runner import read, save


class ExclusiveServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Bridge:
    def __init__(self, base, token, port=18765):
        self.base, self.token = Path(base), token
        self.seen = 0
        self.lock = threading.Lock()
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, code, value):
                self.send_response(code)
                origin = self.headers.get('Origin', '')
                if re.fullmatch(r'chrome-extension://[a-p]{32}', origin):
                    self.send_header('Access-Control-Allow-Origin', origin)
                    self.send_header('Vary', 'Origin')
                self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
                self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(value).encode())

            def do_OPTIONS(self):
                self.reply(204, {})

            def authorized(self):
                return hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + bridge.token)

            def do_GET(self):
                if not self.authorized():
                    return self.reply(401, {'error': 'Pair the extension first.'})
                if self.path != '/command':
                    return self.reply(404, {})
                with bridge.lock:
                    bridge.seen = time.monotonic()
                    path = bridge.base / 'data/browser-command.json'
                    command = read(path) if path.exists() else None
                    self.reply(200, {'command': command})

            def do_POST(self):
                if not self.authorized():
                    return self.reply(401, {})
                try:
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size <= 65536 or self.path not in ('/result', '/progress'):
                        return self.reply(400, {})
                    value = json.loads(self.rfile.read(size))
                    with bridge.lock:
                        path = bridge.base / 'data/browser-command.json'
                        command = read(path) if path.exists() else None
                        if not command or value.get('id') != command['id']:
                            return self.reply(409, {'error': 'Command no longer active.'})
                        if self.path == '/progress':
                            if value.get('step') not in ('opening', 'channel', 'dialog', 'file', 'details', 'next', 'visibility', 'processing', 'publish', 'confirmation'):
                                return self.reply(400, {})
                            save(bridge.base / 'data/browser-progress.json', {'id': command['id'], 'step': value['step']})
                        else:
                            save(bridge.base / 'data/browser-result.json', value)
                    self.reply(200, {'ok': True})
                except (ValueError, KeyError):
                    self.reply(400, {})

        try:
            self.server = ExclusiveServer(('127.0.0.1', port), Handler)
        except OSError as error:
            raise RuntimeError(f'Astra cannot bind to 127.0.0.1:{port}. Another process may be using it; close the other Astra runner and retry.') from error

    def start(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def ready(self):
        return time.monotonic() - self.seen < 75

    def cancel(self):
        path = self.base / 'data/browser-command.json'
        with self.lock:
            if not path.exists():
                return
            command = read(path)
            result = self.base / 'data/browser-result.json'
            if result.exists() and read(result).get('id') == command['id']:
                path.unlink()
                return
            command['cancel'] = True
            save(path, command)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if result.exists() and read(result).get('id') == command['id']:
                path.unlink(missing_ok=True)
                return
            time.sleep(1)
        raise RuntimeError('Chrome has not acknowledged stop. Lease retained; inspect the browser before recovery.')

    def close(self):
        self.server.shutdown()
        self.server.server_close()
