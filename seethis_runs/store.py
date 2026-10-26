"""Small owner-only JSON store. No prompt, capability, or transcript copies."""

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import uuid

from seethis_runs.log_positions import positions


REFERENCE = re.compile(r"[0-9a-f]{32}\Z")
HANDED_URL = re.compile(r"http://127\.0\.0\.1(?::[0-9]{1,5})?/r/([0-9a-f]{32})(?:[0-9a-f]{0,224})(?![0-9a-zA-Z])")
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
MAX_STORE = 8 * 1024 * 1024
MAX_TAIL = 512 * 1024


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def reference_id(value):
    if not isinstance(value, str) or not REFERENCE.fullmatch(value):
        raise ValueError("reference_id_required")
    return value


def references_in_prompt(prompt):
    if not isinstance(prompt, str):
        return []
    return list(dict.fromkeys(m.group(1) for m in HANDED_URL.finditer(prompt)))


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError("invalid_identifier")
    return value


def store_path():
    # One shared store for all conversations; no dependency on current cwd.
    return Path.home() / ".local/share/seethis-agent-demo/runs.json"


def log_locator(path, turn_id=None):
    """Read metadata only, bounded to a tail; all locations are hints."""
    result = {"path": None, "byte": None, "turn_id": turn_id, "ordinal": None}
    if not isinstance(path, str) or not path:
        return result
    try:
        p = Path(path).resolve(strict=True)
        root = (Path.home() / ".codex/sessions").resolve()
        if not p.is_relative_to(root) or p.suffix != ".jsonl":
            return result
        with p.open("rb") as stream:
            size = os.fstat(stream.fileno()).st_size
            offset = max(0, size - MAX_TAIL)
            stream.seek(offset)
            if offset:
                stream.readline()
            result.update(path=str(p), byte=size)
            while True:
                at = stream.tell()
                raw = stream.readline(MAX_TAIL + 1)
                if not raw or len(raw) > MAX_TAIL:
                    break
                try:
                    obj = json.loads(raw)
                except (ValueError, UnicodeError):
                    continue
                payload = obj.get("payload") if isinstance(obj, dict) else None
                if not isinstance(payload, dict) or obj.get("type") != "event_msg":
                    continue
                if payload.get("type") != "task_started":
                    continue
                candidate = payload.get("turn_id")
                if not isinstance(candidate, str) or not IDENTIFIER.fullmatch(candidate):
                    continue
                if turn_id is None or candidate == turn_id:
                    ordinal = obj.get("ordinal")
                    result.update(turn_id=candidate, ordinal=ordinal if type(ordinal) is int else None)
                    if turn_id is not None:
                        result["byte"] = at
    except (OSError, ValueError):
        pass
    return result


class Store:
    def __init__(self, path=None, sessions_root=None):
        self.path = Path(path) if path is not None else store_path()
        self.sessions_root = sessions_root  # test-only injection, never an MCP argument

    @contextmanager
    def _locked(self, write=False):
        parent = self.path.parent
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if parent.is_symlink() or parent.stat().st_uid != os.getuid():
            raise OSError("unsafe_store_directory")
        os.chmod(parent, 0o700)
        lock = os.open(str(self.path) + ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(lock, (fcntl.LOCK_EX if write else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            if self.path.is_symlink():
                raise OSError("unsafe_store_file")
            try:
                with self.path.open("rb") as stream:
                    raw = stream.read(MAX_STORE + 1)
                if len(raw) > MAX_STORE:
                    raise ValueError("store_too_large")
                data = json.loads(raw)
                if data.get("schema_version") not in (1, 2) or not isinstance(data.get("references"), dict):
                    raise ValueError("unsupported_store")
            except FileNotFoundError:
                data = {"schema_version": 1, "references": {}}
            yield data
            if write:
                # Old plugin processes must fail open instead of ignoring the
                # immutable handoff boundary and writing a late run ending.
                data["schema_version"] = 2
                raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
                if len(raw) > MAX_STORE:
                    raise ValueError("store_too_large")
                fd, temporary = tempfile.mkstemp(prefix=".runs-", dir=parent)
                try:
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(raw)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, self.path)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
        finally:
            os.close(lock)

    def start(self, references, session_id, turn_id, transcript_path=None):
        session_id, turn_id = identifier(session_id), identifier(turn_id)
        references = list(dict.fromkeys(reference_id(r) for r in references))
        if not references:
            return
        locator = log_locator(transcript_path, turn_id)
        with self._locked(write=True) as data:
            for ref in references:
                runs = data["references"].setdefault(ref, [])
                if any(r["session_id"] == session_id and r["turn_id"] == turn_id for r in runs):
                    continue
                runs.append({"run_id": uuid.uuid4().hex, "reference_id": ref,
                             "agent": "codex", "session_id": session_id, "turn_id": turn_id,
                             "start": {"at": now(), "kind": "handed_in", "locator": locator},
                             "reported_end": None, "inferred_end": None})

    def infer(self, session_id, turn_id, event, transcript_path=None):
        session_id = identifier(session_id)
        if turn_id is not None:
            turn_id = identifier(turn_id)
        if event not in ("Stop", "Interrupt", "SessionEnd"):
            return
        locator = log_locator(transcript_path)
        with self._locked(write=True) as data:
            for runs in data["references"].values():
                for run in runs:
                    if run["session_id"] != session_id or (turn_id and run["turn_id"] != turn_id):
                        continue
                    if run["reported_end"] or run["inferred_end"] or run.get("handoff_end"):
                        continue
                    run["inferred_end"] = {"at": now(), "event": event, "source": "hook",
                                           "status": "stopped-without-end" if event == "Stop" else "interrupted",
                                           "locator": locator}

    def end(self, reference, session_id, status, summary, notes_revision=None):
        ref, session = reference_id(reference), identifier(session_id)
        if notes_revision is not None and (type(notes_revision) is not int or not 0 <= notes_revision <= 9007199254740991):
            raise ValueError("invalid_notes_revision")
        if status not in ("done", "blocked"):
            raise ValueError("invalid_status")
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 500:
            raise ValueError("invalid_summary")
        if "/r/" in summary or re.search(r"[0-9a-fA-F]{64,}", summary):
            raise ValueError("summary_must_not_contain_capability")
        with self._locked(write=True) as data:
            runs = [r for r in data["references"].get(ref, []) if r["session_id"] == session]
            if not runs:
                raise ValueError("no_run_for_current_session")
            run = runs[-1]
            if run.get("handoff_end"):
                raise ValueError("segment_transferred")
            if run["reported_end"]:
                # Retried delivery is harmless; a new task requires a new hand-in.
                if (run["reported_end"]["status"] == status and run["reported_end"]["summary"] == summary
                    and run["reported_end"].get("notes_revision") == notes_revision):
                    return self.present(run, data)
                raise ValueError("reported_end_already_recorded")
            path = run["start"]["locator"]["path"]
            run["reported_end"] = {"at": now(), "source": "agent", "status": status,
                                   "summary": summary, "locator": log_locator(path),
                                   "notes_revision": notes_revision}
            return self.present(run, data)

    @staticmethod
    def _fingerprint(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @staticmethod
    def _run(data, ref, run_id):
        matches = [r for r in data["references"].get(ref, []) if r["run_id"] == run_id]
        if len(matches) != 1:
            raise ValueError("run_not_registered_for_reference")
        return matches[0]

    def _handoff_pair(self, data, ref, session, from_run):
        source = self._run(data, ref, from_run)
        targets = [r for r in data["references"].get(ref, []) if r["session_id"] == session]
        if not targets:
            raise ValueError("no_run_for_current_session")
        target = targets[-1]
        if source["session_id"] == session:
            raise ValueError("different_session_required")
        if source.get("reported_end") or source.get("handoff_end"):
            raise ValueError("source_already_ended")
        if target.get("reported_end") or target.get("inferred_end") or target.get("handoff_end") or target.get("handoff_from"):
            raise ValueError("target_not_open")
        chain_id = source.get("chain_id", source["run_id"])
        chain = data.get("chains", {}).get(chain_id, {"active_run_id": source["run_id"], "revision": 0})
        if chain["active_run_id"] != source["run_id"]:
            raise ValueError("source_not_current")
        return source, target, chain_id, chain

    def confirm_takeover(self, reference, session_id, from_run_id):
        ref, session, from_run = reference_id(reference), identifier(session_id), identifier(from_run_id)
        with self._locked(write=True) as data:
            source, target, chain_id, chain = self._handoff_pair(data, ref, session, from_run)
            # A paused run's observed ending is retained, never extended into a
            # later turn. Otherwise freeze the last complete record available.
            ending = source.get("inferred_end")
            if ending and not ending.get("locator", {}).get("path"):
                raise ValueError("end_location_missing")
            _, end = positions(source, ending["locator"] if ending else None, self.sessions_root)
            start, _ = positions(target, sessions_root=self.sessions_root)
            basis = {"reference_id": ref, "from_run_id": from_run, "to_run_id": target["run_id"],
                     "target_session_id": session, "chain_id": chain_id, "chain_revision": chain["revision"],
                     "source_fingerprint": self._fingerprint(source), "target_fingerprint": self._fingerprint(target),
                     "source_end": end, "target_start": start}
            confirmations = data.setdefault("handoffs", {})
            for entry in confirmations.values():
                if entry["state"] == "confirmed" and all(entry.get(k) == v for k, v in basis.items()):
                    return dict(entry)
            entry = dict(basis, confirmation_id=uuid.uuid4().hex, state="confirmed", confirmed_at=now())
            confirmations[entry["confirmation_id"]] = entry
            return dict(entry)

    def commit_handoff(self, reference, session_id, confirmation_id):
        ref, session, confirmation = reference_id(reference), identifier(session_id), identifier(confirmation_id)
        with self._locked(write=True) as data:
            entry = data.get("handoffs", {}).get(confirmation)
            if not entry or entry["reference_id"] != ref or entry["target_session_id"] != session:
                raise ValueError("confirmation_not_owned")
            if entry["state"] == "committed":
                return dict(entry)  # retry never moves the active pointer backwards
            source, target, chain_id, chain = self._handoff_pair(data, ref, session, entry["from_run_id"])
            if target["run_id"] != entry["to_run_id"] or chain_id != entry["chain_id"] or chain["revision"] != entry["chain_revision"] or self._fingerprint(source) != entry["source_fingerprint"] or self._fingerprint(target) != entry["target_fingerprint"]:
                raise ValueError("handoff_state_changed")
            # Revalidate exact frozen positions. Never substitute the current
            # file end or silently accept a replaced/truncated session file.
            _, end = positions(source, entry["source_end"], self.sessions_root)
            pinned = dict(target, handoff_start=entry["target_start"])
            positions(pinned, sessions_root=self.sessions_root)
            at = now()
            source["handoff_end"] = {"at": at, "source": "handoff", "status": "transferred",
                                     "locator": end, "to_run_id": target["run_id"], "confirmation_id": confirmation}
            source["chain_id"] = target["chain_id"] = chain_id
            target["handoff_start"] = entry["target_start"]
            target["handoff_from"] = {"run_id": source["run_id"], "at": at, "confirmation_id": confirmation}
            data.setdefault("chains", {})[chain_id] = {"active_run_id": target["run_id"], "revision": chain["revision"] + 1}
            entry.update(state="committed", committed_at=at)
            return dict(entry)

    @staticmethod
    def present(run, data=None):
        end = run.get("handoff_end") or run["reported_end"] or run["inferred_end"]
        view = dict(run, status=end["status"] if end else "in-progress",
                    status_source=end["source"] if end else "hook",
                    summary=run["reported_end"]["summary"] if run["reported_end"] else "")
        revision = (run.get("reported_end") or {}).get("notes_revision")
        view["notes_revision"] = revision
        view["notes_revision_source"] = "agent" if revision is not None else None
        if data is not None:
            chain = data.get("chains", {}).get(run.get("chain_id"))
            view["current_segment"] = chain["active_run_id"] == run["run_id"] if chain else None
            # Retain stale confirmations in history, but do not advertise them
            # as a currently pending switch after either run/chain has changed.
            view["pending_handoffs"] = []
            for entry in data.get("handoffs", {}).values():
                if entry["state"] != "confirmed" or entry["to_run_id"] != run["run_id"]:
                    continue
                runs = data["references"].get(entry["reference_id"], [])
                source = next((r for r in runs if r["run_id"] == entry["from_run_id"]), None)
                targets = [r for r in runs if r["session_id"] == entry["target_session_id"]]
                active = data.get("chains", {}).get(entry["chain_id"],
                         {"active_run_id": entry["from_run_id"], "revision": 0})
                if (not source or not targets or targets[-1]["run_id"] != run["run_id"] or
                    active["active_run_id"] != entry["from_run_id"] or active["revision"] != entry["chain_revision"] or
                    Store._fingerprint(source) != entry["source_fingerprint"] or
                    Store._fingerprint(run) != entry["target_fingerprint"]):
                    continue
                view["pending_handoffs"].append({k: entry[k] for k in
                    ("confirmation_id", "from_run_id", "to_run_id", "confirmed_at")})
        return view

    def progress(self, reference):
        ref = reference_id(reference)
        with self._locked() as data:
            return [self.present(r, data) for r in reversed(data["references"].get(ref, []))]
