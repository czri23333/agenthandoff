"""Format fingerprints and the drift gate - the second layer of the sentinel.

The fixtures answer "can this parser read this format at all". This answers the
quieter question: "did the answer change?". A vendor rename - `payload` to
`content`, `function_call` to `tool_use` - does not break a test suite that only
asserts "sessions > 0"; it silently deletes the data the parser used to extract,
and the user finds out weeks later by noticing a field that is always empty.

Two halves, both derived from the committed fixtures, so they run anywhere:

``store``  the shape of the store itself: record types, the key set of each type,
           SQLite tables and columns, file suffixes. Vendor drift shows up here.
``parse``  what our parsers get out of it: sessions, messages, non-empty text,
           tool calls, file anchors. A regression in OUR code shows up here.

Baseline lives in ``conformance/<cli>.json`` - readable, diffable, and the file a
reviewer checks a claim against. ``check`` exits non-zero on any difference in
either direction: a lost key is a regression, a gained one is drift that somebody
must look at and re-baseline on purpose. A gate that only fails on half the
changes is a dashboard.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

from agent_handoff import fixtures
from agent_handoff.parsers import all_parsers

try:  # optional extra, exactly as in the library
    import zstandard
except ImportError:  # pragma: no cover
    zstandard = None

FINGERPRINT_VERSION = "1"
JSONL_SUFFIXES = (".jsonl", ".json", ".zstd", ".zst", ".ndjson")
SQLITE_SUFFIXES = (".sqlite", ".db")
MAX_KEYS_PER_TYPE = 80  # a record type with more keys than this is a schema dump


def _read_records(path: Path) -> list[str]:
    """Lines of a JSONL-ish file, transparently unpacking a zstd roll."""
    data = path.read_bytes()
    if path.suffix.lower() in {".zstd", ".zst"}:
        if zstandard is None:
            return []
        try:
            data = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(data)).read()
        except Exception:  # a truncated roll is a real format case, not a crash
            return []
    return [line for line in data.decode("utf-8", "replace").splitlines() if line.strip()]


def _schema_of(path: Path) -> dict:
    """Tables and columns of a SQLite store, from its own sqlite_master."""
    out: dict[str, list[str]] = {}
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        tables = [
            r[0]
            for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if not r[0].startswith("sqlite_")
        ]
        for name in tables:
            out[name] = sorted(r[1] for r in con.execute(f'PRAGMA table_info("{name}")'))
    finally:
        con.close()
    return out


def store_shape(root: Path) -> dict:
    """The format the fixture holds, independent of whether we can read it."""
    types: Counter[str] = Counter()
    keys: dict[str, set[str]] = {}
    envelopes: Counter[str] = Counter()
    tables: dict[str, list[str]] = {}
    suffixes: Counter[str] = Counter()
    # A SQLite store's fixture root is the file itself, not a directory.
    paths = [root] if root.is_file() else sorted(root.rglob("*"))
    for path in sorted(p for p in paths if p.is_file()):
        suffix = path.suffix.lower()
        suffixes[suffix or "<none>"] += 1
        if suffix in SQLITE_SUFFIXES:
            with contextlib.suppress(sqlite3.Error):
                tables.update(_schema_of(path))
            continue
        if suffix in JSONL_SUFFIXES or suffix == "":
            for line in _read_records(path):
                try:
                    record = json.loads(line)
                except ValueError:
                    types["<not-json>"] += 1
                    continue
                if isinstance(record, dict):
                    kind = str(record.get("type") or record.get("role") or "<no-type>")
                    top = ",".join(sorted(str(k) for k in record)[:4])
                    envelopes[top] += 1
                else:
                    kind, top = "<scalar>", type(record).__name__
                types[kind] += 1
                keys.setdefault(kind, set()).update(
                    str(k) for k in record if isinstance(record, dict)
                )
    return {
        "record_types": dict(sorted(types.items())),
        "keys_by_type": {
            kind: sorted(values)[:MAX_KEYS_PER_TYPE]
            for kind, values in sorted(keys.items())
        },
        "top_key_sets": {k: v for k, v in sorted(envelopes.items())[:40]},
        "tables": {name: cols for name, cols in sorted(tables.items())},
        "files_by_suffix": dict(sorted(suffixes.items())),
    }


def parse_shape(evidence: fixtures.Evidence) -> dict:
    """What our code gets out of that format."""
    return {
        "files": evidence.files,
        "sessions": evidence.sessions,
        "messages": evidence.messages,
        "nonempty_messages": evidence.nonempty,
        "tool_calls": evidence.tools,
        "file_anchors": evidence.files_touched,
        "source_messages": evidence.source_messages,
        "shape_only": evidence.shape_only,
        "sampled": evidence.sampled,
        "proven": evidence.proven,
        # Which extras this environment had: `dsh` reads zero sessions without
        # zstandard, and that says nothing about the format.
        "unusable": evidence.unusable,
    }


def fingerprint(parser) -> dict:
    cli = parser.cli
    root = fixtures.root_for(cli)
    empty: dict = {
        "record_types": {},
        "keys_by_type": {},
        "top_key_sets": {},
        "tables": {},
        "files_by_suffix": {},
    }
    return {
        "version": FINGERPRINT_VERSION,
        "cli": cli,
        "env": {"zstandard": zstandard is not None},
        "store": store_shape(root) if root and root.exists() else empty,
        "parse": parse_shape(fixtures.measure(parser)),
    }


def baseline_path(cli: str) -> Path:
    return fixtures.BASELINE_ROOT / f"{cli}.json"


def load_baseline(cli: str) -> dict | None:
    path = baseline_path(cli)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def write_baseline(cli: str, payload: dict) -> Path:
    path = baseline_path(cli)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _diff_mapping(old: dict, new: dict, label: str, lost, gained, changed) -> None:
    for key in sorted(set(old) - set(new)):
        lost.append(f"{label} {key!r} disappeared ({old[key]})")
    for key in sorted(set(new) - set(old)):
        gained.append(f"{label} {key!r} appeared ({new[key]})")
    for key in sorted(set(old) & set(new)):
        if old[key] != new[key]:
            changed.append(f"{label} {key!r}: {old[key]} -> {new[key]}")


def diff(baseline: dict, current: dict, parse_comparable: bool = True) -> dict[str, list[str]]:
    """Every difference, split by who is probably at fault."""
    lost: list[str] = []
    gained: list[str] = []
    changed: list[str] = []
    base_store, now_store = baseline.get("store", {}), current.get("store", {})
    base_keys = base_store.get("keys_by_type", {})
    now_keys = now_store.get("keys_by_type", {})
    _diff_mapping(
        base_store.get("record_types", {}),
        now_store.get("record_types", {}),
        "record type",
        lost,
        gained,
        [],
    )
    for kind in sorted(set(base_keys) | set(now_keys)):
        before = set(base_keys.get(kind, []))
        after = set(now_keys.get(kind, []))
        for key in sorted(before - after):
            lost.append(f"key {key!r} disappeared from record type {kind!r}")
        for key in sorted(after - before):
            gained.append(f"key {key!r} appeared in record type {kind!r}")
    _diff_mapping(
        base_store.get("tables", {}),
        now_store.get("tables", {}),
        "table",
        lost,
        gained,
        changed,
    )
    base_parse, now_parse = baseline.get("parse", {}), current.get("parse", {})
    for field in ("sessions", "nonempty_messages", "tool_calls", "file_anchors"):
        if not parse_comparable:
            break
        before, after = base_parse.get(field, 0), now_parse.get(field, 0)
        if after < before:
            lost.append(f"parse: {field} fell {before} -> {after}")
        elif after > before:
            gained.append(f"parse: {field} rose {before} -> {after}")
    if not now_store and base_store:
        lost.append("store: the fixture is gone; nothing can be verified")
    return {"lost": lost, "added": gained, "changed": changed}


def check(clis: list[str] | None = None) -> dict[str, dict]:
    """Per-CLI verdicts. A CLI with no baseline is reported, not silently passed."""
    report: dict[str, dict] = {}
    for parser in all_parsers():
        if clis and parser.cli not in clis:
            continue
        cli = parser.cli
        if not fixtures.cli_dir(cli).is_dir():
            if load_baseline(cli) is not None:
                report[cli] = {"status": "missing-fixture", "diff": {}}
            continue
        baseline = load_baseline(cli)
        current = fingerprint(parser)
        if baseline is None:
            report[cli] = {
                "status": "no-baseline",
                "diff": {},
                "proven": current["parse"]["proven"],
            }
            continue
        # A missing optional codec makes the parse numbers meaningless on both
        # sides, so only the store half is compared and the gap is reported.
        unusable = bool(baseline["parse"].get("unusable") or current["parse"]["unusable"])
        differences = diff(baseline, current, parse_comparable=not unusable)
        clean = not any(differences.values())
        status = ("codec-skipped" if unusable and clean else "ok") if clean else "drift"
        report[cli] = {
            "status": status,
            "diff": differences,
            "proven": current["parse"]["proven"],
            "shape_only": current["parse"]["shape_only"],
        }
    return report


def refresh(clis: list[str] | None = None) -> list[str]:
    written = []
    for parser in all_parsers():
        if clis and parser.cli not in clis:
            continue
        if not fixtures.cli_dir(parser.cli).is_dir():
            continue
        write_baseline(parser.cli, fingerprint(parser))
        written.append(parser.cli)
    return written


def format_report(report: dict[str, dict]) -> str:
    lines: list[str] = []
    for cli, verdict in sorted(report.items()):
        status = verdict["status"]
        mark = "ok  " if status in ("ok", "codec-skipped") else "FAIL"
        extra = " proven" if verdict.get("proven") else ""
        if verdict.get("shape_only"):
            extra = " shape-only (source store had no dialogue)"
        if status == "codec-skipped":
            extra += " parse half skipped: optional codec missing here"
        lines.append(f"[{mark}] {cli:<14} {status}{extra}")
        differences = verdict.get("diff") or {}
        for kind in ("lost", "added", "changed"):
            for item in differences.get(kind, []):
                lines.append(f"    {kind}: {item}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="conformance", description=__doc__.split("\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="compare fixtures with baselines")
    mode.add_argument("--write", action="store_true", help="record fingerprints as baselines")
    mode.add_argument("--show", action="store_true", help="print the current fingerprint")
    ap.add_argument("--cli", action="append", help="restrict to these cli ids")
    args = ap.parse_args(argv)
    wanted = args.cli or []
    parsers = [p for p in all_parsers() if not wanted or p.cli in wanted]

    if args.write:
        for cli in refresh(wanted or None):
            print(f"[write] {cli} -> {baseline_path(cli).name}")
        print(f"{len(parsers)} fingerprint(s); commit conformance/*.json")
        return 0
    if args.show:
        for parser in parsers:
            if fixtures.cli_dir(parser.cli).is_dir():
                print(json.dumps(fingerprint(parser), indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    report = check(wanted or None)
    print(format_report(report))
    bad = [cli for cli, v in report.items() if v["status"] not in ("ok", "codec-skipped")]
    if bad:
        print(
            f"\n{len(bad)} CLI(s) drifted from the committed baselines. If the change is "
            "the vendor's, teach the parser and re-run `python -m agent_handoff.conformance "
            "--write`; if it is yours, fix it. Never re-baseline to silence the gate."
        )
        return 1
    print(f"\n{len(report)} CLI(s) match their baselines.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
