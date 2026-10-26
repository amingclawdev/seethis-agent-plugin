"""Host-owned MCP stdio connection; no listener, daemon, or network access."""

import json
from pathlib import Path
import signal
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from seethis_runs.store import Store
from seethis_runs.log_reader import progress


TOOLS = [
    {"name": "get_progress", "description": "Read all runs for a 32-hex SeeThis reference ID, newest first. Returns metadata and log pointers only. Call before continuing a reference. Never send the capability URL.",
     "inputSchema": {"type": "object", "properties": {"reference": {"type": "string", "pattern": "^[0-9a-f]{32}$"}}, "required": ["reference"], "additionalProperties": False}},
    {"name": "run_end", "description": "Report done or blocked for the latest run in this Codex conversation. Summary must be brief original prose, never prompt/log quotes, URLs or capabilities. Requires host _meta.threadId; no guessed session.",
     "inputSchema": {"type": "object", "properties": {"reference": {"type": "string", "pattern": "^[0-9a-f]{32}$"}, "status": {"type": "string", "enum": ["done", "blocked"]}, "summary": {"type": "string", "minLength": 1, "maxLength": 500}, "notes_revision": {"type": "integer", "minimum": 0, "maximum": 9007199254740991, "description": "The exact notes_revision read from reference JSON for this work; agent-reported, not verified receipt."}}, "required": ["reference", "status", "summary"], "additionalProperties": False}},
]
TOOLS += [
    {"name": "confirm_takeover", "description": "After reading get_progress and agreeing to take over unfinished work, confirm the exact old run. Persists log positions only; does NOT switch the current segment. The old agent should be paused. Requires a newly handed-in open run in this host conversation. Then call commit_handoff with the returned confirmation_id before continuing work.",
     "inputSchema": {"type": "object", "properties": {"reference": {"type": "string", "pattern": "^[0-9a-f]{32}$"}, "from_run_id": {"type": "string"}}, "required": ["reference", "from_run_id"], "additionalProperties": False}},
    {"name": "commit_handoff", "description": "Commit this conversation's confirmed takeover: atomically fix the old log cutoff, link the new log start, and switch the current segment. Idempotent. Refuses stale state or unavailable log positions; continue only if recorded is true. Does not stop another agent's actual process.",
     "inputSchema": {"type": "object", "properties": {"reference": {"type": "string", "pattern": "^[0-9a-f]{32}$"}, "confirmation_id": {"type": "string"}}, "required": ["reference", "confirmation_id"], "additionalProperties": False}},
]


def timeout(*_):
    raise TimeoutError()


def tool_result(value):
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}], "isError": False}


def dispatch(request):
    method, params = request.get("method"), request.get("params", {})
    if method == "initialize":
        return {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "seethis-runs", "version": "0.4.0"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        signal.setitimer(signal.ITIMER_REAL, 0.8)
        try:
            args, name = params.get("arguments", {}), params.get("name")
            if name == "get_progress" and set(args) == {"reference"}:
                return tool_result({"available": True, "runs": progress(args["reference"])})
            if name == "run_end" and {"reference", "status", "summary"} <= set(args) <= {"reference", "status", "summary", "notes_revision"}:
                if "notes_revision" in args and type(args["notes_revision"]) is not int:
                    raise ValueError("invalid_notes_revision")
                session = params.get("_meta", {}).get("threadId")
                if not session:
                    return tool_result({"available": False, "reason": "host_thread_id_missing", "recorded": False})
                run = Store().end(args["reference"], session, args["status"], args["summary"], args.get("notes_revision"))
                return tool_result({"available": True, "recorded": True, "run": run})
            if (name == "confirm_takeover" and set(args) == {"reference", "from_run_id"}) or (name == "commit_handoff" and set(args) == {"reference", "confirmation_id"}):
                session = params.get("_meta", {}).get("threadId")
                if not session:
                    return tool_result({"available": False, "recorded": False, "reason": "host_thread_id_missing"})
                store = Store()
                handoff = (store.confirm_takeover(args["reference"], session, args["from_run_id"]) if name == "confirm_takeover"
                           else store.commit_handoff(args["reference"], session, args["confirmation_id"]))
                return tool_result({"available": True, "recorded": True, "handoff": handoff})
            return tool_result({"available": False, "reason": "unsupported_call", "recorded": False})
        except (Exception, TimeoutError) as error:
            known = {"segment_transferred", "different_session_required", "source_already_ended", "source_not_current", "target_not_open", "confirmation_not_owned", "handoff_state_changed", "no_run_for_current_session", "start_location_missing", "end_location_missing", "session_mismatch", "turn_anchor_mismatch", "turn_has_advanced", "log_file_replaced", "interval_truncated", "interval_exceeds_4_mib", "partial_record"}
            reason = str(error) if isinstance(error, ValueError) and str(error) in known else "unavailable_or_invalid_input"
            return tool_result({"available": False, "reason": reason, "recorded": False})
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
    raise ValueError("unsupported_method")


def main():
    signal.signal(signal.SIGALRM, timeout)
    for raw in sys.stdin.buffer:
        # MCP framing is newline JSON. Never log raw input or exception text.
        if len(raw) > 1048576:
            continue
        try:
            request = json.loads(raw)
            if not isinstance(request, dict) or "id" not in request:
                continue
            try:
                response = {"jsonrpc": "2.0", "id": request["id"], "result": dispatch(request)}
            except Exception:
                response = {"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32601, "message": "Unsupported request"}}
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        except (ValueError, UnicodeError, BrokenPipeError):
            continue


if __name__ == "__main__":
    main()
