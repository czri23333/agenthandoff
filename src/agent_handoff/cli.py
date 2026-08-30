"""Command-line interface: handoff doctor|list|capture|resume."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_handoff import __version__
from agent_handoff.locations import discover
from agent_handoff.parsers import available_parsers, resolve_session
from agent_handoff.render import load_bundle, render_json, render_markdown
from agent_handoff.resume import render_brief
from agent_handoff.summarize import summarize


def _cmd_doctor(_args: argparse.Namespace) -> int:
    stores = discover()
    if not stores:
        print("No known CLI session stores found on this machine.")
        return 1
    print(f"{'cli':<14} {'kind':<10} {'readable':<9} {'via':<4} detail")
    print("-" * 88)
    for s in stores:
        via = "wsl" if s.via_wsl else "native"
        mark = "yes" if s.readable else "no"
        print(f"{s.cli:<14} {s.kind:<10} {mark:<9} {via:<4} {s.detail}")
        print(f"{'':<14} path: {s.path}")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    parsers = available_parsers()
    if args.cli:
        parsers = [p for p in parsers if p.cli == args.cli]
        if not parsers:
            print(f"error: cli '{args.cli}' has no available store", file=sys.stderr)
            return 1

    metas = []
    for p in parsers:
        metas.extend(p.list_sessions())
    if args.cwd:
        needle = str(args.cwd)
        metas = [m for m in metas if needle.lower() in m.cwd.lower()]
    metas.sort(key=lambda m: m.updated_at or "", reverse=True)
    metas = metas[: args.n]

    if args.json:
        import json

        print(json.dumps([m.__dict__ for m in metas], ensure_ascii=False, indent=2))
        return 0
    if not metas:
        print("No sessions found.")
        return 0
    print(f"{'cli':<14} {'updated':<20} {'title':<46} session")
    print("-" * 108)
    for m in metas:
        title = m.title.replace("\n", " ")[:44]
        print(f"{m.cli:<14} {(m.updated_at or '?'):<20} {title:<46} {m.session_id}")
    return 0


def _cmd_capture(args: argparse.Namespace) -> int:
    ref = args.ref or "latest"
    try:
        _parser, raw = resolve_session(ref, cli=args.cli)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    bundle = summarize(raw)
    out = render_json(bundle) if args.json else render_markdown(bundle)
    if args.out:
        dest = Path(args.out)
        dest.write_text(out, encoding="utf-8")
        print(f"bundle written: {dest} ({len(out)} chars)")
    else:
        print(out)
    return 0


def _cmd_resume(args: argparse.Namespace) -> int:
    try:
        bundle = load_bundle(args.bundle)
    except (OSError, ValueError) as e:
        print(f"error: cannot read bundle: {e}", file=sys.stderr)
        return 1
    brief = render_brief(bundle, lang=args.lang, max_chars=args.max_chars)
    if args.out:
        Path(args.out).write_text(brief, encoding="utf-8")
        print(f"brief written: {args.out} ({len(brief)} chars)")
    else:
        print(brief)
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="handoff",
        description=(
            "Capture an AI coding CLI session into a portable handoff bundle and "
            "generate a continuation brief for the next session. Fully local, "
            "deterministic, no API keys."
        ),
    )
    ap.add_argument("--version", action="version", version=f"agenthandoff {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="probe which CLI stores exist and are readable")

    p_list = sub.add_parser("list", help="list recent sessions across CLIs")
    p_list.add_argument("--cli", help="filter by cli id (zcode, claude, codebuddy, dsh, ...)")
    p_list.add_argument("--cwd", help="filter sessions whose cwd contains this substring")
    p_list.add_argument("-n", type=int, default=15, help="max rows (default 15)")
    p_list.add_argument("--json", action="store_true", help="machine-readable output")

    p_cap = sub.add_parser("capture", help="write a handoff bundle for a session")
    p_cap.add_argument("ref", nargs="?", default=None, help="session id (default: latest)")
    p_cap.add_argument("--cli", help="restrict the search to one cli")
    p_cap.add_argument("--out", help="write bundle to file (default: stdout)")
    p_cap.add_argument("--json", action="store_true", help="emit JSON instead of markdown")

    p_res = sub.add_parser("resume", help="generate a continuation brief from a bundle")
    p_res.add_argument("bundle", help="path to a bundle .md or .json file")
    p_res.add_argument("--max-chars", type=int, default=12000, help="brief budget (default 12000)")
    p_res.add_argument("--lang", choices=["en", "zh"], default="en", help="scaffolding language")
    p_res.add_argument("--out", help="write brief to file (default: stdout)")

    return ap


_HANDLERS = {
    "doctor": _cmd_doctor,
    "list": _cmd_list,
    "capture": _cmd_capture,
    "resume": _cmd_resume,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return _HANDLERS[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
