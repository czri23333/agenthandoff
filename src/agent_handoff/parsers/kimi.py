"""Kimi CLI parser (experimental).

Layout (verified 2026-08-30):
    ~/.kimi-code/sessions/wd_<workdir-hash>/<session_id>/
        state.json               title / createdAt / updatedAt / workDir
        agents/main/wire.jsonl   protocol stream (type-discriminated lines)

wire.jsonl's message-row dialect is still being mapped; this parser
extracts reliable identity/state metadata and passes wire rows through the
same tolerant text splitter used by the JSONL family. Marked experimental:
fields may be missing until the protocol is pinned down.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_handoff.locations import home
from agent_handoff.model import Message, RawSession, SessionMeta, ts_to_iso
from agent_handoff.parsers.base import Parser, as_text_blocks, read_jsonl


class KimiParser(Parser):
    cli = "kimi"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or home() / ".kimi-code" / "sessions"

    def available(self) -> bool:
        return self.root.is_dir()

    def list_sessions(self) -> list[SessionMeta]:
        if not self.available():
            return []
        metas: list[SessionMeta] = []
        for state_file in self.root.glob("wd_*/session_*/state.json"):
            meta = self._peek(state_file)
            if meta:
                metas.append(meta)
        metas.sort(key=lambda m: m.updated_at or "", reverse=True)
        return metas

    def _peek(self, state_file: Path) -> SessionMeta | None:
        try:
            state = json.loads(state_file.read_text(encoding="utf-8", errors="replace"))
        except (json.JSONDecodeError, OSError):
            return None
        return SessionMeta(
            cli=self.cli,
            session_id=state_file.parent.name,
            title=state.get("title") or state_file.parent.name,
            cwd=state.get("workDir") or "",
            started_at=ts_to_iso(_ms(state.get("createdAt"))),
            updated_at=ts_to_iso(_ms(state.get("updatedAt"))),
            source_path=str(state_file),
        )

    def load(self, session_id: str) -> RawSession | None:
        if not self.available():
            return None
        hits = list(self.root.glob(f"wd_*/{session_id}/state.json"))
        if not hits:
            return None
        session_dir = hits[0].parent
        meta = self._peek(session_dir / "state.json")
        if meta is None:
            return None

        messages: list[Message] = []
        files, tools = {}, {}
        wire = session_dir / "agents" / "main" / "wire.jsonl"
        if wire.exists():
            for row in read_jsonl(wire):
                inner = row.get("message") if isinstance(row.get("message"), dict) else row
                role = inner.get("role") or ""
                if role not in ("user", "assistant"):
                    continue
                text, tool_blocks = as_text_blocks(inner.get("content"))
                text = self.clean_text(text)
                if text and not self.is_noise(text):
                    messages.append(Message(role=role, text=text))
                for tb in tool_blocks:
                    name = str(tb.get("name") or tb.get("tool") or "tool")
                    tools[name] = tools.get(name, 0) + 1
                    ti = tb.get("input") if isinstance(tb.get("input"), dict) else {}
                    for p in self.extract_paths(ti):
                        files[p] = files.get(p, 0) + 1

        return self.build_raw(meta, messages, [], files, tools)


def _ms(value) -> int | None:
    """Kimi state.json stores epoch millis as numbers or ISO strings."""
    if isinstance(value, (int, float)):
        return int(value)
    return None
