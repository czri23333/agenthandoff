"""What a Codex store holds, and how much of it the reader actually reads.

Codex appends one rollout file per *turn*: `<session-id>.jsonl` for the first,
`<session-id>_<continuation-id>.jsonl` for the rest. A reader that treats a file
as a session shows the first turn and silently loses the rest, and nothing in the
UI says so - which is why this exists as a command instead of a claim.

    python scripts/codex_session_stats.py            # the store this machine has
    python scripts/codex_session_stats.py --json     # machine-readable

Read-only: it never writes to the store.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import sys

from agent_handoff.parsers import all_parsers

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# What a turn's dialogue is made of, for the "how much is missing" number.
MESSAGE_TYPES = {"message", "agent_message"}


def files_for(parser) -> list[pathlib.Path]:
    root = pathlib.Path(getattr(parser, "root", ""))
    if not root.is_dir():
        return []
    out = sorted(root.rglob("rollout-*.jsonl")) or sorted(root.rglob("*.jsonl"))
    return [p for p in out if p.name != "session_index.jsonl"]


def session_of(path: pathlib.Path) -> str:
    """The session id: the header's `payload.id`, else the filename's first UUID."""

    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if '"session_meta"' not in line:
                    continue
                payload = json.loads(line).get("payload") or {}
                ident = payload.get("id") or payload.get("session_id")
                if ident:
                    return str(ident)
                break
    except (OSError, ValueError):
        pass
    found = UUID.findall(path.stem)
    return found[0] if found else path.stem


def dialogue_records(paths: list[pathlib.Path]) -> int:
    """Message records across a session's files - the union a reader should show."""

    total = 0
    for path in paths:
        try:
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    if '"response_item"' not in line and '"event_msg"' not in line:
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    payload = row.get("payload") or {}
                    if str(payload.get("type")) in MESSAGE_TYPES:
                        total += 1
        except OSError:
            continue
    return total


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        prog="codex_session_stats", description=__doc__.splitlines()[0]
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--top", type=int, default=5, help="how many sessions to detail")
    args = parser.parse_args(argv)

    codex = next((p for p in all_parsers() if p.cli == "codex"), None)
    if codex is None:
        print("no codex parser is registered", file=sys.stderr)
        return 2

    paths = files_for(codex)
    grouped: dict[str, list[pathlib.Path]] = collections.defaultdict(list)
    for path in paths:
        grouped[session_of(path)].append(path)
    multi = {k: v for k, v in grouped.items() if len(v) > 1}
    listed = {m.session_id: m for m in codex.list_sessions()}

    report: dict = {
        "root": str(getattr(codex, "root", "")),
        "files": len(paths),
        "session_count": len(grouped),
        "multi_file_sessions": len(multi),
        "list_sessions_rows": len(listed),
        "detailed": [],
    }
    ranked = sorted(multi.items(), key=lambda kv: -len(kv[1]))[: args.top]
    for session_id, files in ranked:
        raw = None
        try:
            raw = codex.load(session_id)
        except (OSError, ValueError):
            raw = None
        report["detailed"].append(
            {
                "session_id": session_id,
                "files": len(files),
                "message_records": dialogue_records(files),
                "read_messages": len(raw.messages) if raw is not None else None,
                "listed": session_id in listed,
            }
        )

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    print(f"root: {report['root']}")
    print(
        f"{report['files']} rollout file(s) -> {report['session_count']} session(s); "
        f"{report['multi_file_sessions']} span more than one file"
    )
    rows = report["list_sessions_rows"]
    verdict = "one per session" if rows == report["session_count"] else "one per file?"
    print(f"list_sessions() rows: {rows}  ({verdict}); a session read short says so below")
    if not report["detailed"]:
        print("no multi-file session in this store")
        return 0
    print(f"\n{'session':<38} {'files':>5} {'msgs on disk':>13} {'read back':>10}")
    for row in report["detailed"]:
        read = "n/a" if row["read_messages"] is None else str(row["read_messages"])
        flag = ""
        short = (
            row["read_messages"] is not None
            and row["message_records"]
            and row["read_messages"] < row["message_records"]
        )
        if short:
            flag = "  <- short"
        line = (
            f"{row['session_id']:<38} {row['files']:>5} "
            f"{row['message_records']:>13} {read:>10}{flag}"
        )
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
