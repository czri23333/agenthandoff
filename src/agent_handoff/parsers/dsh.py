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

from agent_handoff.locations import home
from agent_handoff.model import Message, RawSession, SessionMeta, ts_to_iso
from agent_handoff.parsers.base import Parser

try:  # optional extra
    import zstandard as _zstd
except ImportError:  # pragma: no cover - exercised via doctor only
    _zstd = None


def _decompress(path: Path, limit_bytes: int | None = None) -> bytes:
    """Decompress a dsh roll, crossing frame boundaries.

    dsh appends one zstd frame per flush, so a roll is a concatenation of
    frames. The stream reader stops at the first frame end unless told to
    read across frames — which silently truncated every roll to its opening
    `session` line and cost list_sessions() every title and load() every
    message.
    """
    with open(path, "rb") as fh:
        reader = _zstd.ZstdDecompressor().stream_reader(fh, read_across_frames=True)
        return reader.read(limit_bytes) if limit_bytes else reader.read()


class DshParser(Parser):
    cli = "dsh"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or home() / ".dsh" / "sessions"

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
        # Config lines (full system prompts) can occupy the head of a roll;
        # 256 KiB is usually enough to also reach the first real user turn.
        try:
            head = _decompress(path, limit_bytes=1048576).decode("utf-8", errors="replace")
        except Exception:
            return None
        sid = path.parent.name
        title = ""
        first_user = ""
        cwd = ""
        created = updated = None
        parent = None
        import json

        for line in head.splitlines():
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
                parent = row.get("parentSession") or parent
            elif t == "session/title" and not title:
                title = (row.get("data") or {}).get("title") or ""
            elif t == "user/message" and not first_user:
                blocks = (row.get("data") or {}).get("content") or []
                text = self.clean_text(
                    " ".join(
                        b.get("text") or ""
                        for b in blocks
                        if isinstance(b, dict) and b.get("type") == "text"
                    )
                )
                if text and not self.is_noise(text):
                    first_user = text[:80]
        if updated is None:
            try:
                from datetime import datetime, timezone

                updated = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(
                    timespec="seconds"
                )
            except OSError:
                pass
        return SessionMeta(
            cli=self.cli,
            session_id=sid,
            title=title or first_user or sid,
            cwd=cwd,
            started_at=created,
            updated_at=updated,
            source_path=str(path),
            parent_session_id=parent,
        )

    # -- extraction ----------------------------------------------------------

    def raw_archive(self, session_id: str) -> list[dict] | None:
        """The session's zstd roll, decompressed across all its frames —
        every record the worker wrote, byte-faithful after decompression."""
        if not self.available() or not self.codec_ok():
            return None
        path = self._resolve(session_id)
        if path is None:
            return None
        from agent_handoff.parsers.base import file_entry

        try:
            data = _decompress(path)
        except Exception:
            return None
        try:
            rel = str(path.resolve().relative_to(self.root.resolve()))
        except (ValueError, OSError):
            rel = str(path)
        return [file_entry(path, data, rel)]

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
        parent = None
        # Non-null only: agent identity (who ran), model + window (what ran),
        # the turn-end verdict (why it stopped — e.g. a 429 quota death).
        agent_label: str | None = None
        agent_provider: str | None = None
        agent_model: str | None = None
        req_model: str | None = None
        context_window: int | None = None
        turn_end: dict | None = None
        turns_text: dict = {}
        turns_usage: dict = {}
        turns_reason: dict = {}
        turns_seen_index: dict = {}
        turns_tools: dict = {}
        # Turns carrying a finished assistant/message row: their chunk rows
        # are streaming pre-images of the same content — drop the chunks.
        # Pre-scan first: chunks usually arrive BEFORE the finished row.
        # Single decompression shared with the main loop below.
        try:
            _all = _decompress(path).decode("utf-8", errors="replace").splitlines()
        except (OSError, ValueError):
            _all = []
        has_finished: set[str] = set()
        for _line in _all:
            _line = _line.strip()
            if not _line:
                continue
            try:
                _row = json.loads(_line)
            except json.JSONDecodeError:
                continue
            if _row.get("type") == "assistant/message":
                _data = _row.get("data") or {}
                if _data.get("turn") is not None:
                    has_finished.add(str(_data.get("turn")))

        for line in _all:
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
                parent = row.get("parentSession") or parent
            elif t == "session/title":
                title = (row.get("data") or {}).get("title") or title
            elif t == "user/message":
                praw = "\n".join(
                    b.get("text") or ""
                    for b in (row.get("data") or {}).get("content") or []
                    if isinstance(b, dict) and b.get("type") == "text"
                )
                text = self.clean_text(praw)
                if text and not self.is_noise(text):
                    messages.append(self.msg("user", praw, text=text, at=ts_to_iso(row.get("time"))))
            elif t == "subagent/descriptor":
                data = row.get("data") or {}
                agent_label = str(data.get("label") or "") or agent_label
                agent_provider = str(data.get("agentProvider") or "") or agent_provider
                agent_model = str(data.get("agentModel") or "") or agent_model
            elif t == "request/header":
                header = (row.get("data") or {}).get("header") or {}
                cfg = header.get("config") or {}
                req_model = str(cfg.get("model") or "") or req_model
            elif t == "request/context":
                data = row.get("data") or {}
                req_model = str(data.get("model") or "") or req_model
                window = data.get("contextWindow")
                if isinstance(window, int):
                    context_window = window
            elif t == "turn/end":
                turn_end = row.get("data") or turn_end
            elif t == "assistant/message":
                # Finished message blocks: the product's own assembled turns
                # (reasoning/tool-call/text). Prefer these over the chunk
                # stream; chunks remain as fallback for sessions without them.
                # Turn keys vary (int in messages, str in chunks): normalize.
                data = row.get("data") or {}
                turn = data.get("turn")
                if turn is not None:
                    has_finished.add(str(turn))
                msg = data.get("message") or {}
                for b in msg.get("content") or []:
                    if not isinstance(b, dict):
                        continue
                    btype = b.get("type")
                    if btype == "reasoning":
                        praw = b.get("text") or ""
                        text = self.clean_text(praw)
                        if text:
                            turns_reason.setdefault(turn, []).append((text, praw))
                    elif btype == "tool-call":
                        name = str(b.get("name") or "tool")
                        tools[name] += 1
                        args = b.get("arguments")
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except ValueError:
                                args = {}
                        if isinstance(args, dict):
                            for pth in self.extract_paths(args):
                                files[pth] += 1
                        arg = ""
                        if isinstance(args, dict):
                            for k in ("file_path", "path", "command", "description"):
                                v = args.get(k)
                                if isinstance(v, str) and v.strip():
                                    arg = f" {v.strip()[:80]}"
                                    break
                        turns_tools.setdefault(turn, []).append(f"[工具 {name}]{arg}")
                    elif btype == "text":
                        praw = b.get("text") or ""
                        text = self.clean_text(praw)
                        if text:
                            turns_text.setdefault(turn, []).append((ts_to_iso(row.get("time")), text, praw))
                            turns_seen_index[turn, len(turns_text[turn])] = True
            elif t == "assistant/chunk":
                data = row.get("data") or {}
                chunk = data.get("chunk") or {}
                turn = data.get("turn")
                if turn is not None and str(turn) in has_finished and (chunk.get("type") or "") != "usage":
                    continue  # finished row already covers this turn's content
                ctype = chunk.get("type")
                if ctype == "usage":
                    u = chunk.get("usage") or {}
                    turns_usage[turn] = u
                elif ctype in ("text", "text-delta"):
                    praw = chunk.get("text") or chunk.get("delta") or ""
                    text = self.clean_text(praw)
                    if text:
                        turns_text.setdefault(turn, []).append((ts_to_iso(row.get("time")), text, praw))
                        turns_seen_index[turn, chunk.get("index")] = True
                elif ctype == "reasoning-delta":
                    praw = chunk.get("text") or ""
                    text = self.clean_text(praw)
                    if text:
                        turns_reason.setdefault(turn, []).append((text, praw))
                elif ctype == "block-end":
                    block = chunk.get("block") or {}
                    btype = block.get("type")
                    if btype == "text" and not turns_seen_index.get((turn, chunk.get("index"))):
                        praw = block.get("text") or ""
                        text = self.clean_text(praw)
                        if text:
                            turns_text.setdefault(turn, []).append((ts_to_iso(row.get("time")), text, praw))
                    elif btype == "reasoning" and not turns_seen_index.get((turn, chunk.get("index"))):
                        praw = block.get("text") or ""
                        text = self.clean_text(praw)
                        if text:
                            turns_reason.setdefault(turn, []).append((text, praw))

        # One assistant turn = one message: the product streams a reply as
        # many text chunks plus a usage chunk keyed by the same turn number.
        # Merging both fixes chunk fragmentation AND attributes per-message
        # billing (input/output/reasoning) plus the request model. Reasoning
        # deltas ride along as [思考] turns, the same convention as the
        # CherryStudio parser.
        for turn in sorted(set(list(turns_text) + list(turns_reason) + list(turns_tools)), key=lambda k: (k is None, k)):
            parts = turns_text.get(turn, [])
            at = next((a for a, _, _ in parts if a), None)
            u = turns_usage.get(turn) or {}
            msg_in = u.get("inputTokens")
            msg_out = u.get("outputTokens")
            msg_reason = u.get("reasoningTokens")
            model = req_model or agent_model or None
            if parts:
                messages.append(
                    self.msg(
                        "assistant",
                        "\n".join(r for _, _, r in parts),
                        text="\n".join(t for _, t, _ in parts),
                        at=at,
                        model=model,
                        tokens_in=msg_in if isinstance(msg_in, int) else None,
                        tokens_out=msg_out if isinstance(msg_out, int) else None,
                        tokens_reasoning=msg_reason if isinstance(msg_reason, int) else None,
                    )
                )
            for tool_line in turns_tools.get(turn, []):
                # Tool rows carry no billing of their own: the turn's usage
                # lives on the text/thinking turns (else usage() would sum
                # one request N times for N tool calls).
                messages.append(
                    self.msg(
                        "assistant",
                        tool_line,
                        text=tool_line,
                        at=at,
                        model=model,
                    )
                )
            reason_pairs = turns_reason.get(turn, [])
            reason_text = "".join(t for t, _ in reason_pairs).strip()
            if reason_text:
                # Same-request billing when this turn has its own usage;
                # otherwise the second pass below backfills from the nearest
                # settled turn (old turns carry no usage chunk).
                messages.append(
                    self.msg(
                        "assistant",
                        f"[思考] {''.join(r for _, r in reason_pairs).strip()}",
                        text=f"[思考] {reason_text}", at=at, model=model,
                        tokens_in=msg_in if isinstance(msg_in, int) else None,
                        tokens_out=msg_out if isinstance(msg_out, int) else None,
                        tokens_reasoning=msg_reason if isinstance(msg_reason, int) else None,
                    )
                )

        # Second pass (same rule as the jsonl family): tokenless [思考] turns
        # inherit the nearest settled assistant turn at/after their timestamp.
        messages.sort(key=lambda m: m.at or "")
        settled = [m for m in messages if m.role == "assistant" and (m.tokens_in is not None or m.tokens_out is not None)]
        if settled:
            for m in messages:
                if (
                    m.role == "assistant"
                    and m.tokens_in is None
                    and m.tokens_out is None
                    and (m.text or "").startswith("[思考]")
                    and m.at
                ):
                    nxt = next((s for s in settled if (s.at or "") >= (m.at or "")), None)
                    if nxt is None:
                        continue
                    m.tokens_in = nxt.tokens_in
                    m.tokens_out = nxt.tokens_out
                    if m.tokens_reasoning is None:
                        m.tokens_reasoning = nxt.tokens_reasoning
                    if not m.model:
                        m.model = nxt.model

        meta = SessionMeta(
            cli=self.cli,
            session_id=sid,
            title=title or sid,
            cwd=cwd,
            started_at=created,
            updated_at=updated,
            source_path=str(path),
            parent_session_id=parent,
            model=req_model or agent_model or None,
            notes=_dsh_notes(agent_label, agent_provider, agent_model, req_model, context_window),
        )
        raw = self.build_raw(meta, messages, [], files, tools)
        raw.interruption = _dsh_interruption(turn_end)
        return raw

    def usage(self, session_id: str) -> dict | None:
        """Per-model tokens summed once per turn (not per message).

        A turn fans out into text/thinking/tool rows sharing one usage
        chunk — summing messages would bill one request N times. Aggregate
        the turn-level usage rows instead.
        """
        if not self.available() or not self.codec_ok():
            return None
        path = self._resolve(session_id)
        if path is None:
            return None
        import json

        from collections import Counter

        seen: dict = {}
        model: str | None = None
        for line in _decompress(path).decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = row.get("type")
            if t == "request/context":
                data = row.get("data") or {}
                if isinstance(data.get("model"), str) and data["model"]:
                    model = data["model"]
            data = row.get("data") or {}
            chunk = data.get("chunk") or {}
            if row.get("type") == "assistant/chunk" and chunk.get("type") == "usage":
                u = chunk.get("usage") or {}
                if data.get("turn") not in seen:
                    seen[data.get("turn")] = u
        if not seen:
            return None
        tot_in = tot_out = tot_reason = calls = 0
        for u in seen.values():
            i, o, r = u.get("inputTokens"), u.get("outputTokens"), u.get("reasoningTokens")
            if isinstance(i, int):
                tot_in += i
            if isinstance(o, int):
                tot_out += o
            if isinstance(r, int):
                tot_reason += r
            calls += 1
        name = model or "unknown"
        return {
            "models": [
                {
                    "model": name,
                    "calls": calls,
                    "tokens_in": tot_in,
                    "tokens_out": tot_out,
                    "reasoning": tot_reason,
                    "cache_write": 0,
                    "cache_read": 0,
                    "avg_ttft_ms": None,
                    "tok_per_s": None,
                }
            ],
            "totals": {"calls": calls, "tokens_in": tot_in, "tokens_out": tot_out},
        }

    def _resolve(self, session_id: str) -> Path | None:
        hits = list(self.root.rglob(f"{session_id}/session.jsonl.zstd"))
        return hits[0] if hits else None


def _dsh_notes(
    label: str | None,
    provider: str | None,
    agent_model: str | None,
    req_model: str | None,
    window: int | None,
) -> list[str]:
    """Agent identity + model + window the roll declares about itself."""
    notes: list[str] = []
    if label:
        notes.append(f"agent:{label}")
    if provider:
        notes.append(f"agent_provider:{provider}")
    if agent_model and agent_model != req_model:
        notes.append(f"agent_model:{agent_model}")
    if window:
        notes.append(f"context_window:{window}")
    return notes


def _dsh_interruption(turn_end: dict | None):
    """The turn-end verdict is the store's own account of why a run stopped —
    including quota deaths (e.g. GoUsageLimitError) that no row count reveals.
    """
    from agent_handoff.model import Interruption

    if not turn_end:
        return Interruption()
    reason = turn_end.get("reason") or {}
    kind = str(reason.get("kind") or "")
    if kind == "error":
        err = reason.get("error") or {}
        msg = str(err.get("message") or "")[:300]
        if " sage " in f" {msg} ".lower() or "limit" in msg.lower() or "429" in msg:
            return Interruption(kind="error", detail=f"quota/limit: {msg[:200]}")
        return Interruption(kind="error", detail=msg[:200])
    if kind in ("complete", "completed", "done", "finished"):
        return Interruption(kind="clean")
    if kind:
        return Interruption(kind="unknown", detail=f"turn_end:{kind}")
    return Interruption()
