"""The lossless layer: a vault copy of every session we ever read.

Why this exists. Everything else in this tool is *lossy on purpose* — bundles
clip items to 220 chars, briefs drop whole sections to fit a character budget,
and the search index caps a session's haystack at 120 KB. That is the right call
for a prompt you paste into the next session. It is the wrong call as the only
copy, because the scenario this tool exists for is the one where the original is
at risk:

  * a vendor compacts a long session and the early turns stop existing;
  * a store rotates/archives roll files and the tail disappears;
  * a profile is cleaned, a tool is uninstalled, a machine is retired.

So the design rule borrowed from how OpenCode handles pruning: **mark, pointer,
never physically drop**. The brief is a *view* with a pointer back to the vault;
the vault holds the full extraction, verified after write.

What is stored: our deterministic extraction of the session (messages, todos,
file anchors, tool counts, interruption evidence, compaction events, usage when
the store exposes it) — not a copy of the vendor's private file. That keeps the
read-only promise (we never touch their store) while still making the context
recoverable.

Storage: plain JSON under ``~/.agenthandoff/vault/<cli>/<session_id>.json``,
written atomically, deduplicated by content hash. Plain JSON because it must stay
greppable and diffable without this tool — a backup you can only read with the
software that made it is a liability.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from agent_handoff.model import (
    CompactionEvent,
    HandoffBundle,
    Interruption,
    Message,
    RawSession,
    SessionMeta,
    TodoItem,
)

VAULT_VERSION = 1


def vault_root() -> Path:
    return Path.home() / ".agenthandoff" / "vault"


def _path_for(cli: str, session_id: str) -> Path:
    # Session ids are opaque tokens in practice, but never trust one: strip
    # anything path-like before it becomes a filename.
    safe_cli = "".join(c for c in cli if c.isalnum() or c in "-_.") or "unknown"
    safe_sid = "".join(c for c in session_id if c.isalnum() or c in "-_.") or "unknown"
    if not safe_cli or not safe_sid:
        raise ValueError(f"unusable session identity: {cli!r}/{session_id!r}")
    return vault_root() / safe_cli / f"{safe_sid}.json"


def path_for(cli: str, session_id: str) -> Path:
    """Public accessor: where a session's lossless copy lives."""
    return _path_for(cli, session_id)


def encode_raw(raw: RawSession) -> dict:
    """Full extraction → JSON-safe dict. Nothing is clipped here."""
    return {
        "meta": asdict(raw.meta),
        "messages": [{"role": m.role, "text": m.text, "at": m.at} for m in raw.messages],
        "todos": [asdict(t) for t in raw.todos],
        "files_touched": dict(raw.files_touched),
        "tool_counts": dict(raw.tool_counts),
        "interruption": asdict(raw.interruption),
        "compactions": [asdict(c) for c in raw.compactions],
    }


def decode_raw(payload: dict) -> RawSession:
    """The inverse of :func:`encode_raw` (vault round-trip is lossless)."""
    meta = SessionMeta(**payload["meta"])
    return RawSession(
        meta=meta,
        messages=[
            Message(role=m["role"], text=m["text"], at=m.get("at"))
            for m in payload["messages"]
        ],
        todos=[
            TodoItem(
                content=t["content"],
                status=t.get("status", "pending"),
                priority=t.get("priority", ""),
            )
            for t in payload.get("todos", [])
        ],
        files_touched=Counter(payload.get("files_touched") or {}),
        tool_counts=Counter(payload.get("tool_counts") or {}),
        interruption=Interruption(
            kind=payload.get("interruption", {}).get("kind", "clean"),
            detail=payload.get("interruption", {}).get("detail", ""),
            pending_user_text=payload.get("interruption", {}).get("pending_user_text", ""),
        ),
        compactions=[
            CompactionEvent(
                at=c.get("at"),
                reason=c.get("reason", ""),
                pre_tokens=c.get("pre_tokens"),
                post_tokens=c.get("post_tokens"),
                auto=c.get("auto", True),
            )
            for c in payload.get("compactions", [])
        ],
    )


def _canonical(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def save(raw: RawSession, *, source_kind: str = "", force: bool = False) -> Path | None:
    """Archive one extraction. Returns the path written, or None if unchanged.

    Content-hash dedupe means re-running capture on a growing session rewrites
    once per change, and never rewrites for an identical read.
    """
    payload = encode_raw(raw)
    blob = _canonical(payload)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    path = _path_for(raw.meta.cli, raw.meta.session_id)
    if path.is_file() and not force:
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = {}
        if existing.get("content_sha256") == digest:
            return None

    doc = {
        "vault_version": VAULT_VERSION,
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "content_sha256": digest,
        "bytes": len(blob.encode("utf-8")),
        "message_count": len(payload["messages"]),
        "source_kind": source_kind,
        "session": payload,
    }
    _atomic_write(path, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")

    # Verify-what-you-wrote: a backup that cannot be read back is not a backup.
    back = load(raw.meta.cli, raw.meta.session_id)
    if back is None or _canonical(encode_raw(back)) != blob:
        raise OSError(f"vault round-trip failed for {path}; the archive is not trustworthy")
    return path


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)  # atomic on both Windows and POSIX


def load(cli: str, session_id: str) -> RawSession | None:
    """Read a vaulted session back as a RawSession."""
    path = _path_for(cli, session_id)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return decode_raw(doc["session"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def read_doc(cli: str, session_id: str) -> dict | None:
    path = _path_for(cli, session_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def entries() -> list[dict]:
    """One row per archived session, newest file first."""
    root = vault_root()
    if not root.is_dir():
        return []
    out: list[dict] = []
    for path in sorted(root.rglob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        session = doc.get("session") or {}
        meta = session.get("meta") or {}
        out.append(
            {
                "cli": meta.get("cli", path.parent.name),
                "session_id": meta.get("session_id", path.stem),
                "title": meta.get("title", ""),
                "cwd": meta.get("cwd", ""),
                "saved_at": doc.get("saved_at", ""),
                "message_count": doc.get("message_count", len(session.get("messages") or [])),
                "bytes": doc.get("bytes", 0),
                "path": str(path),
            }
        )
    out.sort(key=lambda e: e["saved_at"] or "", reverse=True)
    return out


def total_bytes() -> int:
    root = vault_root()
    if not root.is_dir():
        return 0
    return sum(p.stat().st_size for p in root.rglob("*.json") if p.is_file())


def check(cli: str, session_id: str, live: RawSession | None) -> dict:
    """Compare the vault copy with what the store holds *right now*.

    This is the alarm that matters: stores shrink. Compaction, roll rotation and
    profile cleanup all take history away, and the vendor will not tell you. If
    the vault has turns the store no longer has, the vault is the only copy left.
    """
    doc = read_doc(cli, session_id)
    if doc is None:
        return {"state": "not-archived", "cli": cli, "session_id": session_id}
    vaulted = len(doc.get("session", {}).get("messages") or [])
    if live is None:
        return {
            "state": "store-gone",
            "cli": cli,
            "session_id": session_id,
            "vault_messages": vaulted,
        }
    now = len(live.messages)
    result = {
        "state": "ok",
        "cli": cli,
        "session_id": session_id,
        "vault_messages": vaulted,
        "store_messages": now,
    }
    if vaulted > now:
        result["state"] = "store-shrank"
        result["turns_only_in_vault"] = vaulted - now
    elif vaulted < now:
        result["state"] = "store-grew"
        result["turns_not_yet_archived"] = now - vaulted
    return result


def prune(keep: int = 5, older_than_days: int | None = None) -> list[str]:
    """Delete superseded archives on request only — never implicitly."""
    removed: list[str] = []
    root = vault_root()
    if not root.is_dir():
        return removed
    cutoff = time.time() - older_than_days * 86400 if older_than_days else None
    for path in sorted(root.rglob("*.json")):
        if keep > 0:
            continue  # one file per session: superseded copies are already gone
        if cutoff is not None and path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)
            removed.append(str(path))
    return removed


def fidelity_note(bundle: HandoffBundle, raw: RawSession, brief_chars: int) -> str:
    """One-line provenance footer: what the brief could not carry, and where the
    full copy lives. The artifact states its own lossiness.
    """
    path = _path_for(raw.meta.cli, raw.meta.session_id)
    total = len(raw.messages)
    carried = min(total, 3)
    return (
        f"bundle carries {carried}/{total} turns verbatim, "
        f"{brief_chars} chars after budget; full extraction: {path}"
    )
