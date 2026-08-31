"""Snapshot a live session *before* its budget runs out.

Why this exists. The session worth handing off is usually the one that dies
without warning: quota ends mid-task, or the context window fills and the next
request is refused. Everything else in this tool reads a store after the fact -
and after the fact is exactly when the store may already be compacted, truncated
or "corrupted, started a new session".

So `watch` polls the session and takes a snapshot at fixed rungs of its budget -
20%, 45%, 70%, 90% of the context window by default, which is spaced so that a
session dying at any point has a recent, complete brief behind it. Each snapshot
is both a rendered bundle (for a human to paste) and a lossless vault archive (for
`vault restore`), and the ladder state lives on disk, so re-running never
re-fires a rung that already fired.

Two honest limitations, both reported in the output:

* the fill estimate needs per-request usage; when the store does not record a
  context window, the ladder falls back to turn counts and says `turns`
* a store flush is not atomic: a snapshot can catch a half-written record. The
  parsers tolerate that, and the snapshot notes its own turn count so a truncated
  tail is visible rather than silent.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from agent_handoff import vault
from agent_handoff.locations import home
from agent_handoff.render import render_markdown
from agent_handoff.summarize import summarize

LADDER = (0.20, 0.45, 0.70, 0.90)
TURN_LADDER = (25, 75, 150, 300)
DEFAULT_INTERVAL = 60.0


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def watch_root() -> Path:
    return home() / ".agenthandoff" / "watch"


def state_path(cli: str, session_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() else "-" for ch in f"{cli}-{session_id}")[:80]
    return watch_root() / f"{safe}.json"


@dataclass
class WatchState:
    """What has already fired, so a long watch does not snapshot every minute."""

    cli: str = ""
    session_id: str = ""
    fired: dict[str, str] = field(default_factory=dict)  # label -> iso time
    snapshots: list[str] = field(default_factory=list)
    turns: int = 0
    fill: float | None = None
    basis: str = ""
    updated_at: str = ""

    @property
    def fired_labels(self) -> set[str]:
        return set(self.fired)


def load_state(cli: str, session_id: str) -> WatchState:
    path = state_path(cli, session_id)
    if not path.is_file():
        return WatchState(cli=cli, session_id=session_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return WatchState(cli=cli, session_id=session_id)
    state = WatchState(**{k: v for k, v in data.items() if k in WatchState.__dataclass_fields__})
    state.cli, state.session_id = cli, session_id
    return state


def save_state(state: WatchState) -> Path:
    path = state_path(state.cli, state.session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    state.updated_at = now_iso()
    text = json.dumps(asdict(state), indent=2, ensure_ascii=False) + "\n"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)
    return path


def context_fill(parser, raw) -> tuple[float | None, str]:
    """How full the model's context is, and how that was worked out.

    Prefers the store's own declaration: a context window plus the tokens of the
    most recent request. Falls back to the session totals, and to None when the
    store records neither - in which case the caller uses the turn ladder.
    """
    window = None
    for note in getattr(raw.meta, "notes", ()) or ():
        text = str(note)
        if text.startswith("context_window:"):
            try:
                window = int(text.split(":", 1)[1])
            except ValueError:
                window = None
    # Only a per-request figure measures pressure. A session total is a sum over
    # every call the session ever made - divided by the window it saturates on any
    # long session, which would fire the whole ladder at once.
    used = 0
    last = getattr(parser, "last_request_tokens", None)
    if callable(last):
        recent = last(raw.meta.session_id) or {}
        used = recent.get("input_tokens") or recent.get("prompt_tokens") or 0
    if not window or not used:
        return None, "unknown"
    fraction = min(1.0, float(used) / float(window))
    return fraction, f"{used} of {window} tokens"


def triggers(
    raw,
    state: WatchState,
    fill: float | None,
    ladder: tuple[float, ...] = LADDER,
    turn_ladder: tuple[int, ...] = TURN_LADDER,
) -> list[str]:
    """Ladder rungs crossed since the last look, oldest first."""
    fired = state.fired_labels
    out: list[str] = []
    turns = len(raw.messages)
    if fill is None:
        for rung in turn_ladder:
            label = f"t{rung}"
            if turns >= rung and label not in fired:
                out.append(label)
        return out
    for rung in ladder:
        label = f"{int(rung * 100)}%"
        if fill >= rung and label not in fired:
            out.append(label)
    return out


def snapshot(
    parser, raw, label: str, out_dir: Path | None = None
) -> tuple[Path, str | None]:
    """Write the brief for this rung and archive the session losslessly."""
    target_dir = Path(out_dir) if out_dir else watch_root() / raw.meta.session_id[:40]
    target_dir.mkdir(parents=True, exist_ok=True)
    bundle = summarize(raw)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    turn_count = len(raw.messages)
    name = f"{label.replace('%', 'pct')}-{turn_count}turns-{stamp}.md"
    path = target_dir / name
    text = render_markdown(bundle)
    path.write_text(text, encoding="utf-8", newline="\n")
    archived: str | None = None
    try:
        archived = str(vault.save(raw))
    except OSError:
        archived = None  # the brief is the deliverable; the archive is a bonus
    return path, archived


def watch_once(
    parser,
    session_id: str,
    ladder: tuple[float, ...] = LADDER,
    turn_ladder: tuple[int, ...] = TURN_LADDER,
    out_dir: Path | None = None,
) -> dict:
    """One look: measure, fire whatever rungs were crossed, return the result."""
    raw = parser.load(session_id)
    state = load_state(parser.cli, session_id)
    if raw is None:
        return {"status": "gone", "cli": parser.cli, "session_id": session_id}
    fill, basis = context_fill(parser, raw)
    due = triggers(raw, state, fill, ladder, turn_ladder)
    written: list[dict] = []
    for label in due:
        path, archived = snapshot(parser, raw, label, out_dir)
        state.fired[label] = now_iso()
        state.snapshots.append(str(path))
        written.append({"rung": label, "path": str(path), "vault": archived})
    state.turns = len(raw.messages)
    state.fill = fill
    state.basis = basis
    if due:
        save_state(state)
    return {
        "status": "ok",
        "cli": parser.cli,
        "session_id": session_id,
        "turns": state.turns,
        "fill": fill,
        "basis": basis,
        "fired": written,
        "pending": [
            lab for lab in ([f"{int(r * 100)}%" for r in ladder] if fill is not None
                            else [f"t{t}" for t in turn_ladder])
            if lab not in state.fired_labels
        ],
    }


def run(
    parser,
    session_id: str,
    *,
    interval: float = DEFAULT_INTERVAL,
    iterations: int | None = None,
    sleep=time.sleep,
    on_event=None,
    out_dir: Path | None = None,
    ladder: tuple[float, ...] = LADDER,
    turn_ladder: tuple[int, ...] = TURN_LADDER,
) -> dict:
    """Poll until the session disappears, or for `iterations` looks.

    `iterations` and `sleep` are parameters, not accidents: a watch loop nobody
    can run once is a loop nobody can test.
    """
    seen = 0
    fired: list[dict] = []
    last: dict = {}
    while iterations is None or seen < iterations:
        seen += 1
        last = watch_once(
            parser, session_id, ladder=ladder, turn_ladder=turn_ladder, out_dir=out_dir
        )
        if last["status"] == "gone":
            break
        for event in last.get("fired", []):
            fired.append(event)
            if on_event is not None:
                on_event(event, last)
        if iterations is not None and seen >= iterations:
            break
        sleep(interval)
    return {"looks": seen, "fired": fired, "last": last}
