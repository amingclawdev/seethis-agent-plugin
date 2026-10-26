"""Bounded, read-only checks for persisted handoff positions; never copy logs."""

import json
import os
from pathlib import Path
import stat

MAX_INTERVAL = 4 * 1024 * 1024
MAX_HEADER = 256 * 1024


def positions(run, cutoff=None, sessions_root=None):
    start = run.get("handoff_start") or run.get("start", {}).get("locator") or {}
    path, begin = start.get("path"), start.get("byte")
    if not isinstance(path, str) or type(begin) is not int or begin < 0:
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
        if start.get("file_identity", identity) != identity:
            raise ValueError("log_file_replaced")
        header = stream.readline(MAX_HEADER + 1)
        if len(header) > MAX_HEADER or not header.endswith(b"\n"):
            raise ValueError("session_header_unavailable")
        metadata = json.loads(header)
        if metadata.get("type") != "session_meta" or metadata.get("payload", {}).get("id") != run["session_id"]:
            raise ValueError("session_mismatch")
        if cutoff is not None:
            if cutoff.get("path") != path or type(cutoff.get("byte")) is not int:
                raise ValueError("end_location_missing")
            if cutoff.get("file_identity", identity) != identity:
                raise ValueError("log_file_replaced")
            end = cutoff["byte"]
        else:
            end = info.st_size
        if end < begin or end > info.st_size:
            raise ValueError("interval_truncated")
        if end - begin > MAX_INTERVAL:
            raise ValueError("interval_exceeds_4_mib")
        stream.seek(begin)
        raw = stream.read(end - begin)
        if not raw.endswith(b"\n"):
            if cutoff is not None:
                raise ValueError("partial_record")
            raw = raw[:raw.rfind(b"\n") + 1]
            end = begin + len(raw)
        events = [json.loads(line) for line in raw.splitlines()]
        if not events or events[0].get("type") != "event_msg" or events[0].get("payload", {}).get("type") != "task_started" or events[0]["payload"].get("turn_id") != run["turn_id"]:
            raise ValueError("turn_anchor_mismatch")
        for event in events[1:]:
            if event.get("type") == "event_msg" and event.get("payload", {}).get("type") == "task_started":
                raise ValueError("turn_has_advanced")
    return ({**start, "file_identity": identity},
            {"path": path, "byte": end, "turn_id": run["turn_id"], "file_identity": identity})
