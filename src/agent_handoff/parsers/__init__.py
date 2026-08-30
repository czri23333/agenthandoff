"""Parser registry and session resolution."""

from __future__ import annotations

from agent_handoff.model import RawSession, SessionMeta
from agent_handoff.parsers.base import Parser
from agent_handoff.parsers.codex import CodexParser
from agent_handoff.parsers.dsh import DshParser
from agent_handoff.parsers.jsonl_family import (
    ClaudeCodeParser,
    CodebuddyCnParser,
    CodebuddyParser,
    QodercnIdeParser,
    QoderworkCnParser,
    QoderworkParser,
    QwenworkParser,
)
from agent_handoff.parsers.kimi import KimiParser
from agent_handoff.parsers.zcode import ZcodeParser

__all__ = [
    "Parser",
    "ZcodeParser",
    "ClaudeCodeParser",
    "CodebuddyParser",
    "CodebuddyCnParser",
    "QoderworkParser",
    "QodercnIdeParser",
    "QoderworkCnParser",
    "QwenworkParser",
    "DshParser",
    "KimiParser",
    "CodexParser",
    "available_parsers",
    "resolve_session",
]


def available_parsers() -> list[Parser]:
    """Instantiate parsers whose storage exists on this machine, display order."""
    instances = [
        ZcodeParser(),
        ClaudeCodeParser(),
        CodebuddyParser(),
        CodebuddyCnParser(),
        QoderworkParser(),
        QoderworkCnParser(),
        QodercnIdeParser(),
        QwenworkParser(),
        DshParser(),
        KimiParser(),
        CodexParser(),
    ]
    return [p for p in instances if p.available()]


def all_parsers() -> list[Parser]:
    return [
        ZcodeParser(),
        ClaudeCodeParser(),
        CodebuddyParser(),
        CodebuddyCnParser(),
        QoderworkParser(),
        QoderworkCnParser(),
        QodercnIdeParser(),
        QwenworkParser(),
        DshParser(),
        KimiParser(),
        CodexParser(),
    ]


def resolve_session(session_ref: str, cli: str | None = None) -> tuple[Parser, RawSession]:
    """Find a session by id (or 'latest') across known stores.

    Raises FileNotFoundError with a human-readable explanation when nothing
    matches, so the CLI can surface it directly.
    """
    candidates = all_parsers()
    if cli:
        candidates = [p for p in candidates if p.cli == cli]
        if not candidates:
            raise FileNotFoundError(f"unknown or unavailable cli: {cli}")

    if session_ref == "latest":
        metas: list[SessionMeta] = []
        for p in candidates:
            metas.extend(p.list_sessions())
        if not metas:
            raise FileNotFoundError("no sessions found in any known store")
        metas.sort(key=lambda m: m.updated_at or "", reverse=True)
        newest = metas[0]
        parser = next(p for p in candidates if p.cli == newest.cli)
        raw = parser.load(newest.session_id)
        if raw is None:
            raise FileNotFoundError(f"failed to load session {newest.session_id}")
        return parser, raw

    for p in candidates:
        raw = p.load(session_ref)
        if raw is not None:
            return p, raw

    # Prefix match (like git short hashes): unambiguous hits only.
    prefix_hits: list[tuple[Parser, SessionMeta]] = []
    for p in candidates:
        for m in p.list_sessions():
            if m.session_id.startswith(session_ref):
                prefix_hits.append((p, m))
    if len(prefix_hits) == 1:
        p, m = prefix_hits[0]
        raw = p.load(m.session_id)
        if raw is not None:
            return p, raw
    if len(prefix_hits) > 1:
        ids = ", ".join(m.session_id for _p, m in prefix_hits[:5])
        raise FileNotFoundError(f"ambiguous session prefix '{session_ref}': {ids}")

    raise FileNotFoundError(
        f"session '{session_ref}' not found in: " + ", ".join(p.cli for p in all_parsers())
    )
