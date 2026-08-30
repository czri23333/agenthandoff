"""Codex CLI parser — rollout JSONL under ~/.codex/sessions.

Layout (verified 2026-08-30):
    ~/.codex/sessions/rollout-<ts>-<uuid>.jsonl

Line types: session_meta (payload: session_id/timestamp/cwd/git/...),
response_item (payload.type == "message", role user|assistant|developer,
content blocks input_text/output_text), event_msg, turn_context, ...

`developer` rows are harness-injected context, not user turns — skipped.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from agent_handoff.model import Message, RawSession, SessionMeta, ts_to_iso
from agent_handoff.parsers.base import Parser, as_text_blocks, read_jsonl


class CodexParser(Parser):
    cli = "codex"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path.home() / ".codex" / "sessions"

    def available(self) -> bool:
        return self.root.is_dir()

    def list_sessions(self) -> list[SessionMeta]:
        if not self.available():
            return []
        metas: list[SessionMeta] = []
        for f in self.root.rglob("*.jsonl"):
            meta = self._peek(f)
            if meta:
                metas.append(meta)
        metas.sort(key=lambda m: m.updated_at or "", reverse=True)
        return metas

    def _peek(self, path: Path) -> SessionMeta | None:
        rows = read_jsonl(path, limit=5)
        meta_row = next((r for r in rows if r.get("type") == "session_meta"), None)
        if meta_row is None:
            return None
        p = meta_row.get("payload") or {}
        try:
            updated = ts_to_iso(int(path.stat().st_mtime * 1000))
        except OSError:
            updated = None
        return SessionMeta(
            cli=self.cli,
            session_id=str(p.get("session_id") or p.get("id") or path.stem),
            title=path.stem[:80],
            cwd=str(p.get("cwd") or ""),
            started_at=ts_to_iso(p.get("timestamp")),
            updated_at=updated,
            model=str(p.get("model_provider") or "") or None,
            source_path=str(path),
        )

    def load(self, session_id: str) -> RawSession | None:
        if not self.available():
            return None
        hits = [p for p in self.root.rglob("*.jsonl") if session_id in p.name]
        if not hits:
            return None
        path = hits[0]

        messages: list[Message] = []
        files: Counter[str] = Counter()
        tools: Counter[str] = Counter()
        meta: SessionMeta | None = None

        for row in read_jsonl(path):
            rtype = row.get("type")
            payload = row.get("payload") or {}
            if rtype == "session_meta":
                try:
                    updated = ts_to_iso(int(path.stat().st_mtime * 1000))
                except OSError:
                    updated = None
                meta = SessionMeta(
                    cli=self.cli,
                    session_id=str(payload.get("session_id") or path.stem),
                    title=path.stem[:80],
                    cwd=str(payload.get("cwd") or ""),
                    started_at=ts_to_iso(payload.get("timestamp")),
                    updated_at=updated,
                    model=str(payload.get("model_provider") or "") or None,
                    source_path=str(path),
                )
            elif rtype == "response_item" and payload.get("type") == "message":
                role = payload.get("role")
                if role not in ("user", "assistant"):
                    continue
                text, tool_blocks = as_text_blocks(payload.get("content"))
                text = self.clean_text(text)
                if text and not self.is_noise(text):
                    messages.append(Message(role=role, text=text))
                for tb in tool_blocks:
                    name = str(tb.get("name") or "tool")
                    tools[name] += 1
                    ti = tb.get("input") if isinstance(tb.get("input"), dict) else {}
                    for pth in self.extract_paths(ti):
                        files[pth] += 1

        if meta is None:
            return None
        return self.build_raw(meta, messages, [], files, tools)
