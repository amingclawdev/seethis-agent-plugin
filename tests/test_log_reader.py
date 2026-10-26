import copy
import json
from pathlib import Path
import tempfile
import unittest

from seethis_runs.log_reader import read_run

REF = "a" * 32


class FakeStore:
    def __init__(self, run): self.run = run
    def progress(self, ref): return [copy.deepcopy(self.run)] if ref == REF else []


class LogReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / "rollout.jsonl"
        self.events = [
            {"type": "session_meta", "payload": {"id": "session-a"}},
            {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "turn-a"}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Example\n你好 http://127.0.0.1:1234/r/" + REF + "b" * 96}]}},
            {"type": "event_msg", "payload": {"type": "user_message", "message": "Duplicate representation"}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Example answer"}]}},
            {"type": "response_item", "payload": {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "Do not display host instructions"}]}},
        ]
        raw = [json.dumps(dict(e, timestamp="2026-10-25T04:00:00Z")).encode() + b"\n" for e in self.events]
        self.path.write_bytes(b"".join(raw))
        self.run = {"run_id": "run-a", "session_id": "session-a", "turn_id": "turn-a", "start": {"locator": {"path": str(self.path), "byte": len(raw[0])}}, "reported_end": {"locator": {"path": str(self.path), "byte": self.path.stat().st_size}}, "inferred_end": None}

    def tearDown(self): self.tmp.cleanup()

    def read(self, ref=REF, run="run-a"):
        return read_run(ref, run, FakeStore(self.run), self.root)

    def test_roles_dedup_redaction_and_no_write(self):
        before = self.path.read_bytes(), self.path.stat().st_mtime_ns
        result = self.read()
        self.assertEqual([m["role"] for m in result["messages"]], ["user", "assistant"])
        self.assertIn("你好", result["messages"][0]["text"])
        self.assertNotIn("b" * 96, json.dumps(result))
        self.assertNotIn("host instructions", json.dumps(result))
        self.assertEqual(before, (self.path.read_bytes(), self.path.stat().st_mtime_ns))

    def test_unregistered_run_and_cross_reference_rejected(self):
        for ref, run in [(REF, "other"), ("c" * 32, "run-a")]:
            with self.assertRaisesRegex(ValueError, "run_not_registered"): self.read(ref, run)

    def test_wrong_session(self):
        self.run["session_id"] = "another"
        with self.assertRaisesRegex(ValueError, "session_mismatch"): self.read()

    def test_wrong_turn(self):
        self.run["turn_id"] = "another"
        with self.assertRaisesRegex(ValueError, "turn_anchor_mismatch"): self.read()

    def test_missing_end_never_falls_back(self):
        self.run["reported_end"]["locator"] = {}
        with self.assertRaisesRegex(ValueError, "end_location_missing"): self.read()

    def test_truncated_interval(self):
        self.path.write_bytes(self.path.read_bytes()[:-20])
        with self.assertRaisesRegex(ValueError, "interval_truncated"): self.read()

    def test_completed_partial_record(self):
        self.run["reported_end"]["locator"]["byte"] -= 2
        with self.assertRaisesRegex(ValueError, "partial_record"): self.read()

    def test_live_snapshot_is_not_completion(self):
        self.run["reported_end"] = None
        with self.path.open("ab") as out: out.write(b'{"unfinished":')
        result = self.read()
        self.assertTrue(result["interval"]["live_snapshot"])
        self.assertEqual(len(result["messages"]), 2)
        self.assertIsNone(self.run["reported_end"])

    def test_escape_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "outside.jsonl"; target.write_bytes(self.path.read_bytes())
            self.run["start"]["locator"]["path"] = str(target)
            with self.assertRaisesRegex(ValueError, "outside_sessions"): self.read()
            self.path.unlink(); self.path.symlink_to(target)
            self.run["start"]["locator"]["path"] = str(self.path)
            with self.assertRaisesRegex(ValueError, "outside_sessions"): self.read()

    def test_malformed_record_is_not_partial_success(self):
        raw = self.path.read_bytes().replace(b'"assistant"', b'!invalid!')
        self.path.write_bytes(raw); self.run["reported_end"]["locator"]["byte"] = len(raw)
        with self.assertRaises(ValueError): self.read()

    def test_original_cutoff_survives_later_messages(self):
        with self.path.open("ab") as out: out.write(b'{"type":"later"}\n')
        result = self.read()
        self.assertEqual(result["interval"]["end_byte"], self.run["reported_end"]["locator"]["byte"])
        self.assertFalse(result["interval"]["live_snapshot"])


if __name__ == "__main__": unittest.main()
