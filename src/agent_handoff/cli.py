"""Command-line interface: handoff doctor|list|capture|resume|publish|inbox|claim."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

from agent_handoff import __version__, vault
from agent_handoff import search as ah_search
from agent_handoff.exchange import claim as exchange_claim
from agent_handoff.exchange import inbox as exchange_inbox
from agent_handoff.exchange import publish as exchange_publish
from agent_handoff.locations import discover
from agent_handoff.parsers import available_parsers, resolve_session
from agent_handoff.render import load_bundle, render_json, render_markdown
from agent_handoff.resume import render_brief
from agent_handoff.summarize import summarize


def _cmd_doctor(args: argparse.Namespace) -> int:
    stores = discover()
    parsed = _doctor_rows(stores)
    if args.markdown:
        print(render_doctor_markdown(parsed))
        return 0
    width = max((len(s.cli) for s in stores), default=6) + 2
    print(f"{'cli':<{width}} {'kind':<10} {'readable':<9} {'parses':<8} {'via':<6} detail")
    print("-" * 88)
    for info, sessions, note in parsed:
        via = "wsl" if info.via_wsl else "native"
        extra = f"; {note}" if note else ""
        parses = f"yes ({sessions})" if sessions >= 0 else "n/a"
        readable = "yes" if info.readable else "no"
        print(
            f"{info.cli:<{width}} {info.kind:<10} {readable:<9} {parses:<8} "
            f"{via:<6} {info.detail}{extra}"
        )
        print(f"{'':<{width}} path: {info.path}")
    if not stores:
        print("no known CLI stores found on this machine.")
    return 0


def _doctor_rows(stores):
    """Ask each registered parser what it actually sees in this store."""
    from agent_handoff.parsers import all_parsers

    by_cli: dict[str, list] = {}
    for parser in all_parsers():
        by_cli.setdefault(parser.cli, []).append(parser)
    out = []
    for info in stores:
        sessions = -1
        note = ""
        for parser in by_cli.get(info.cli, []):
            try:
                # StoreInfo.path is exactly what each parser's constructor wants:
                # the SQLite file for sqlite stores, the session directory otherwise.
                scoped = parser.with_root(Path(info.path))
                metas = scoped.list_sessions()
                sessions = len(metas)
                if sessions:
                    break
            except (OSError, ValueError) as exc:  # evidence, not an assumption
                note = f"parser error: {type(exc).__name__}"
        out.append((info, sessions, note))
    return out


def _parses_cell(sessions: int) -> str:
    """Markdown cell: did a registered parser actually read this store?

    -1 means no parser is registered for the cli id at all - a different
    statement from "registered, but it returned zero sessions".
    """
    if sessions < 0:
        return "—"
    if sessions:
        return f"✅ {sessions} sessions"
    return "❌ 0 sessions"


def render_doctor_markdown(rows) -> str:
    """The same evidence as a table — the raw material of the README matrix."""
    lines = [
        "| CLI | store | readable | parses on this machine | detail |",
        "|---|---|---|---|---|",
    ]
    for info, sessions, note in rows:
        parses = _parses_cell(sessions)
        detail = info.detail + (f"; {note}" if note else "")
        lines.append(
            f"| `{info.cli}` | {info.kind}{' (WSL)' if info.via_wsl else ''} "
            f"| {'✅' if info.readable else '❌'} | {parses} | {detail} |"
        )
    return "\n".join(lines)


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

    archived = None
    if not args.no_vault:
        try:
            archived = vault.save(raw)
        except OSError as exc:  # a failed archive must not cost the bundle
            print(f"warning: vault archive failed: {exc}", file=sys.stderr)
    out = render_json(bundle) if args.json else render_markdown(bundle)
    if args.out:
        dest = Path(args.out)
        dest.write_text(out, encoding="utf-8")
        print(f"bundle written: {dest} ({len(out)} chars)")
        _vault_footer(bundle, raw, archived, out, dest)
    else:
        print(out)
    return 0


def _cmd_resume(args: argparse.Namespace) -> int:
    try:
        bundle = load_bundle(args.bundle)
    except (OSError, ValueError) as e:
        print(f"error: cannot read bundle: {e}", file=sys.stderr)
        return 1
    budget = args.max_chars
    if args.depth == "full":
        budget = 10**9  # explicit opt-in: no paste window to fit into
    brief = render_brief(
        bundle,
        lang=args.lang,
        max_chars=budget,
        with_pack=args.depth != "brief",
    )
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


def _cmd_ui(args: argparse.Namespace) -> int:
    """Serve the local cockpit WebUI (requires agenthandoff[server])."""
    try:
        from agent_handoff.server.app import run_server
    except ImportError:
        print("error: server extras missing — pip install 'agenthandoff[server]'", file=sys.stderr)
        return 1
    import webbrowser

    url = f"http://{args.host}:{args.port}"
    print(f"cockpit: {url}  (Ctrl+C to stop)")
    if args.open:
        webbrowser.open(url)
    run_server(host=args.host, port=args.port)
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

    p_doc = sub.add_parser(
        "doctor", help="probe which CLI stores exist, are readable, and actually parse"
    )
    p_doc.add_argument(
        "--markdown", action="store_true", help="emit this machine's support table as markdown"
    )

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
        "--no-vault",
        action="store_true",
        help="skip the lossless archive (capture normally stores the full extraction)",
    )
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

    p_srch = sub.add_parser(
        "search",
        help="search every session: titles/paths are instant, --body adds message text",
    )
    p_srch.add_argument("query", help="search string (at least 2 characters)")
    p_srch.add_argument("--cli", help="restrict to one cli")
    p_srch.add_argument(
        "--body",
        action="store_true",
        help="also match message bodies (first run indexes every session once, ~15s)",
    )
    p_srch.add_argument("-n", "--limit", type=int, default=50, help="max hits (default 50)")
    p_srch.add_argument("--json", action="store_true", help="emit hits as JSON")
    p_srch.add_argument("--reindex", action="store_true", help="drop the cached index and rebuild")

    p_bu = sub.add_parser("backup", help="archive all session stores to a timestamped directory")
    p_bu.add_argument(
        "--dest", help="destination directory (default: ~/.agenthandoff/backups/backup-<ts>)"
    )

    p_vault = sub.add_parser(
        "vault",
        help="the lossless archive: what capture kept, and how to get it back",
    )
    p_vault.add_argument(
        "action",
        nargs="?",
        choices=["list", "show", "check", "restore"],
        help="list (default) | show | check | restore",
    )
    p_vault.add_argument("cli", nargs="?", help="cli id, for show/check/restore")
    p_vault.add_argument("session", nargs="?", help="session id, for show/check/restore")
    p_vault.add_argument("--out", help="restore: destination .json path (default: stdout)")
    p_vault.add_argument("-n", type=int, default=20, help="list: max rows (default 20)")

    p_ui = sub.add_parser("ui", help="serve the local cockpit WebUI (needs [server] extra)")
    p_ui.add_argument("--host", default="127.0.0.1")
    p_ui.add_argument("--port", type=int, default=8620)
    p_ui.add_argument("--open", action="store_true", help="open the browser automatically")

    p_mtx = sub.add_parser(
        "matrix",
        help="print the support matrix derived from the shipped fixtures (never hand-written)",
    )
    p_mtx.add_argument("--json", action="store_true", help="emit rows + summary as JSON")
    p_mtx.add_argument(
        "--lang", choices=["en", "zh"], default="en", help="table language (default en)"
    )
    p_mtx.add_argument(
        "--markdown",
        action="store_true",
        help="emit the README block (emoji cells) instead of the console table",
    )

    p_ev = sub.add_parser(
        "evidence",
        help="check (or regenerate) that README/JSON match the fixtures; maintainer-facing",
    )
    ev_group = p_ev.add_mutually_exclusive_group()
    ev_group.add_argument(
        "--check", action="store_true", default=True, help="exit non-zero when stale (default)"
    )
    ev_group.add_argument(
        "--write", action="store_true", help="rewrite the README block and support-matrix.json"
    )

    p_res = sub.add_parser("resume", help="generate a continuation brief from a bundle")
    p_res.add_argument("bundle", help="path to a bundle .md or .json file")
    p_res.add_argument("--max-chars", type=int, default=12000, help="brief budget (default 12000)")
    p_res.add_argument("--lang", choices=["en", "zh"], default="en", help="scaffolding language")
    p_res.add_argument("--out", help="write brief to file (default: stdout)")
    p_res.add_argument(
        "--depth",
        choices=["brief", "resume", "full"],
        default="resume",
        help="brief: no verbatim tail; resume: protected tail (default); full: ignore the budget",
    )

    return ap


def _cmd_search(args: argparse.Namespace) -> int:
    query = args.query.strip()
    if len(query) < 2:
        print("error: query needs at least 2 characters", file=sys.stderr)
        return 2

    def progress(done: int, total: int) -> None:
        if not sys.stderr.isatty():
            return
        sys.stderr.write(f"\rindexing {done}/{total} sessions…      ")
        sys.stderr.flush()

    hits, stats = ah_search.search_with_stats(
        query,
        cli=args.cli,
        limit=args.limit,
        mode="full" if args.body else "fast",
        on_progress=progress if args.body else None,
        reindex=args.reindex,
    )
    if args.body and sys.stderr.isatty():
        sys.stderr.write("\r" + " " * 44 + "\r")

    if args.json:
        print(json.dumps([h.to_dict() for h in hits], ensure_ascii=False, indent=2))
        return 0
    if not hits:
        print("no hits. Try a shorter term, or --body to search message text.")
        return 1
    for h in hits:
        cwd = h.cwd or "?"
        print(f'{h.cli:<14} {h.session_id[:24]} "{h.title[:52]}" ({cwd})')
        tag = f"[{h.matched}] " if h.matched else ""
        print(f"  {tag}{h.excerpt[:160]}")
    print(
        f"{len(hits)} hit(s) \u00b7 scanned {stats.scanned} session(s) in {stats.took_ms} ms"
        f" \u00b7 index {stats.index_state} ({stats.indexed}/{stats.total})"
    )
    return 0


def _cmd_matrix(args: argparse.Namespace) -> int:
    """The support matrix, computed from the fixtures in this repo."""
    from agent_handoff import matrix as ah_matrix

    rows = ah_matrix.build_rows()
    if args.json:
        print(
            json.dumps(
                {"rows": [r.to_dict() for r in rows], "summary": ah_matrix.summary(rows)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.markdown:
        from agent_handoff import evidence

        print(evidence.render_block(args.lang, rows))
        return 0
    print(ah_matrix.render_markdown(args.lang, rows, ascii_cell=True))
    print(f"\nsummary: {ah_matrix.summary(rows)}")
    gaps = ah_matrix.unproven(rows)
    if gaps:
        print("unproven readers (no fixture yet): " + ", ".join(gaps))
    print('reproduce: pip install -e ".[dev]" && python -m agent_handoff.evidence --check')
    return 0


def _cmd_evidence(args: argparse.Namespace) -> int:
    from agent_handoff import evidence

    argv = ["--write"] if getattr(args, "write", False) else ["--check"]
    return evidence.main(argv)


def _cmd_backup(args: argparse.Namespace) -> int:
    from agent_handoff.backup import backup

    dest = Path(args.dest) if args.dest else None
    out = backup(dest)
    print(f"backup written: {out}")
    return 0


def _vault_footer(bundle, raw, archived, out: str, dest) -> None:
    """One stderr line: where the lossless copy is, and how lossy this view is."""
    if dest is None:
        return
    print(vault.fidelity_note(bundle, raw, len(out)), file=sys.stderr)
    where = f"archived: {archived}" if archived else "archive already current"
    print(where, file=sys.stderr)


def _cmd_vault(args: argparse.Namespace) -> int:
    """list | show | check | restore - the copy that outlives a store's own cleanup."""
    action = args.action or "list"

    if action == "list":
        rows = vault.entries()
        if not rows:
            print("vault is empty - `handoff capture` archives every session it reads")
            return 0
        for row in rows[: args.n]:
            cli = row["cli"]
            sid = row["session_id"][:24]
            turns = row["message_count"]
            saved = row["saved_at"]
            title = row["title"][:38]
            print(f"{cli:<14} {sid:<26} {turns:>5} turns  {saved:<25} {title}")
        total = sum(r["bytes"] for r in rows) / 1e6
        print(f"{len(rows)} archived session(s), {total:.1f} MB under {vault.vault_root()}")
        return 0

    if args.session is None:
        print(f"error: `vault {action}` needs <cli> <session-id>", file=sys.stderr)
        return 2

    doc = vault.read_doc(args.cli, args.session)
    if doc is None:
        print(f"error: nothing archived for {args.cli}/{args.session}", file=sys.stderr)
        return 1

    if action == "show":
        return _vault_show(doc, args)

    if action == "check":
        return _vault_check(args)

    payload = json.dumps(doc.get("session"), ensure_ascii=False, indent=2)
    if args.out:
        dest = Path(args.out)
        dest.write_text(payload, encoding="utf-8")
        print(f"restored {len(payload)} chars -> {dest}")
    else:
        print(payload)
    return 0


def _vault_show(doc: dict, args: argparse.Namespace) -> int:
    session = doc.get("session") or {}
    meta = session.get("meta") or {}
    digest = str(doc.get("content_sha256"))[:16]
    print(f"saved_at: {doc.get('saved_at')}  sha256: {digest}...")
    print(f"title:    {meta.get('title')}")
    turns = len(session.get("messages") or [])
    files = len(session.get("files_touched") or {})
    print(f"turns:    {turns}  files: {files}")
    print(f"path:     {vault.path_for(args.cli, args.session)}")
    return 0


def _vault_check(args: argparse.Namespace) -> int:
    """Has the vendor's store shrunk under us? Then the vault is the only copy."""
    try:
        _parser, live = resolve_session(args.session, cli=args.cli)
    except FileNotFoundError as exc:
        print(f"error: cannot read the live store: {exc}", file=sys.stderr)
        return 1
    report = vault.check(args.cli, args.session, live)
    for key, value in report.items():
        print(f"{key}: {value}")
    if report["state"] == "store-shrank":
        missing = report.get("turns_only_in_vault", 0)
        print(
            f"\nALARM: the store dropped {missing} turn(s) the vault still holds. "
            "This archive may be the only copy - restore it with `handoff vault restore`.",
            file=sys.stderr,
        )
        return 3
    return 0


_HANDLERS = {
    "doctor": _cmd_doctor,
    "list": _cmd_list,
    "capture": _cmd_capture,
    "resume": _cmd_resume,
    "publish": _cmd_publish,
    "inbox": _cmd_inbox,
    "claim": _cmd_claim,
    "threads": _cmd_threads,
    "ui": _cmd_ui,
    "search": _cmd_search,
    "matrix": _cmd_matrix,
    "evidence": _cmd_evidence,
    "backup": _cmd_backup,
    "vault": _cmd_vault,
}


def _survive_console_codepage() -> None:
    """Report something, even when the console cannot spell it.

    A zh-CN Windows console is cp936 and a Western one is cp1252; neither can
    encode `✓`, so printing the support matrix used to raise UnicodeEncodeError
    before it could say anything. Replacing unencodable characters keeps the run
    alive and leaves the native code page alone - forcing UTF-8 instead made
    piped output arrive as mojibake, because the reader decodes with the console's
    own code page. Glyphs belong in the Markdown, not in terminal output.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            # A redirected or closed stream is not a reason to stop working.
            with contextlib.suppress(OSError, ValueError):
                stream.reconfigure(errors="replace")


def main(argv: list[str] | None = None) -> int:
    _survive_console_codepage()
    args = build_parser().parse_args(argv)
    return _HANDLERS[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
