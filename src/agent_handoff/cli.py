"""Command-line interface: handoff doctor|list|capture|resume|publish|inbox|claim."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_handoff import __version__
from agent_handoff.exchange import claim as exchange_claim
from agent_handoff.exchange import inbox as exchange_inbox
from agent_handoff.exchange import publish as exchange_publish
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
    if args.note:
        bundle.meta.notes = list(args.note)
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


def _cmd_publish(args: argparse.Namespace) -> int:
    try:
        dest = exchange_publish(
            Path(args.bundle),
            global_scope=args.to_global,
            note=args.note,
        )
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    scope = "global" if args.to_global else "project"
    print(f"published ({scope}): {dest}")
    return 0


def _cmd_inbox(args: argparse.Namespace) -> int:
    items = exchange_inbox(global_scope=args.to_global)
    if not items:
        scope = "global" if args.to_global else "project"
        print(f"inbox empty ({scope}).")
        return 0
    print(f"{'published':<18} {'cli':<12} {'status':<9} title")
    print("-" * 84)
    for it in items:
        status = f"claimed({it.claimed_by[:12]})" if it.claimed else "open"
        print(f"{it.published_at:<18} {it.cli:<12} {status:<9} {it.title[:44]}")
        print(f"{'':<18} file: {it.path}")
    return 0


def _cmd_claim(args: argparse.Namespace) -> int:
    try:
        sidecar = exchange_claim(Path(args.bundle), claimed_by=args.by)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"claimed: {sidecar}")
    return 0


def _cmd_threads(args: argparse.Namespace) -> int:
    """Cluster sessions across CLIs into task threads (one job, many sessions)."""
    from agent_handoff.threads import (
        SessionNode,
        build_threads,
        describe_thread,
        normalize_path,
        title_tokens,
    )

    parsers = available_parsers()
    if args.cli:
        parsers = [p for p in parsers if p.cli == args.cli]
    nodes: list[SessionNode] = []
    for p in parsers:
        for m in p.list_sessions():
            if args.cwd and args.cwd.lower() not in m.cwd.lower():
                continue
            raw = p.load(m.session_id)
            files = {normalize_path(f) for f in raw.files_touched} if raw else set()
            nodes.append(
                SessionNode(meta=m, files=files, tokens=title_tokens(m.title))
            )
    if not nodes:
        print("no sessions found.")
        return 0
    threads = build_threads(nodes, min_jaccard=args.min_overlap, window_days=args.window_days)
    multi = [t for t in threads if len(t.sessions) > 1]
    multi.sort(key=lambda t: t.last_active or "", reverse=True)
    if not multi:
        print("no multi-session threads detected (all sessions look standalone).")
        return 0
    print(f"{len(multi)} task thread(s) spanning multiple sessions:\n")
    for idx, t in enumerate(multi[: args.n], 1):
        print(f"Thread {idx}: {describe_thread(t)[0]}")
        for line in describe_thread(t)[1:]:
            print(line)
        print()
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
    p_cap.add_argument(
        "--note",
        action="append",
        default=[],
        help="attach a provenance note (repeatable), e.g. --note 'account:work'",
    )

    p_pub = sub.add_parser(
        "publish", help="copy a bundle into the exchange dir for other agents"
    )
    p_pub.add_argument("bundle", help="path to a bundle .md/.json file")
    p_pub.add_argument(
        "--global",
        dest="to_global",
        action="store_true",
        help="publish to ~/.agenthandoff instead of <cwd>/.handoff",
    )
    p_pub.add_argument("--note", help="publication note (who it is for, why)")

    p_inb = sub.add_parser("inbox", help="list published handoffs waiting for pickup")
    p_inb.add_argument(
        "--global",
        dest="to_global",
        action="store_true",
        help="read ~/.agenthandoff instead of <cwd>/.handoff",
    )

    p_clm = sub.add_parser("claim", help="mark a published handoff as taken")
    p_clm.add_argument("bundle", help="path to the published bundle")
    p_clm.add_argument("--by", help="who is claiming (default: hostname)")

    p_thr = sub.add_parser(
        "threads",
        help="cluster sessions across CLIs into task threads (one job, many sessions)",
    )
    p_thr.add_argument("--cli", help="restrict to one cli")
    p_thr.add_argument("--cwd", help="filter sessions whose cwd contains this substring")
    p_thr.add_argument(
        "--min-overlap",
        type=float,
        default=0.15,
        help="file-set Jaccard threshold for linking (default 0.15)",
    )
    p_thr.add_argument(
        "--window-days", type=int, default=21, help="link time window in days (default 21)"
    )
    p_thr.add_argument("-n", type=int, default=10, help="max threads shown (default 10)")

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
    "publish": _cmd_publish,
    "inbox": _cmd_inbox,
    "claim": _cmd_claim,
    "threads": _cmd_threads,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return _HANDLERS[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
