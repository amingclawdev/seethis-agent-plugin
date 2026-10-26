"""Run the distributed shell command against isolated synthetic packages/state."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parent.parent
REF = "0123456789abcdef0123456789abcdef"


class HookFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.package = self.base / "relocated package with spaces"
        shutil.copytree(ROOT / "seethis_runs", self.package / "seethis_runs",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        self.home = self.base / "home"
        self.home.mkdir()
        self.bin = self.base / "bin"
        self.bin.mkdir()
        (self.bin / "python3").symlink_to(sys.executable)
        self.env = dict(os.environ, HOME=str(self.home), PATH=str(self.bin),
                        PLUGIN_ROOT=str(self.package), PYTHONDONTWRITEBYTECODE="1")
        self.env.pop("PYTHONPATH", None)
        self.state = self.home / ".local/share/seethis-agent-demo/runs.json"
        manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text())
        hooks = manifest["hooks"]["hooks"]
        self.assertEqual(set(hooks), {"UserPromptSubmit", "Stop", "Interrupt", "SessionEnd"})
        definitions = [h for blocks in hooks.values() for block in blocks for h in block["hooks"]]
        self.assertTrue(all(h["timeout"] == 1 for h in definitions))
        self.assertEqual(len({h["command"] for h in definitions}), 1)
        self.command = definitions[0]["command"]

    def event(self, name="UserPromptSubmit"):
        return {"hook_event_name": name, "session_id": "synthetic-session",
                "turn_id": "synthetic-turn", "prompt": "http://127.0.0.1/r/" + REF}

    def run_hook(self, event=None, raw=None, env=None):
        raw = json.dumps(self.event() if event is None else event).encode() if raw is None else raw
        start = time.monotonic()
        result = subprocess.run(["/bin/sh", "-c", self.command], input=raw,
                                cwd=self.base, env=self.env if env is None else env,
                                capture_output=True, timeout=1)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
        self.assertLess(time.monotonic() - start, 1)

    def test_relocated_package_records_and_ends_real_synthetic_run(self):
        self.run_hook()
        before = json.loads(self.state.read_text())["references"][REF][0]
        self.assertIsNone(before["inferred_end"])
        self.run_hook(self.event("Stop"))
        after = json.loads(self.state.read_text())["references"][REF][0]
        self.assertEqual(after["inferred_end"]["status"], "stopped-without-end")
        self.assertIsNone(after["reported_end"])

    def test_missing_target(self):
        (self.package / "seethis_runs/hooks.py").unlink()
        self.run_hook()
        self.assertFalse(self.state.exists())

    def test_missing_interpreter(self):
        (self.bin / "python3").unlink()
        self.run_hook()
        self.assertFalse(self.state.exists())

    def test_missing_or_empty_plugin_root(self):
        for value in (None, ""):
            with self.subTest(value=value):
                env = dict(self.env)
                if value is None:
                    env.pop("PLUGIN_ROOT")
                else:
                    env["PLUGIN_ROOT"] = value
                self.run_hook(env=env)
                self.assertFalse(self.state.exists())

    def test_import_failure_stops_without_callback(self):
        (self.package / "seethis_runs/store.py").write_text("raise RuntimeError('synthetic import failure')\n")
        self.run_hook()
        self.assertFalse(self.state.exists())
        # Direct invocation proves Python's own boundary catches the import too.
        result = subprocess.run([sys.executable, str(self.package / "seethis_runs/hooks.py")],
                                input=b"{}", env=self.env, capture_output=True, timeout=1)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))

    def test_syntax_failure_before_main(self):
        (self.package / "seethis_runs/hooks.py").write_text("invalid syntax !\n")
        self.run_hook()
        self.assertFalse(self.state.exists())

    def test_failed_callback_has_no_followup_or_retry(self):
        marker = self.base / "calls"
        (self.package / "seethis_runs/store.py").write_text(
            "from pathlib import Path\n"
            "def references_in_prompt(value): return ['" + REF + "', 'f' * 32]\n"
            "class Store:\n"
            " def start(self, *args):\n"
            "  with Path(" + repr(str(marker)) + ").open('a') as out: out.write('attempt\\n')\n"
            "  raise RuntimeError('synthetic callback failure')\n"
            " def infer(self, *args): raise AssertionError('unexpected callback')\n")
        self.run_hook()
        self.assertEqual(marker.read_text(), "attempt\n")
        self.assertFalse(self.state.exists())

    def test_bad_input_does_not_create_state(self):
        for raw in (b"{", b"[]", b"x" * 262145):
            with self.subTest(size=len(raw)):
                self.run_hook(raw=raw)
                self.assertFalse(self.state.exists())

    def test_corrupt_store_preserved(self):
        self.state.parent.mkdir(parents=True)
        self.state.write_text("synthetic corrupt store")
        self.run_hook()
        self.assertEqual(self.state.read_text(), "synthetic corrupt store")

    def test_open_stdin_and_slow_import_finish_within_host_timeout(self):
        for slow_import in (False, True):
            with self.subTest(slow_import=slow_import):
                if slow_import:
                    (self.package / "seethis_runs/store.py").write_text("import time\ntime.sleep(5)\n")
                start = time.monotonic()
                process = subprocess.Popen(["/bin/sh", "-c", self.command], stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env)
                try:
                    process.wait(timeout=1)
                    self.assertLess(time.monotonic() - start, 1)
                    self.assertEqual(process.returncode, 0)
                    self.assertEqual(process.stdout.read(), b"")
                    self.assertEqual(process.stderr.read(), b"")
                    self.assertFalse(self.state.exists())
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
                    process.stdin.close()
                    process.stdout.close()
                    process.stderr.close()


if __name__ == "__main__":
    unittest.main()
