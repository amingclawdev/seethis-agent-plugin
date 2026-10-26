"""Fail-open command hook: consume input in memory; retain only run metadata."""

import json
import os
from pathlib import Path
import signal
import sys


def main():
    signal.signal(signal.SIGALRM, lambda *_: os._exit(0))
    signal.setitimer(signal.ITIMER_REAL, 0.8)
    # Import only after the deadline and inside the outer fail-open boundary.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from seethis_runs.store import Store, references_in_prompt

    raw = sys.stdin.buffer.read(262145)
    if len(raw) > 262144:
        return
    event = json.loads(raw)
    name = event.get("hook_event_name")
    if name == "UserPromptSubmit":
        refs = references_in_prompt(event.get("prompt"))
        if refs:
            Store().start(refs, event.get("session_id"), event.get("turn_id"), event.get("transcript_path"))
    elif name in ("Stop", "Interrupt", "SessionEnd"):
        Store().infer(event.get("session_id"), event.get("turn_id"), name, event.get("transcript_path"))


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        pass
    sys.exit(0)
