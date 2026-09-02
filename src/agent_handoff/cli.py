"""Command-line interface: handoff doctor|list|capture|resume|publish|inbox|claim."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

from agent_handoff import __version__, memory_export, vault
from agent_handoff import search as ah_search
from agent_handoff.exchange import (
    AlreadyClaimed,
)
from agent_handoff.exchange import (
    claim as exchange_claim,
)
from agent_handoff.exchange import (
    inbox as exchange_inbox,
)
from agent_handoff.exchange import (
    lease_of as exchange_lease_of,
)
from agent_handoff.exchange import (
    publish as exchange_publish,
)
from agent_handoff.exchange import (
    release as exchange_release,
)
from agent_handoff.locations import discover
from agent_handoff.parsers import available_parsers, resolve_session
from agent_handoff.render import load_bundle, render_json, render_markdown
from agent_handoff.resume import render_brief, render_full_brief
from agent_handoff.summarize import build_full_transcript, summarize


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
    if getattr(args, "full", False):
        bundle.full_transcript = build_full_transcript(
            raw, keep_noise=getattr(args, "keep_noise", False)
        )
    if getattr(args, "raw", False):
        archive = _parser.raw_archive(ref if ref != "latest" else raw.meta.session_id)
        if archive is None:
            print(
                f"warning: {_parser.cli} has no per-session raw archive; "
                "the bundle carries the parsed transcript only",
                file=sys.stderr,
            )
        else:
            bundle.raw_files = archive
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
        _next_step(f"handoff resume {dest.name} --lang zh   # paste into the next session")
    else:
        print(out)
    return 0


def _resolve_full_transcript(bundle, args) -> list[tuple[str, str]]:
    """Full dialogue for a lossless brief, from the best available source.

    Order of preference:
    1. The bundle's own ``full_transcript`` (capture --full) — portable.
    2. The lossless vault archive (same machine, lossless round-trip).
    3. A fresh re-parse of the source session store.
    Falls back to the bundle's recent tail when nothing else is reachable.
    """
    if bundle.full_transcript:
        return list(bundle.full_transcript)
    keep_noise = getattr(args, "keep_noise", False)
    cli = bundle.meta.cli
    sid = bundle.meta.session_id
    # Vault first — it is the guaranteed-lossless local copy.
    try:
        from agent_handoff import vault

        raw = vault.load(cli, sid)
        if raw is not None:
            return build_full_transcript(raw, keep_noise=keep_noise)
    except Exception:
        pass
    # Then re-parse the live source store.
    try:
        _parser, raw = resolve_session(sid, cli=cli)
        return build_full_transcript(raw, keep_noise=keep_noise)
    except (FileNotFoundError, Exception):
        pass
    return list(bundle.recent)


def dump_raw_files(bundle, dest: Path) -> list[tuple[str, bool]] | None:
    """Extract the bundle's byte-faithful raw storage; verify each sha256.

    Returns (path, ok) pairs, or None when the bundle carries no raw archive.
    """
    if not bundle.raw_files:
        return None
    import hashlib

    out: list[tuple[str, bool]] = []
    for entry in bundle.raw_files:
        rel = str(entry.get("path") or "unnamed")
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        data = str(entry.get("text") or "").encode("utf-8", "surrogateescape")
        target.write_bytes(data)
        ok = hashlib.sha256(data).hexdigest() == str(entry.get("sha256"))
        out.append((str(target), ok))
    return out


def _cmd_resume(args: argparse.Namespace) -> int:
    try:
        bundle = load_bundle(args.bundle)
    except (OSError, ValueError) as e:
        print(f"error: cannot read bundle: {e}", file=sys.stderr)
        return 1
    if getattr(args, "dump_raw", None):
        dest = dump_raw_files(bundle, Path(args.dump_raw))
        if dest is None:
            print("error: bundle carries no raw archive", file=sys.stderr)
            return 1
        for path, ok in dest:
            print(f"  {'ok ' if ok else 'MISMATCH'} {path}")
        print(f"raw storage extracted: {len(dest)} file(s) -> {Path(args.dump_raw)}")
    if args.depth == "full":
        transcript = _resolve_full_transcript(bundle, args)
        brief = render_full_brief(bundle, transcript, lang=args.lang)
    else:
        brief = render_brief(
            bundle,
            lang=args.lang,
            max_chars=args.max_chars,
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
            lease_minutes=args.lease_minutes,
            owner=args.owner,
        )
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    scope = "global" if args.to_global else "project"
    print(f"published ({scope}): {dest}")
    _next_step("handoff inbox   # the other agent runs this, then claim/release")
    held = exchange_lease_of(dest)
    if held:
        print(f"  leased by {held.get('leased_by')} until {held.get('until')}")
    return 0


def _cmd_inbox(args: argparse.Namespace) -> int:
    items = exchange_inbox(global_scope=args.to_global)
    if not items:
        scope = "global" if args.to_global else "project"
        print(f"inbox empty ({scope}).")
        return 0
    print(f"{'published':<18} {'cli':<12} {'status':<26} title")
    print("-" * 100)
    for it in items:
        # A lease has to be visible here: this is where an agent decides whether
        # to take the work, and "open" while somebody holds it is a lie.
        if it.leased:
            status = f"leased({it.lease_by[:10]}→{it.lease_until[11:16]})"
        elif it.claimed:
            status = f"claimed({it.claimed_by[:12]})"
        else:
            status = "open"
        print(f"{it.published_at:<18} {it.cli:<12} {status:<26} {it.title[:44]}")
        print(f"{'':<18} file: {it.path}")
    return 0


def _cmd_claim(args: argparse.Namespace) -> int:
    try:
        sidecar = exchange_claim(Path(args.bundle), claimed_by=args.by, force=args.force)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except AlreadyClaimed as e:
        # Exit 3: somebody else has this one. The message names the holder and the
        # deadline instead of a bare "failed", so a script can branch on it.
        print(f"not available: {e}", file=sys.stderr)
        return 3
    print(f"claimed: {sidecar}")
    _next_step(f"handoff capture {Path(args.bundle).name} --cli ...   # or open the session")
    return 0


def _cmd_release(args: argparse.Namespace) -> int:
    try:
        dropped = exchange_release(Path(args.path), owner=args.by, force=args.force)
    except AlreadyClaimed as e:
        print(f"not available: {e}", file=sys.stderr)
        return 3
    if not dropped:
        print("nothing to release (no lease on that bundle)")
        return 0
    print(f"released: {args.path}")
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
    sub = ap.add_subparsers(dest="cmd")

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
    p_cap.add_argument(
        "--full",
        action="store_true",
        help="embed the ENTIRE dialogue verbatim in the bundle (lossless handoff body)",
    )
    p_cap.add_argument(
        "--raw",
        action="store_true",
        help="with --full: also embed the session's ORIGINAL storage, byte-faithful "
        "(tool calls, system rows, unknown vendor fields \u2014 nothing re-derived)",
    )
    p_cap.add_argument(
        "--keep-noise",
        action="store_true",
        help="with --full: keep harness-injected noise instead of filtering it",
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

    p_pub.add_argument(
        "--lease-minutes",
        type=float,
        help="hold the published handoff for N minutes so no other agent claims it",
    )
    p_pub.add_argument(
        "--owner",
        help="who the lease belongs to (default: hostname; match it in claim --by)",
    )

    p_rel = sub.add_parser("release", help="drop a lease you placed on a handoff")
    p_rel.add_argument("path", help="the published bundle path")
    p_rel.add_argument("--by", help="lease holder to verify (default: do not verify)")
    p_rel.add_argument("--force", action="store_true", help="drop it whoever holds it")

    p_clm = sub.add_parser("claim", help="mark a published handoff as taken")
    p_clm.add_argument("bundle", help="path to the published bundle")
    p_clm.add_argument("--by", help="who is claiming (default: hostname)")
    p_clm.add_argument(
        "--force",
        action="store_true",
        help="claim it even while another agent holds a lease",
    )

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

    sub.add_parser("guide", help="print the whole loop, with this machine's state")

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

    p_watch = sub.add_parser(
        "watch",
        help="snapshot a running session at budget rungs, before a quota death",
    )
    p_watch.add_argument(
        "session", nargs="?", default="latest", help="session id or fragment (default latest)"
    )
    p_watch.add_argument("--cli", help="restrict to one CLI (recommended while watching)")
    p_watch.add_argument(
        "--every", type=float, default=60.0, help="seconds between looks (default 60)"
    )
    p_watch.add_argument(
        "--times", type=int, help="stop after N looks (default: until the session vanishes)"
    )
    p_watch.add_argument("--once", action="store_true", help="single look, then exit")
    p_watch.add_argument(
        "--ladder", help="comma-separated context percentages (default 20,45,70,90)"
    )
    p_watch.add_argument(
        "--status", action="store_true", help="print fired rungs and the last snapshot"
    )
    p_watch.add_argument("--out", help="snapshot directory (default ~/.agenthandoff/watch/…)")

    p_res = sub.add_parser("resume", help="generate a continuation brief from a bundle")
    p_res.add_argument("bundle", help="path to a bundle .md or .json file")
    p_res.add_argument("--max-chars", type=int, default=12000, help="brief budget (default 12000)")
    p_res.add_argument("--lang", choices=["en", "zh"], default="en", help="scaffolding language")
    p_res.add_argument("--out", help="write brief to file (default: stdout)")
    p_res.add_argument(
        "--depth",
        choices=["brief", "resume", "full"],
        default="resume",
        help="brief: no verbatim tail; resume: protected tail (default); "
        "full: the ENTIRE dialogue verbatim (lossless)",
    )
    p_res.add_argument(
        "--keep-noise",
        action="store_true",
        help="with --depth full: keep harness-injected noise instead of filtering it",
    )
    p_res.add_argument(
        "--dump-raw",
        default=None,
        metavar="DIR",
        help="extract the bundle's byte-faithful raw storage into DIR (hash-verified)",
    )

    p_mem = sub.add_parser(
        "memory-export",
        help="export standing instructions/memory files across CLIs (five-section format)",
    )
    p_mem.add_argument(
        "--cli", help="restrict to one cli (claude, codex, gemini, kimi-code, zcode)"
    )
    p_mem.add_argument(
        "--project", default=".", help="project dir for AGENTS.md/CLAUDE.md (default: cwd)"
    )
    p_mem.add_argument(
        "--no-project", action="store_true", help="skip the project-level files"
    )
    p_mem.add_argument("--out", help="write to file (default: stdout)")
    p_mem.add_argument("--json", action="store_true", help="machine-readable output")
    p_mem.add_argument(
        "--lang", choices=["en", "zh"], default="en", help="section headings language"
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


def _parse_ladder(spec: str | None):
    from agent_handoff import watch as ah_watch

    if not spec:
        return ah_watch.LADDER
    try:
        rungs = tuple(
            float(part.strip().rstrip("%")) / 100.0
            for part in spec.split(",")
            if part.strip()
        )
    except ValueError as exc:
        raise ValueError("--ladder wants percentages, e.g. 20,45,70,90") from exc
    if not rungs or any(r <= 0 or r > 1 for r in rungs):
        raise ValueError("--ladder values must be between 1 and 100")
    return tuple(sorted(rungs))


def _watch_status_line(state) -> str:
    fired = ", ".join(f"{label}@{when}" for label, when in sorted(state.fired.items())) or "none"
    where = state.snapshots[-1] if state.snapshots else "-"
    return (
        f"{state.cli}/{state.session_id[:24]}: {state.turns} turns, "
        f"fill={state.fill if state.fill is not None else '?'} ({state.basis or 'unknown'})\n"
        f"  fired: {fired}\n"
        f"  last:  {where}"
    )


def _cmd_watch(args: argparse.Namespace) -> int:
    from agent_handoff import watch as ah_watch

    out_dir = Path(args.out) if args.out else None
    try:
        parser, raw = resolve_session(args.session, cli=args.cli)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    session_id = raw.meta.session_id

    if args.status:
        print(_watch_status_line(ah_watch.load_state(parser.cli, session_id)))
        return 0

    try:
        ladder = _parse_ladder(args.ladder)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    iterations = 1 if args.once else args.times

    def report(event: dict, last: dict) -> None:
        archived = event.get("vault") or "vault unavailable"
        print(f"[{last['basis']}] rung {event['rung']}: {event['path']}  ({archived})")

    result = ah_watch.run(
        parser,
        session_id,
        interval=args.every,
        iterations=iterations,
        on_event=report,
        out_dir=out_dir,
        ladder=ladder,
    )
    last = result.get("last") or {}
    if last.get("status") == "gone":
        print("session is no longer in the store - the last snapshot stands", file=sys.stderr)
    pending = ", ".join(last.get("pending", [])) or "none"
    print(
        f"{result['looks']} look(s), {len(result['fired'])} snapshot(s) this run; "
        f"basis={last.get('basis', 'unknown')}; pending: {pending}"
    )
    if last.get("status") == "gone":
        _next_step("handoff watch --status   # the last snapshot is still on disk")
    elif pending:
        _next_step(f"handoff watch --cli {parser.cli} --every {int(args.every)}   # keep watching")
    return 0


GUIDE_STEPS = [
    (
        "看看本机有什么",
        "handoff doctor",
        "which stores exist, are readable, and actually parse - on THIS machine",
    ),
    (
        "找到要接手的会话",
        "handoff list --cli codex -n 10",
        "or `handoff search <关键词> --body` once you know what you were doing",
    ),
    (
        "生成交接包",
        "handoff capture -o handoff.md",
        "the newest session by default; archives a lossless copy to the vault",
    ),
    (
        "喂给下一个 agent",
        "handoff resume handoff.md --lang zh",
        "prints the brief to paste; --depth full ignores the budget",
    ),
    (
        "别等它断了再动手",
        "handoff watch --cli codex --every 60",
        "snapshots at 20/45/70/90% of the context budget, before a quota death",
    ),
    (
        "两个 agent 交替干活",
        "handoff publish handoff.md --lease-minutes 45",
        "then `handoff inbox` / `claim` / `release` - a held handoff refuses others",
    ),
]


def guide_text() -> str:
    """The loop, with this machine's state substituted where it changes the answer."""
    lines = ["agenthandoff - the whole loop, in order", ""]
    for index, (title, command, note) in enumerate(GUIDE_STEPS, 1):
        lines.append(f"{index}. {title}")
        lines.append(f"   $ {command}")
        lines.append(f"   {note}")
        lines.append("")
    try:
        stores = [info for info in discover() if info.readable]
    except OSError:  # a probe must never break the guide
        stores = []
    if stores:
        named = [
            # zcode reports no detail line (a SQLite file is either readable or
            # not), and an empty pair of parentheses reads like a bug.
            f"{info.cli}({info.detail.split(';')[0].strip() or 'readable'})" for info in stores[:8]
        ]
        found = ", ".join(named)
        lines.append(f"本机可读: {found}")
    else:
        lines.append(
            "本机未读到任何会话存储 - 先确认 CLI 至少跑过一次，"
            "或用 --home 指向别的用户目录"
        )
    lines.append("")
    lines.append("每一步都会告诉你下一步做什么；`handoff matrix` 看哪些 CLI 有夹具证据。")
    return "\n".join(lines)


def _cmd_guide(args: argparse.Namespace) -> int:
    print(guide_text())
    return 0


def _next_step(hint: str) -> None:
    """One line on stderr: what to run next. Keeps stdout machine-readable."""
    print(f"next: {hint}", file=sys.stderr)


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


def _cmd_memory_export(args: argparse.Namespace) -> int:
    """Standing instructions across CLIs, exported in the five-section format."""
    if args.cli and args.cli not in memory_export.known_clis():
        known = ", ".join(memory_export.known_clis())
        print(f"error: unknown cli '{args.cli}' (known: {known})", file=sys.stderr)
        return 2
    project = None if args.no_project else Path(args.project)
    if args.json:
        payload = memory_export.export_json(project=project, cli=args.cli)
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    else:
        text = memory_export.export_markdown(
            project=project, cli=args.cli, lang=args.lang
        )
    if args.out:
        try:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
        except OSError as exc:
            print(f"error: cannot write {args.out}: {exc}", file=sys.stderr)
            return 2
        print(f"memory export written to {args.out}")
        return 0
    print(text)
    return 0


_HANDLERS = {
    "doctor": _cmd_doctor,
    "list": _cmd_list,
    "capture": _cmd_capture,
    "resume": _cmd_resume,
    "publish": _cmd_publish,
    "inbox": _cmd_inbox,
    "claim": _cmd_claim,
    "release": _cmd_release,
    "threads": _cmd_threads,
    "ui": _cmd_ui,
    "search": _cmd_search,
    "matrix": _cmd_matrix,
    "guide": _cmd_guide,
    "watch": _cmd_watch,
    "evidence": _cmd_evidence,
    "backup": _cmd_backup,
    "vault": _cmd_vault,
    "memory-export": _cmd_memory_export,
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
    if getattr(args, "cmd", None) is None:
        # Bare `handoff` used to be a usage error. Someone typing the tool's name
        # is asking "what do I do", so answer that instead of scolding them.
        print(guide_text())
        return 0
    return _HANDLERS[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
