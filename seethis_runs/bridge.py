"""One-shot, read-only SeeThis helper. No listener and no transcript files."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from seethis_runs.log_reader import progress, read_run


def connect():
    package = Path(__file__).resolve().parent
    parent = Path.home() / ".local/share/seethis-agent-demo"
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if parent.is_symlink() or parent.stat().st_uid != os.getuid():
        raise ValueError("unsafe_connection_directory")
    os.chmod(parent, 0o700)
    binding = {"schema_version": 1, "python": str(Path(sys.executable).resolve()),
               "helper": str(package / "bridge.py"),
               "files": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(package.glob("*.py"))}}
    fd, tmp = tempfile.mkstemp(prefix=".bridge-", dir=parent)
    try:
        with os.fdopen(fd, "w") as out:
            json.dump(binding, out, indent=2); out.flush(); os.fsync(out.fileno())
        os.replace(tmp, parent / "bridge.json")
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
    return {"connected": True, "binding": str(parent / "bridge.json"), "helper": binding["helper"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--connect", action="store_true")
    parser.add_argument("--reference")
    parser.add_argument("--run")
    args = parser.parse_args()
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError()))
    signal.setitimer(signal.ITIMER_REAL, 1.5)
    try:
        if args.connect and not args.reference and not args.run:
            result = connect()
        elif args.reference and not args.connect:
            result = read_run(args.reference, args.run) if args.run else {"available": True, "runs": progress(args.reference)}
        else:
            raise ValueError("invalid_arguments")
    except Exception as error:
        # Never include exception paths, request text or excerpts in errors.
        known = {"run_not_registered_for_reference", "start_location_missing", "log_path_outside_sessions", "log_file_untrusted", "session_header_unavailable", "session_mismatch", "end_location_missing", "interval_truncated", "interval_exceeds_4_mib", "partial_record", "turn_anchor_mismatch", "unsupported_record", "unsupported_message", "message_time_missing"}
        result = {"available": False, "reason": str(error) if isinstance(error, ValueError) and str(error) in known else "unavailable_or_invalid_input"}
    sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
