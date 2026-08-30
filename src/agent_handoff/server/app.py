"""Local web UI server — the cockpit over the deterministic engine.

FastAPI app (extra: `agenthandoff[server]`), bound to 127.0.0.1 only.
REST contract consumed by the React frontend in `web/` (built dist is
shipped inside the wheel). See docs/decisions.md ADR-006/007/008.
"""

from __future__ import annotations

import time
from importlib import resources
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent_handoff.exchange import claim as exchange_claim
from agent_handoff.exchange import inbox as exchange_inbox
from agent_handoff.exchange import publish as exchange_publish
from agent_handoff.locations import discover
from agent_handoff.parsers import all_parsers
from agent_handoff.render import render_markdown
from agent_handoff.resume import render_brief
from agent_handoff.summarize import summarize
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
                }
            )
    out.sort(key=lambda s: s["updated_at"] or "", reverse=True)
    _sessions_cache[cache_key] = (now, out)
    return out


@app.get("/api/sessions/{cli}/{sid}/detail")
def session_detail(cli: str, sid: str, lang: str = "en", max_chars: int = 12000):
    raw = _raw_or_404(cli, sid)
    bundle = summarize(raw)
    return {
        "bundle": bundle.to_dict(),
        "markdown": render_markdown(bundle),
        "brief": render_brief(bundle, lang=lang, max_chars=max_chars),
        "interruption": {
            "kind": bundle.interruption.kind,
            "detail": bundle.interruption.detail,
            "pending_user_text": bundle.interruption.pending_user_text,
        },
        "topics": [{"opener": o, "messages": n} for o, n in bundle.topics],
    }


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
        }
        for i in exchange_inbox(global_scope=global_scope)
    ]


# -- write APIs (explicit actions from the cockpit) ---------------------------

class PublishBody(BaseModel):
    cli: str
    session_id: str
    note: str | None = None
    global_scope: bool = False


@app.post("/api/publish")
def publish(body: PublishBody):
    raw = _raw_or_404(body.cli, body.session_id)
    bundle = summarize(raw)
    dest = Path.cwd() / "handoff-export.md"
    dest.write_text(render_markdown(bundle), encoding="utf-8")
    published = exchange_publish(dest, global_scope=body.global_scope, note=body.note)
    dest.unlink(missing_ok=True)
    return {"published": str(published)}


class ClaimBody(BaseModel):
    path: str
    by: str | None = None


@app.post("/api/claim")
def claim(body: ClaimBody):
    sidecar = exchange_claim(Path(body.path), claimed_by=body.by)
    return {"claimed": str(sidecar)}


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
