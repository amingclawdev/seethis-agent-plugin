"""Read a registered interval for transient local display; never copy a rollout."""

from datetime import datetime
import json
import os
from pathlib import Path
import re
import stat

from seethis_runs.store import Store, reference_id

MAX_INTERVAL = 4 * 1024 * 1024
MAX_HEADER = 256 * 1024


def progress(reference, store=None):
    return (store or Store()).progress(reference_id(reference))


def _time(value):
    if not isinstance(value, str):
        raise ValueError("message_time_missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("message_time_missing")
    return int(parsed.timestamp() * 1000)


def _display_text(text):
    # A user message can contain its original capability. Do not expose that
    # capability again in the browser response, even though display is local.
    text = re.sub(r"http://127\.0\.0\.1(?::\d+)?/r/([0-9a-f]{32})[0-9a-f]+",
                  r"SeeThis reference \1 [capability omitted]", text)
    return re.sub(r"(?i)([#?](?:cap|token)=)[A-Za-z0-9_-]+", r"\1[omitted]", text)


def read_run(reference, run_id, store=None, sessions_root=None):
    """Only registered run IDs; no caller-supplied path, offset or session."""
    runs = progress(reference, store)
    matches = [r for r in runs if r.get("run_id") == run_id]
    if len(matches) != 1:
        raise ValueError("run_not_registered_for_reference")
    run = matches[0]
    start = run.get("handoff_start") or run.get("start", {}).get("locator") or {}
    ending = run.get("handoff_end") or run.get("reported_end") or run.get("inferred_end")
    end = (ending or {}).get("locator") or {}
    path = start.get("path")
    if not isinstance(path, str) or type(start.get("byte")) is not int or start["byte"] < 0:
        raise ValueError("start_location_missing")
    root = Path(sessions_root or Path.home() / ".codex/sessions").resolve(strict=True)
    p = Path(path)
    if p.is_symlink() or not p.resolve(strict=True).is_relative_to(root) or p.suffix != ".jsonl":
        raise ValueError("log_path_outside_sessions")
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("log_file_untrusted")
        identity = {"device": info.st_dev, "inode": info.st_ino}
        if start.get("file_identity", identity) != identity or end.get("file_identity", identity) != identity:
            raise ValueError("log_file_replaced")
        header = stream.readline(MAX_HEADER + 1)
        if len(header) > MAX_HEADER or not header.endswith(b"\n"):
            raise ValueError("session_header_unavailable")
        header = json.loads(header)
        if header.get("type") != "session_meta" or header.get("payload", {}).get("id") != run["session_id"]:
            raise ValueError("session_mismatch")
        if ending:
            if end.get("path") != path or type(end.get("byte")) is not int:
                raise ValueError("end_location_missing")
            cutoff = end["byte"]
        else:
            cutoff = info.st_size  # read-only snapshot, not an inferred ending
        if cutoff < start["byte"] or cutoff > info.st_size:
            raise ValueError("interval_truncated")
        if cutoff - start["byte"] > MAX_INTERVAL:
            raise ValueError("interval_exceeds_4_mib")
        stream.seek(start["byte"])
        raw = stream.read(cutoff - start["byte"])
        if not raw.endswith(b"\n"):
            if ending:
                raise ValueError("partial_record")
            raw = raw[:raw.rfind(b"\n") + 1]
        events = [json.loads(line) for line in raw.splitlines()]
    if not events or events[0].get("type") != "event_msg" or events[0].get("payload", {}).get("type") != "task_started" or events[0]["payload"].get("turn_id") != run["turn_id"]:
        raise ValueError("turn_anchor_mismatch")
    messages, fallback = [], []
    for ordinal, event in enumerate(events):
        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            raise ValueError("unsupported_record")
        if event.get("type") == "response_item" and payload.get("type") == "message" and payload.get("role") in ("user", "assistant"):
            content = payload.get("content")
            if not isinstance(content, list):
                raise ValueError("unsupported_message")
            pieces = [c["text"] for c in content if isinstance(c, dict) and c.get("type") in ("input_text", "output_text", "text") and isinstance(c.get("text"), str)]
            if pieces:
                messages.append({"kind": "message", "role": payload["role"], "at_ms": _time(event.get("timestamp")), "order": ordinal, "text": _display_text("\n".join(pieces))})
        elif event.get("type") == "event_msg" and payload.get("type") in ("user_message", "agent_message") and isinstance(payload.get("message"), str):
            fallback.append({"kind": "message", "role": "user" if payload["type"] == "user_message" else "assistant", "at_ms": _time(event.get("timestamp")), "order": ordinal, "text": _display_text(payload["message"])})
    # The researched host emits canonical response_item messages; event_msg can
    # repeat them. Use a single representation, never duplicate those messages.
    return {"available": True, "reference_id": reference, "run_id": run_id,
            "messages": messages if messages else fallback,
            "representation": "response_item" if messages else "event_msg",
            "interval": {"start_byte": start["byte"], "end_byte": cutoff, "live_snapshot": not bool(ending)},
            "note_revision_seen": None}
