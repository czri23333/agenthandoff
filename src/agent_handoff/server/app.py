"""Local web UI server — the cockpit over the deterministic engine.

FastAPI app (extra: `agenthandoff[server]`), bound to 127.0.0.1 only.
REST contract consumed by the React frontend in `web/` (built dist is
shipped inside the wheel). See docs/decisions.md ADR-006/007/008.
"""

from __future__ import annotations

import time
from dataclasses import asdict
from importlib import resources
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent_handoff import memory_export as ah_memory
from agent_handoff import search as ah_search
from agent_handoff import watch as ah_watch
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
from agent_handoff.parsers import all_parsers
from agent_handoff.render import render_markdown
from agent_handoff.resume import render_brief, render_full_brief
from agent_handoff.summarize import build_full_transcript, summarize
from agent_handoff.threads import (
    SessionNode,
    build_threads,
    describe_thread,
    normalize_path,
    title_tokens,
)

app = FastAPI(title="agenthandoff cockpit", version="0.1.0")


def _parser_or_404(cli: str):
    for p in all_parsers():
        if p.cli == cli:
            return p
    raise HTTPException(404, f"unknown cli: {cli}")


def _raw_or_404(cli: str, sid: str):
    raw = _parser_or_404(cli).load(sid)
    if raw is None:
        raise HTTPException(404, f"session not found: {sid}")
    return raw


# -- read APIs ----------------------------------------------------------------

@app.get("/api/stores")
def stores():
    return [
        {
            "cli": s.cli,
            "kind": s.kind,
            "path": str(s.path),
            "readable": s.readable,
            "via_wsl": s.via_wsl,
            "detail": s.detail,
        }
        for s in discover()
    ]


# Session listing re-reads every store; cache briefly so the frontend's
# 30s poll doesn't re-decompress 46 zstd rolls per request (ADR-006).
_sessions_cache: dict[str, tuple[float, list]] = {}
_CACHE_TTL = 20.0


def _domain_for(cwd: str) -> str:
    """Classify a session's project domain — config-driven, never hardcoded
    (ADR-009). Default domain is the cwd itself; ~/.agenthandoff/domains.toml
    may map path patterns (glob prefixes or regex) to user-chosen names.

        [domains]
        "D:/work/ComfyUI" = "h3"
        'regex:D:\\\\引擎.*native' = "rustwebgal"

    First matching rule wins; unmatched sessions keep their cwd.
    """
    cfg = Path.home() / ".agenthandoff" / "domains.toml"
    if cfg.is_file() and cwd:
        try:
            import tomllib  # Python 3.11+
        except ModuleNotFoundError:  # pragma: no cover - the 3.10 leg of CI
            tomllib = None  # type: ignore[assignment]
        if tomllib is not None:
            try:
                rules = tomllib.loads(cfg.read_text(encoding="utf-8")).get("domains", {})
                norm = cwd.replace("\\\\", "/").replace("\\", "/")
                for pattern, name in rules.items():
                    pat = str(pattern)
                    if pat.startswith("regex:"):
                        import re

                        if re.search(pat[6:], norm):
                            return str(name)
                    elif norm.lower().startswith(
                        pat.replace("\\\\", "/").replace("\\", "/").lower().rstrip("/")
                    ):
                        return str(name)
            except (OSError, ValueError, TypeError):
                pass
    return cwd



# Git branch/worktree detection per cwd, cached to avoid repeated subprocess calls.
_git_cache: dict[str, tuple[float, dict]] = {}
_GIT_TTL = 30.0


def _git_info(cwd: str) -> dict:
    """Detect git branch and worktree info for a session cwd. Cached 30s."""
    if not cwd:
        return {}
    now = time.monotonic()
    hit = _git_cache.get(cwd)
    if hit and now - hit[0] < _GIT_TTL:
        return hit[1]
    import subprocess
    info: dict = {}
    try:
        r = subprocess.run(
            ["git", "-C", cwd, "branch", "--show-current"],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0 and r.stdout.strip():
            info["branch"] = r.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        r = subprocess.run(
            ["git", "-C", cwd, "worktree", "list", "--porcelain"],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0:
            worktrees = [
                w.split(" ", 1)[1]
                for w in r.stdout.splitlines()
                if w.startswith("worktree ")
            ]
            if len(worktrees) > 1:
                info["worktree_count"] = len(worktrees)
    except (OSError, subprocess.TimeoutExpired):
        pass
    _git_cache[cwd] = (now, info)
    return info


@app.get("/api/sessions")
def sessions(cli: str | None = None, cwd: str | None = None, q: str | None = None):
    cache_key = f"{cli}|{cwd}|{q}"
    now = time.monotonic()
    hit = _sessions_cache.get(cache_key)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]

    out = []
    for p in all_parsers():
        if cli and p.cli != cli:
            continue
        for m in p.list_sessions():
            if cwd and cwd.lower() not in m.cwd.lower():
                continue
            if q and q.lower() not in m.title.lower():
                continue
            out.append(
                {
                    "cli": m.cli,
                    "session_id": m.session_id,
                    "title": m.title,
                    "cwd": m.cwd,
                    "started_at": m.started_at,
                    "updated_at": m.updated_at,
                    "model": m.model,
                    "provider": m.provider,
                    "origin": m.origin,
                    "parent_session_id": m.parent_session_id,
                    # proven end-state where the store has a cheap signal;
                    # null means unknown (never faked as clean)
                    "status": p.peek_status(m.session_id),
                    # Agent-View-style "Needs input": ends on an un-answered user
                    # message (cheap tail probe; null = store has no probe)
                    "needs_reply": p.peek_needs_reply(m.session_id),
                    # config-driven project domain (ADR-009): cwd by default
                    "domain": _domain_for(m.cwd),
                    # live git branch/worktree for the session cwd (cached 30s)
                    **({"git": g} if (g := _git_info(m.cwd)) else {}),
                }
            )
    out.sort(key=lambda s: s["updated_at"] or "", reverse=True)
    # Windows paths vary in case; merge domain variants, keeping the most
    # frequent original spelling for display.
    merge: dict[str, dict[str, int]] = {}
    for s in out:
        key = s["domain"].casefold()
        merge.setdefault(key, {})
        merge[key][s["domain"]] = merge[key].get(s["domain"], 0) + 1
    canonical = {k: max(v, key=v.get) for k, v in merge.items()}
    for s in out:
        s["domain"] = canonical[s["domain"].casefold()]
    _sessions_cache[cache_key] = (now, out)
    return out


@app.get("/api/sessions/{cli}/{sid}/detail")
def session_detail(cli: str, sid: str, lang: str = "en", max_chars: int = 12000):
    raw = _raw_or_404(cli, sid)
    bundle = summarize(raw)

    # Transcript with honest compaction markers: long sessions get compacted
    # many times and everything before a marker exists only as a summary.
    # Hiding that would present a truncated history as complete.
    stream: list[dict] = [
        {
            "role": m.role,
            "text": m.text[:2000],
            "at": m.at,
            # per-turn billing: which model answered, what it cost in tokens
            **({"model": m.model} if m.model else {}),
            **({"tokens_in": m.tokens_in} if m.tokens_in is not None else {}),
            **({"tokens_out": m.tokens_out} if m.tokens_out is not None else {}),
            **({"tokens_reasoning": m.tokens_reasoning} if m.tokens_reasoning is not None else {}),
            **({"subagent": m.subagent} if m.subagent else {}),
        }
        for m in raw.messages
    ]
    markers: list[dict] = [
        {
            "role": "compaction",
            "text": f"#{n} · {c.reason or 'unknown'} · "
            f"{c.pre_tokens if c.pre_tokens is not None else '?'} → "
            f"{c.post_tokens if c.post_tokens is not None else '?'} tokens",
            "at": c.at,
        }
        for n, c in enumerate(raw.compactions, 1)
    ]
    if markers:
        stream = sorted(stream + markers, key=lambda x: x["at"] or "")[-400:]

    # The same measurement `handoff watch` ladder-steps, read-only: the UI must
    # not show a fuller or emptier session than the snapshots claim.
    parser = _parser_or_404(cli)
    fill, basis = ah_watch.context_fill(parser, raw)
    state = ah_watch.load_state(cli, sid)
    rungs = (
        [f"{int(r * 100)}%" for r in ah_watch.LADDER]
        if fill is not None
        else [f"t{n}" for n in ah_watch.TURN_LADDER]
    )
    budget = {
        "fill": fill,
        "basis": basis,
        "turns": len(raw.messages),
        "fired": sorted(state.fired),
        "pending": [label for label in rungs if label not in state.fired_labels],
        "last_snapshot": state.snapshots[-1] if state.snapshots else "",
    }

    return {
        "bundle": bundle.to_dict(),
        "budget": budget,
        "markdown": render_markdown(bundle),
        "brief": render_brief(bundle, lang=lang, max_chars=max_chars),
        "interruption": {
            "kind": bundle.interruption.kind,
            "detail": bundle.interruption.detail,
            "pending_user_text": bundle.interruption.pending_user_text,
        },
        "topics": [{"opener": o, "messages": n} for o, n in bundle.topics],
        "usage": _parser_or_404(cli).usage(sid),
        "compactions": len(raw.compactions),
        "messages": stream[::-1],
    }


@app.get("/api/sessions/{cli}/{sid}/brief")
def session_brief(
    cli: str,
    sid: str,
    lang: str = "zh",
    depth: str = "full",
    keep_noise: bool = False,
):
    """The paste-ready continuation brief, generated without any CLI.

    depth=full resolves the ENTIRE dialogue (noise-filtered unless keep_noise)
    and renders the lossless brief; depth=resume falls back to the budgeted
    12 000-char brief the detail view already shows.
    """
    raw = _raw_or_404(cli, sid)
    bundle = summarize(raw)
    if depth == "full":
        transcript = build_full_transcript(raw, keep_noise=keep_noise)
        brief = render_full_brief(bundle, transcript, lang=lang)
    else:
        brief = render_brief(bundle, lang=lang, max_chars=12000)
    return {
        "brief": brief,
        "chars": len(brief),
        "turns": (
            len(build_full_transcript(raw, keep_noise=keep_noise))
            if depth == "full"
            else len(bundle.recent)
        ),
    }


@app.get("/api/sessions/{cli}/{sid}/raw")
def session_raw(cli: str, sid: str):
    """The session's ORIGINAL storage as a zip: byte-faithful files, hash-
    verified inside the archive. This is the verbatim layer — the brief only
    summarises, the zip is the unfiltered truth (tool calls, system rows,
    vendor fields no parser reads).
    """
    import io
    import zipfile
    from pathlib import Path as _Path

    parser = _parser_or_404(cli)
    archive = parser.raw_archive(sid)
    if archive is None:
        raise HTTPException(status_code=404, detail=f"{cli} cannot archive session {sid} verbatim")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in archive:
            data = str(entry.get("text") or "").encode("utf-8", "surrogateescape")
            zf.writestr(_Path(entry.get("path") or "unnamed").as_posix(), data)
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{cli}-{sid[:8]}-raw.zip"'
        },
    )


# Threads clusters every session across every store (~15s live); cache the
# result and let "recluster" bust it explicitly.
_threads_cache: dict[tuple, tuple[float, list]] = {}
_THREADS_TTL = 600.0


@app.get("/api/threads")
def threads(cwd: str | None = None, min_overlap: float = 0.15, window_days: int = 21):
    key = (cwd, min_overlap, window_days)
    now = time.monotonic()
    hit = _threads_cache.get(key)
    if hit and now - hit[0] < _THREADS_TTL:
        return hit[1]

    nodes: list[SessionNode] = []
    for p in all_parsers():
        for m in p.list_sessions():
            if cwd and cwd.lower() not in m.cwd.lower():
                continue
            raw = p.load(m.session_id)
            files = {normalize_path(f) for f in raw.files_touched} if raw else set()
            nodes.append(SessionNode(meta=m, files=files, tokens=title_tokens(m.title)))
    result = []
    for t in sorted(
        build_threads(nodes, min_jaccard=min_overlap, window_days=window_days),
        key=lambda t: len(t.sessions),
        reverse=True,
    ):
        result.append(
            {
                "lines": describe_thread(t),
                "session_ids": [s.meta.session_id for s in t.sessions],
                "clis": t.clis,
                "last_active": t.last_active,
            }
        )
    _threads_cache[key] = (now, result)
    return result


@app.get("/api/inbox")
def inbox(global_scope: bool = False):
    return [
        {
            "path": str(i.path),
            "title": i.title,
            "cli": i.cli,
            "session_id": i.session_id,
            "published_at": i.published_at,
            "claimed": i.claimed,
            "claimed_by": i.claimed_by,
            "leased": i.leased,
            "lease_by": i.lease_by,
            "lease_until": i.lease_until,
        }
        for i in exchange_inbox(global_scope=global_scope)
    ]


# -- write APIs (explicit actions from the cockpit) ---------------------------

class PublishBody(BaseModel):
    cli: str
    session_id: str
    note: str | None = None
    global_scope: bool = False
    lease_minutes: float | None = None


@app.post("/api/publish")
def publish(body: PublishBody):
    raw = _raw_or_404(body.cli, body.session_id)
    bundle = summarize(raw)
    dest = Path.cwd() / "handoff-export.md"
    dest.write_text(render_markdown(bundle), encoding="utf-8")
    published = exchange_publish(
        dest,
        global_scope=body.global_scope,
        note=body.note,
        lease_minutes=body.lease_minutes,
    )
    dest.unlink(missing_ok=True)
    return {"published": str(published), "lease": exchange_lease_of(published)}


class ClaimBody(BaseModel):
    path: str
    by: str | None = None
    force: bool = False


@app.post("/api/claim")
def claim(body: ClaimBody):
    """A held lease is a conflict the caller must see, not a silent success."""
    try:
        sidecar = exchange_claim(Path(body.path), claimed_by=body.by, force=body.force)
    except AlreadyClaimed as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"claimed": str(sidecar)}


class ReleaseBody(BaseModel):
    path: str
    by: str | None = None
    force: bool = False


@app.post("/api/release")
def release(body: ReleaseBody):
    try:
        dropped = exchange_release(Path(body.path), owner=body.by, force=body.force)
    except AlreadyClaimed as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"released": dropped}


# -- launcher registry (ADR-007: verified doors only) --------------------------

_LAUNCHERS = {
    "dsh": {
        "kind": "verified",
        "resume": "dsh --resume {session_id}",
        "headless": "dsh run --profile headless -p",
    },
    "kimi": {"kind": "verified", "resume": "kimi --resume {session_id}"},
    "codex": {"kind": "verified", "resume": "codex resume {session_id}", "headless": "codex exec"},
    "claude": {"kind": "unverified", "resume": "claude --resume {session_id}"},
}


@app.get("/api/search")
def search_api(
    q: str,
    cli: str | None = None,
    mode: str = "full",
    limit: int = 50,
):
    """Ranked hits plus honest coverage stats.

    ``mode=fast`` matches metadata only (no session loads, works on a cold
    index); ``mode=full`` matches message bodies out of the warm index and
    never blocks on I/O — while the index is still building, ``stats`` says so
    and the UI shows progress instead of a silently partial list.
    """
    if len(q.strip()) < 2:
        raise HTTPException(400, "query too short (>= 2 chars)")
    if mode not in ("fast", "full"):
        raise HTTPException(400, "mode must be fast|full")
    if mode == "full" and ah_search.index_status()["state"] == "idle":
        ah_search.warm_async()  # first full query starts the background index
    hits, stats = ah_search.search_cached(q, cli=cli, limit=min(limit, 200), mode=mode)
    return {"hits": [h.to_dict() for h in hits], "stats": asdict(stats)}


@app.get("/api/search/status")
def search_status():
    """Index build state: {state, done, total, indexed, error}."""
    return ah_search.index_status()


@app.post("/api/search/warm")
def search_warm():
    """Kick (or join) the background index build. Returns immediately."""
    return ah_search.warm_async()


@app.get("/api/heartbeat")
def heartbeat():
    """Cheap liveness + session count used by the toolbar tile."""
    n = 0
    for p in all_parsers():
        n += len(p.list_sessions())
    return {"sessions": n}


@app.post("/api/backup")
def backup_api():
    """Snapshot every store to disk. POST, not GET: this writes."""
    from agent_handoff.backup import backup

    dest = backup()
    return {"path": str(dest)}


@app.get("/api/launcher/{cli}/{sid}")
def launcher(cli: str, sid: str):
    entry = _LAUNCHERS.get(cli)
    if entry is None:
        raise HTTPException(404, f"no launcher for {cli}")
    return {
        "cli": cli,
        "kind": entry["kind"],
        "command": entry["resume"].format(session_id=sid),
        "headless": entry.get("headless"),
    }


@app.get("/api/memory-export")
def memory_export_api(cli: str | None = None, with_project: bool = True):
    """The memory-export page data. Same honesty contract as the CLI:
    missing stores stay listed; secret flags carry no text."""
    if cli is not None and cli not in ah_memory.known_clis():
        raise HTTPException(404, f"unknown cli: {cli} (known: {', '.join(ah_memory.known_clis())})")
    project = Path.cwd() if with_project else None
    entries, reports = ah_memory.scan_sources(project=project, cli=cli)
    blob = "\n".join(e.text for e in entries)
    return {
        "entries": [asdict(e) for e in ah_memory._sorted_entries(entries)],
        "reports": [asdict(r) for r in reports],
        "secret_flags": ah_memory.scan_secrets(blob),
        "completeness": {
            "read": sum(1 for r in reports if r.status == "read"),
            "total": len(reports),
        },
        "markdown_en": ah_memory.render(entries, reports, lang="en"),
        "markdown_zh": ah_memory.render(entries, reports, lang="zh"),
        "completeness_en": "\n".join(ah_memory._completeness_lines(reports, "en")),
        "completeness_zh": "\n".join(ah_memory._completeness_lines(reports, "zh")),
    }


# -- static frontend -----------------------------------------------------------

def _static_dir() -> Path | None:
    try:
        res = resources.files("agent_handoff").joinpath("server/static")
        if res.is_dir():
            return Path(str(res))
    except (ModuleNotFoundError, FileNotFoundError):
        pass
    local = Path(__file__).parent / "static"
    return local if local.is_dir() else None


def _index_html() -> Path | None:
    d = _static_dir()
    idx = d / "index.html" if d else None
    return idx if idx and idx.exists() else None


@app.get("/")
def index():
    idx = _index_html()
    if idx is None:
        raise HTTPException(503, "frontend not built — run: cd web && npm run build")
    return FileResponse(idx)


_static = _static_dir()
if _static is not None and (_static / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=_static / "assets"), name="assets")


def run_server(host: str = "127.0.0.1", port: int = 8620) -> None:
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    run_server()
