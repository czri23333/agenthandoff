"""Support matrix, derived — never hand-written.

Why this module exists: the README used to carry a hand-maintained table, and it
drifted into a false claim (Codex listed as ✅ stable while
``handoff doctor`` on the same machine reported its 19 rollout files as
unreadable). A hand-written table is an assertion; a derived table is evidence.
In this project the *only* defensible selling point is verifiability, so an
unverifiable table is not a typo — it is a hole in the positioning.

Column contract (every cell must hold on any machine after a plain clone):

``store``          storage shape, from the code that reads it
``reader``         a parser is registered (derived from the registry)
``fixtures``       count of sanitized real-format files shipped in the repo
``fixture reads``  sessions/messages those fixtures actually yield — the proof
``conformance``    whether a schema fingerprint baseline exists
``status``         DERIVED from the above, never typed by a human

A row can only say ``stable`` if a fixture parses into at least one session with
at least one message. Anything else is reported as ``unverified`` — which is the
honest label, and the one a reviewer can reproduce with one command.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from agent_handoff.parsers import all_parsers

REPO = Path(__file__).resolve().parent.parent.parent
FIXTURE_ROOT = REPO / "tests" / "fixtures" / "sanitized"
BASELINE_ROOT = REPO / "conformance"

# Facts that cannot be derived from code: the on-disk shape each store uses and
# the roadmap entries we intend to fill. Everything else is measured.
STORE_KINDS: dict[str, str] = {
    "zcode": "SQLite (read-only URI)",
    "claude": "JSONL dir",
    "codebuddy": "JSONL dir",
    "codebuddy-cn": "JSONL dir",
    "qoderwork": "JSONL dir",
    "qoderwork-cn": "JSONL dir",
    "qodercn-ide": "JSONL dir",
    "qwenwork": "JSONL dir",
    "dsh": "zstd JSONL dir",
    "kimi": "state.json + wire.jsonl",
    "codex": "JSONL rollouts",
}

# Parsers whose format handling is knowingly incomplete upstream of us.
EXPERIMENTAL: set[str] = {"kimi"}

ROADMAP: dict[str, str] = {
    "qoder-ide": "Electron leveldb — no session files on disk",
    "opencode": "storage layout undocumented",
    "trae": "IDE SQLite; read-only only, never written",
}

MATRIX_VERSION = "1"


@dataclass
class Row:
    cli: str
    store: str
    reader: bool
    fixtures: int = 0
    fixture_sessions: int = 0
    fixture_messages: int = 0
    fixture_ok: bool = False
    conformance: bool = False
    status: str = "unverified"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _fixture_dir(cli: str) -> Path:
    return FIXTURE_ROOT / cli


def _measure_fixture(parser, directory: Path) -> tuple[int, int, int, bool]:
    """(files, sessions, messages, ok) actually produced from the fixtures.

    The parser is pointed at the fixture directory instead of the user's store;
    nothing here touches a real session file.
    """
    files = sorted(p for p in directory.rglob("*") if p.is_file())
    sessions = messages = 0
    ok = False
    probe = getattr(parser, "with_root", None)
    if probe is None or not files:
        return len(files), 0, 0, False
    try:
        scoped = probe(directory)
        metas = scoped.list_sessions()
        sessions = len(metas)
        for meta in metas[:5]:  # bounded: a fixture dir is small by design
            raw = scoped.load(meta.session_id)
            if raw is not None:
                messages += len(raw.messages)
        ok = sessions > 0 and messages > 0
    except (OSError, ValueError):  # a broken fixture is a failed measurement
        ok = False
    return len(files), sessions, messages, ok


def derive_status(row: Row) -> str:
    """Status is a function of evidence, so it cannot be inflated."""
    if not row.reader:
        return "roadmap"
    if not row.fixtures:
        return "unverified"
    if not row.fixture_ok:
        return "fixture-fails"
    if row.cli in EXPERIMENTAL:
        return "experimental"
    return "stable"


def build_rows() -> list[Row]:
    rows: list[Row] = []
    registered = set()
    for parser in all_parsers():
        registered.add(parser.cli)
        row = Row(
            cli=parser.cli,
            store=STORE_KINDS.get(parser.cli, "unknown"),
            reader=True,
            conformance=(BASELINE_ROOT / f"{parser.cli}.json").is_file(),
        )
        directory = _fixture_dir(parser.cli)
        if directory.is_dir():
            measured = _measure_fixture(parser, directory)
            row.fixtures, row.fixture_sessions = measured[0], measured[1]
            row.fixture_messages, row.fixture_ok = measured[2], measured[3]
        row.status = derive_status(row)
        rows.append(row)
    for cli in ROADMAP:
        if cli not in registered:
            rows.append(
                Row(cli=cli, store=ROADMAP[cli], reader=False, status="roadmap")
            )
    return rows


def _cell(status: str, lang: str) -> str:
    zh = {
        "stable": "✅ 稳定（有夹具证据）",
        "experimental": "🧪 实验性",
        "unverified": "⚠️ 未验证（缺脱敏夹具）",
        "fixture-fails": "❌ 夹具解析失败",
        "roadmap": "🔜 路线图",
    }
    en = {
        "stable": "✅ stable (fixture-proven)",
        "experimental": "🧪 experimental",
        "unverified": "⚠️ unverified (no fixture)",
        "fixture-fails": "❌ fixture fails to parse",
        "roadmap": "🔜 roadmap",
    }
    table = zh if lang == "zh" else en
    return table.get(status, status)


def render_markdown(lang: str = "en", rows: list[Row] | None = None) -> str:
    rows = rows if rows is not None else build_rows()
    if lang == "zh":
        header = "| CLI | 存储形态 | 读取 | 脱敏夹具 | 夹具读出 | 格式指纹 | 状态 |"
        rule = "|---|---|---|---|---|---|---|"
    else:
        header = "| CLI | store | reader | fixtures | proven from fixtures | fingerprint | status |"
        rule = "|---|---|---|---|---|---|---|"
    lines = [header, rule]
    for row in rows:
        fixtures = str(row.fixtures) if row.fixtures else "—"
        proven = (
            f"{row.fixture_sessions} ses / {row.fixture_messages} msg"
            if row.fixtures
            else "—"
        )
        fingerprint = "✓" if row.conformance else "—"
        reader = "✓" if row.reader else "—"
        lines.append(
            f"| `{row.cli}` | {row.store} | {reader} | {fixtures} | {proven} | {fingerprint} "
            f"| {_cell(row.status, lang)} |"
        )
    return "\n".join(lines)


def summary(rows: list[Row] | None = None) -> dict:
    rows = rows if rows is not None else build_rows()
    out: dict[str, int] = {}
    for row in rows:
        out[row.status] = out.get(row.status, 0) + 1
    out["total"] = len(rows)
    return out


def write_baselines(rows: list[Row] | None = None) -> int:
    """Persist the derived matrix as JSON for CI diffing (machine-independent)."""
    rows = rows if rows is not None else build_rows()
    target = REPO / "config" / "support-matrix.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": MATRIX_VERSION,
        "rows": [r.to_dict() for r in rows],
        "summary": summary(rows),
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    target.write_text(text, encoding="utf-8", newline="\n")
    return len(rows)


def unproven(rows: list[Row] | None = None) -> list[str]:
    """CLIs that claim a reader but have no fixture evidence."""
    rows = rows if rows is not None else build_rows()
    return [r.cli for r in rows if r.reader and r.status in ("unverified", "fixture-fails")]
