"""Offline runner checks; no live claims or uploads."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

SOURCE = Path(__file__).resolve().parents[1] / "vps/runner.py"
spec = importlib.util.spec_from_file_location("runner", SOURCE)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class RunnerTests(unittest.TestCase):
    def config(self):
        return {"url": "https://example.com/astra/", "token": "a" * 64,
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
            worker.client.call.assert_not_called()

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
