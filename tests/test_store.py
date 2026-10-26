import fcntl
import json
import os
from pathlib import Path
import tempfile
import unittest

from seethis_runs.store import Store, references_in_prompt


REF = "0123456789abcdef0123456789abcdef"


class RunStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "private/runs.json"
        self.store = Store(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def start(self, session="session-a", turn="turn-a"):
        self.store.start([REF], session, turn)

    def test_prompt_only_reference_id_survives(self):
        prompt = "PRIVATE-PROMPT http://127.0.0.1:12345/r/" + REF + "a" * 96
        refs = references_in_prompt(prompt)
        self.assertEqual(refs, [REF])
        self.store.start(refs, "s", "t")
        raw = self.path.read_text()
        self.assertNotIn("PRIVATE-PROMPT", raw)
        self.assertNotIn("a" * 96, raw)
        self.assertNotIn("http:", raw)
        self.assertEqual(references_in_prompt("https://example.org/r/" + REF), [])

    def test_replayed_hook_deduplicates_but_new_handin_adds(self):
        self.start(); self.start(); self.start(turn="turn-b")
        self.assertEqual(len(self.store.progress(REF)), 2)

    def test_stop_is_not_done(self):
        self.start()
        self.store.infer("session-a", "turn-a", "Stop")
        self.assertEqual(self.store.progress(REF)[0]["status"], "stopped-without-end")

    def test_interrupt_then_session_end_keeps_actual_event(self):
        self.start()
        self.store.infer("session-a", "turn-a", "Interrupt")
        self.store.infer("session-a", None, "SessionEnd")
        self.assertEqual(self.store.progress(REF)[0]["inferred_end"]["event"], "Interrupt")

    def test_reported_end_supersedes_inference_without_deleting_it(self):
        self.start()
        self.store.infer("session-a", "turn-a", "Stop")
        run = self.store.end(REF, "session-a", "done", "Work completed.")
        self.assertEqual(run["status"], "done")
        self.assertEqual(run["status_source"], "agent")
        self.assertEqual(run["inferred_end"]["status"], "stopped-without-end")

    def test_explicit_end_survives_hooks_and_retry(self):
        self.start()
        first = self.store.end(REF, "session-a", "blocked", "Waiting for input.")
        self.store.infer("session-a", "turn-a", "Stop")
        self.assertEqual(self.store.end(REF, "session-a", "blocked", "Waiting for input."), first)
        with self.assertRaises(ValueError):
            self.store.end(REF, "session-a", "done", "Different result.")

    def test_sessions_do_not_end_each_others_runs(self):
        self.start(); self.start(session="session-b")
        self.store.infer("session-a", "turn-a", "Interrupt")
        runs = self.store.progress(REF)
        self.assertEqual([r["status"] for r in runs], ["in-progress", "interrupted"])
        with self.assertRaises(ValueError):
            self.store.end(REF, "unrelated", "done", "Done.")

    def test_new_run_keeps_earlier_record(self):
        self.start()
        old = self.store.end(REF, "session-a", "done", "First task finished.")
        self.start(session="session-b", turn="turn-b")
        self.assertEqual(self.store.progress(REF)[1], old)

    def test_corrupt_store_not_replaced(self):
        self.path.parent.mkdir(); self.path.write_text("broken")
        with self.assertRaises(ValueError): self.start()
        self.assertEqual(self.path.read_text(), "broken")

    def test_lock_contention_returns_without_waiting(self):
        self.start()
        with open(str(self.path) + ".lock", "r+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError): self.start(turn="other")

    def test_summary_rejects_capability(self):
        self.start()
        with self.assertRaises(ValueError):
            self.store.end(REF, "session-a", "done", "URL /r/" + REF + "a" * 96)
        self.assertEqual(self.store.progress(REF)[0]["status"], "in-progress")

    def test_note_revision_report_is_explicit_durable_and_idempotent(self):
        self.start()
        self.assertIsNone(self.store.progress(REF)[0]["notes_revision"])
        run = self.store.end(REF, "session-a", "done", "Done.", 4)
        self.assertEqual((run["notes_revision"], run["notes_revision_source"]), (4, "agent"))
        self.assertEqual(Store(self.path).progress(REF)[0], run)
        self.assertEqual(self.store.end(REF, "session-a", "done", "Done.", 4), run)
        for revision in (None, 3, 5):
            with self.assertRaises(ValueError):
                self.store.end(REF, "session-a", "done", "Done.", revision)
        self.assertEqual(self.store.progress(REF)[0], run)

    def test_legacy_and_zero_note_revision_are_distinct(self):
        self.start()
        self.store.end(REF, "session-a", "done", "Done.")
        self.assertIsNone(self.store.progress(REF)[0]["notes_revision_source"])
        self.start(turn="turn-b")
        run = self.store.end(REF, "session-a", "done", "Done.", 0)
        self.assertEqual(run["notes_revision"], 0)
        self.assertEqual(run["notes_revision_source"], "agent")

    def test_invalid_note_revision_does_not_write(self):
        self.start()
        before = self.path.read_bytes()
        for revision in (-1, True, False, 1.0, "1", [], 9007199254740992):
            with self.assertRaises(ValueError):
                self.store.end(REF, "session-a", "done", "Done.", revision)
        self.assertEqual(self.path.read_bytes(), before)

    def test_mcp_optional_revision_and_original_required_fields(self):
        from unittest.mock import patch
        from seethis_runs.mcp_server import dispatch, TOOLS
        self.start()
        args = {"reference": REF, "status": "done", "summary": "Done.", "notes_revision": 2}
        with patch("seethis_runs.mcp_server.Store", return_value=self.store):
            result = dispatch({"method": "tools/call", "params": {"name": "run_end", "arguments": args, "_meta": {"threadId": "session-a"}}})
        self.assertEqual(json.loads(result["content"][0]["text"])["run"]["notes_revision"], 2)
        schema = next(t["inputSchema"] for t in TOOLS if t["name"] == "run_end")
        self.assertNotIn("notes_revision", schema["required"])
        self.assertFalse(schema["additionalProperties"])
        before = self.path.read_bytes()
        for value in (None, True, "2"):
            with patch("seethis_runs.mcp_server.Store", return_value=self.store):
                bad = dispatch({"method": "tools/call", "params": {"name": "run_end", "arguments": dict(args, notes_revision=value), "_meta": {"threadId": "session-a"}}})
            self.assertFalse(json.loads(bad["content"][0]["text"])["recorded"])
        self.assertEqual(self.path.read_bytes(), before)

    def test_owner_only_storage(self):
        self.start()
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)

    def test_symlink_not_followed(self):
        victim = Path(self.temp.name) / "victim"
        victim.write_text("unchanged")
        self.path.parent.mkdir(); self.path.symlink_to(victim)
        with self.assertRaises(OSError): self.start()
        self.assertEqual(victim.read_text(), "unchanged")


if __name__ == "__main__":
    unittest.main()
