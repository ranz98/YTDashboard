"""Offline integration checks for the browser mailbox and media adapters."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'vps'))
import adapter
from bridge import Bridge
from runner import read, save


class MailboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.bridge = Bridge(self.base, 'a' * 64, port=0)
        self.bridge.start()
        self.url = 'http://127.0.0.1:' + str(self.bridge.server.server_port)

    def tearDown(self):
        self.bridge.close()
        self.temp.cleanup()

    def call(self, path, body=None, token='a' * 64):
        request = urllib.request.Request(self.url + path,
            data=json.dumps(body).encode() if body else None,
            headers={'Authorization': 'Bearer ' + token})
        return json.load(urllib.request.urlopen(request, timeout=3))

    def test_pairing_required(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.call('/command', token='wrong')
        self.assertEqual(caught.exception.code, 401)
        self.assertFalse(self.bridge.ready())

    def test_mailbox_roundtrip_and_stale_result(self):
        save(self.base / 'data/browser-command.json', {'id': 'one', 'action': 'fetch'})
        self.assertEqual(self.call('/command')['command']['id'], 'one')
        self.assertTrue(self.bridge.ready())
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.call('/result', {'id': 'old', 'ok': True})
        self.assertEqual(caught.exception.code, 409)
        self.call('/result', {'id': 'one', 'ok': True, 'videos': []})
        self.assertTrue(read(self.base / 'data/browser-result.json')['ok'])

    def test_stop_waits_for_browser_acknowledgement(self):
        request = self.base / 'data/browser-command.json'
        save(request, {'id': 'one', 'action': 'upload'})
        finished = threading.Event()
        def cancel():
            self.bridge.cancel()
            finished.set()
        thread = threading.Thread(target=cancel)
        thread.start()
        deadline = time.monotonic() + 3
        while not read(request).get('cancel') and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(read(request)['cancel'])
        self.assertFalse(finished.is_set())
        self.call('/result', {'id': 'one', 'ok': False, 'error': 'Stopped'})
        thread.join(3)
        self.assertTrue(finished.is_set())
        self.assertFalse(request.exists())


class AdapterTests(unittest.TestCase):
    def test_media_path_rejects_traversal(self):
        with self.assertRaises(ValueError):
            adapter.folder_for({'channel_id': 1}, '../outside')

    def test_duplicate_scan_never_downloads(self):
        task = {'channel_id': 1, 'channel': {'handle': '@Example'}, 'known_video_ids': ['abcdefghijk']}
        with tempfile.TemporaryDirectory() as temp, patch.object(adapter, 'BASE', Path(temp)), \
                patch.object(adapter, 'browser', return_value={'videos': [{'id': 'abcdefghijk', 'title': 'Known'}]}), \
                patch.object(adapter, 'run') as run:
            result = adapter.fetch(task, Path(temp) / 'request.json')
            run.assert_not_called()
            self.assertFalse(result['videos'][0]['downloaded'])

    def test_scan_cannot_exceed_five(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(adapter, 'browser', return_value={'videos': [{}] * 6}):
            with self.assertRaises(ValueError):
                adapter.fetch({'channel': {'handle': '@Example'}}, Path(temp) / 'request.json')

    def test_upload_rejects_changed_title(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(adapter, 'BASE', Path(temp)), \
                patch.object(adapter, 'verify', return_value=12), patch.object(adapter, 'browser') as browser:
            task = {'channel_id': 1, 'video': {'source_video_id': 'abcdefghijk', 'title': 'Changed'}}
            folder = adapter.folder_for(task, 'abcdefghijk')
            save(folder / 'ready.json', {'title': 'Original'})
            with self.assertRaises(RuntimeError):
                adapter.upload(task, Path(temp) / 'request.json')
            browser.assert_not_called()

    def test_upload_requires_publication_evidence(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(adapter, 'BASE', Path(temp)), \
                patch.object(adapter, 'verify', return_value=12), \
                patch.object(adapter, 'browser', return_value={'ok': True}):
            task = {'channel_id': 1, 'channel': {'destination': 'UC' + 'x' * 22},
                    'video': {'source_video_id': 'abcdefghijk', 'title': 'Title'}}
            folder = adapter.folder_for(task, 'abcdefghijk')
            save(folder / 'ready.json', {'title': 'Title'})
            with self.assertRaises(RuntimeError):
                adapter.upload(task, Path(temp) / 'request.json')
            self.assertFalse((folder / 'published.json').exists())


if __name__ == '__main__':
    unittest.main()
