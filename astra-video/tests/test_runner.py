"""Offline runner checks; no live claims or uploads."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parents[1] / "vps/runner.py"
spec = importlib.util.spec_from_file_location("runner", SOURCE)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class RunnerTests(unittest.TestCase):
    def test_busy_instance_does_not_enter_runner(self):
        fake = Mock()
        fake.locking.side_effect = PermissionError(13, 'Locked')
        with tempfile.TemporaryDirectory() as temp, patch.dict(runner.sys.modules, {'msvcrt': fake}):
            with self.assertRaises(runner.InstanceBusy):
                with runner.instance_lock(Path(temp) / 'runner.lock'):
                    self.fail('A second runner entered the lock')

    def test_instance_unlocks_after_failure(self):
        fake = Mock()
        with tempfile.TemporaryDirectory() as temp, patch.dict(runner.sys.modules, {'msvcrt': fake}):
            with self.assertRaises(ValueError):
                with runner.instance_lock(Path(temp) / 'runner.lock'):
                    raise ValueError('Startup failed')
        self.assertEqual(fake.locking.call_count, 2)
        self.assertEqual(fake.locking.call_args.args[1], fake.LK_UNLCK)

    def test_permission_error_names_the_file(self):
        message = runner.failure_message(PermissionError(13, 'Denied', 'data/runner.log'))
        self.assertIn('data/runner.log', message)
        self.assertIn('Access denied', message)

    def test_editor_limits_leave_cpu_headroom(self):
        for cpus, expected in [(1, '1'), (2, '1'), (4, '2'), (16, '2')]:
            with patch.object(runner.os, 'cpu_count', return_value=cpus):
                environment = runner.editor_environment({})
                self.assertEqual(environment['ASTRA_FFMPEG_THREADS'], expected)
                self.assertEqual(environment['OPENBLAS_NUM_THREADS'], expected)

    def test_editor_cannot_request_unbounded_threads(self):
        with patch.object(runner.os, 'cpu_count', return_value=4):
            self.assertEqual(runner.editor_environment({'editor_threads': 0})['ASTRA_FFMPEG_THREADS'], '1')
            self.assertEqual(runner.editor_environment({'editor_threads': 100})['ASTRA_FFMPEG_THREADS'], '2')

    def config(self):
        return {"url": "https://example.com/astra/", "token": "a" * 64,
                "bridge_token": "b" * 64,
                "commands": {"editor": ["python", "adapter.py"]}}

    def test_empty_capabilities_rejected(self):
        config = self.config()
        config["commands"] = {}
        with self.assertRaises(ValueError):
            runner.validate(config)

    def test_http_rejected(self):
        config = self.config()
        config["url"] = "http://example.com"
        with self.assertRaises(ValueError):
            runner.validate(config)

    def test_unknown_stage_rejected(self):
        config = self.config()
        config["commands"] = {"publish": ["something"]}
        with self.assertRaises(ValueError):
            runner.validate(config)

    def test_uncertain_claim_never_reclaimed(self):
        with tempfile.TemporaryDirectory() as temp:
            worker = runner.Runner(self.config(), Path(temp))
            worker.client = Mock()
            runner.save(worker.journal, {"phase": "claiming"})
            with self.assertRaises(RuntimeError):
                worker.run()
            worker.client.call.assert_called_once_with('recover_claim')

    def test_old_lost_claim_recovers_only_when_server_slot_is_clear(self):
        with tempfile.TemporaryDirectory() as temp:
            worker = runner.Runner(self.config(), Path(temp))
            worker.client = Mock()
            worker.client.call.return_value = {'clear': True}
            runner.save(worker.journal, {'phase': 'claiming'})
            worker.stop_file.touch()
            worker.run()
            self.assertFalse(worker.journal.exists())

    def test_network_retry_preserves_claim_receipt(self):
        client = runner.Client(self.config())
        client.request = Mock(side_effect=[runner.urllib.error.URLError('offline'), {'task': None}])
        with patch.object(runner.time, 'sleep') as sleep:
            self.assertEqual(client.call('claim', claim_lease='c'*64), {'task': None})
        self.assertEqual(client.request.call_args_list[0], client.request.call_args_list[1])
        sleep.assert_called_once_with(5)

    def test_auth_errors_do_not_retry(self):
        client = runner.Client(self.config())
        client.request = Mock(side_effect=runner.urllib.error.HTTPError('url', 401, 'Unauthorized', {}, None))
        with self.assertRaises(runner.urllib.error.HTTPError):
            client.call('claim', claim_lease='c'*64)
        self.assertEqual(client.request.call_count, 1)

    def test_failed_delivery_preserves_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            worker = runner.Runner(self.config(), Path(temp))
            worker.client = Mock()
            worker.client.call.side_effect = OSError("Offline")
            record = {"phase": "complete", "task": {"id": 7, "lease": "private"},
                      "result": {"state": "completed", "render_verified": True, "title": "Done"}}
            runner.save(worker.journal, record)
            with self.assertRaises(OSError):
                worker.deliver(record)
            self.assertEqual(runner.read(worker.journal), record)

    def test_successful_delivery_clears_lease(self):
        with tempfile.TemporaryDirectory() as temp:
            worker = runner.Runner(self.config(), Path(temp))
            worker.client = Mock()
            record = {"task": {"id": 7, "lease": "private"},
                      "result": {"state": "failed", "reason": "Test"}}
            runner.save(worker.journal, record)
            worker.deliver(record)
            self.assertFalse(worker.journal.exists())
            self.assertNotIn("lease", runner.read(worker.data / "last-completed.json"))


if __name__ == "__main__":
    unittest.main()
