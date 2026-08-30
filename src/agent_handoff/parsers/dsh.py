"""dsh (DeepSeekHarness) parser — zstd-compressed JSONL session rolls.

Layout (verified 2026-08-30):
    ~/.dsh/sessions/<munged-project>/<uuid>/session.jsonl.zstd

Line types (type-discriminated):
    session         {id, createdAt, cwd, parentSession, origin, agentPreset}
    session/title   {data:{title, messageSeqs, source}}
    user/message    {seq, time, data:{content:[{type:"text", text}]}}
    assistant/chunk {seq, time, data:{turn, step, chunk:{type:"text"|"usage"|…}}}
    plus turn/step markers, approvals, subagent descriptors — skipped.

`zstandard` is an optional dependency (extra "zstd"); without it this parser
reports the missing codec through `doctor` instead of raising.
"""

from __future__ import annotations

from pathlib import Path

from agent_handoff.model import Message, RawSession, SessionMeta, ts_to_iso
from agent_handoff.parsers.base import Parser

try:  # optional extra
    import zstandard as _zstd
except ImportError:  # pragma: no cover - exercised via doctor only
    _zstd = None


def _decompress(path: Path, limit_bytes: int | None = None) -> bytes:
    with open(path, "rb") as fh:
        reader = _zstd.ZstdDecompressor().stream_reader(fh)
        return reader.read(limit_bytes) if limit_bytes else reader.read()


class DshParser(Parser):
    cli = "dsh"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path.home() / ".dsh" / "sessions"

    def available(self) -> bool:
        return self.root.is_dir()

    def codec_ok(self) -> bool:
        return _zstd is not None

    # -- discovery ----------------------------------------------------------

    def list_sessions(self) -> list[SessionMeta]:
        """Peek the first 64 KiB of each roll for identity lines."""
        if not self.available() or not self.codec_ok():
            return []
        metas: list[SessionMeta] = []
        for f in self.root.rglob("session.jsonl.zstd"):
            meta = self._peek(f)
            if meta:
                metas.append(meta)
        metas.sort(key=lambda m: m.updated_at or "", reverse=True)
        return metas

    def _peek(self, path: Path) -> SessionMeta | None:
        try:
            head = _decompress(path, limit_bytes=65536).decode("utf-8", errors="replace")
        except Exception:
            return None
        sid = path.parent.name
        title = ""
        cwd = ""
        created = updated = None
        for line in head.splitlines():
            line = line.strip()
            if not line:
                continue
            import json

            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = row.get("type")
            if t == "session":
                sid = row.get("id") or sid
                cwd = row.get("cwd") or cwd
                created = ts_to_iso(row.get("createdAt")) or created
                updated = ts_to_iso(row.get("updatedAt")) or updated
            elif t == "session/title" and not title:
                title = (row.get("data") or {}).get("title") or ""
        return SessionMeta(
            cli=self.cli,
            session_id=sid,
            title=title or sid,
            cwd=cwd,
            started_at=created,
            updated_at=updated,
            source_path=str(path),
        )

    # -- extraction ----------------------------------------------------------

    def load(self, session_id: str) -> RawSession | None:
        if not self.available() or not self.codec_ok():
            return None
        path = self._resolve(session_id)
        if path is None:
            return None

        import json
        from collections import Counter

        messages: list[Message] = []
        files: Counter[str] = Counter()
        tools: Counter[str] = Counter()
        sid = path.parent.name
        title = ""
        cwd = ""
        created = updated = None

        for line in _decompress(path).decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = row.get("type")
            if t == "session":
                sid = row.get("id") or sid
                cwd = row.get("cwd") or cwd
                created = ts_to_iso(row.get("createdAt")) or created
                updated = ts_to_iso(row.get("updatedAt")) or updated
            elif t == "session/title":
                title = (row.get("data") or {}).get("title") or title
            elif t == "user/message":
                text = self.clean_text(
                    "\n".join(
                        b.get("text") or ""
                        for b in (row.get("data") or {}).get("content") or []
                        if isinstance(b, dict) and b.get("type") == "text"
                    )
                )
                if text and not self.is_noise(text):
                    messages.append(Message(role="user", text=text, at=ts_to_iso(row.get("time"))))
            elif t == "assistant/chunk":
                chunk = ((row.get("data") or {}).get("chunk")) or {}
                if chunk.get("type") == "text":
                    text = self.clean_text(chunk.get("text") or chunk.get("delta") or "")
                    if text:
                        messages.append(
                            Message(role="assistant", text=text, at=ts_to_iso(row.get("time")))
                        )

        meta = SessionMeta(
            cli=self.cli,
            session_id=sid,
            title=title or sid,
            cwd=cwd,
            started_at=created,
            updated_at=updated,
            source_path=str(path),
        )
        return self.build_raw(meta, messages, [], files, tools)

    def _resolve(self, session_id: str) -> Path | None:
        hits = list(self.root.rglob(f"{session_id}/session.jsonl.zstd"))
        return hits[0] if hits else None
