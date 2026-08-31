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

from agent_handoff import fixtures
from agent_handoff.parsers import all_parsers

REPO = Path(__file__).resolve().parent.parent.parent
# Single source of truth for what a fixture is and what it proves: the same
# helpers back the conformance gate and tests/test_fixtures.py, so a row in this
# table cannot mean something different from the assertion that guards it.
FIXTURE_ROOT = fixtures.FIXTURE_ROOT
BASELINE_ROOT = fixtures.BASELINE_ROOT

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

# The zh table must not be an English table with a Chinese heading. Unknown
# descriptions fall back to the source text rather than disappearing.
STORE_ZH = {
    "JSONL dir": "JSONL 目录",
    "SQLite (read-only URI)": "SQLite（只读 URI 打开）",
    "zstd JSONL dir": "zstd 压缩 JSONL 目录",
    "state.json + wire.jsonl": "state.json + wire.jsonl",
    "JSONL rollouts": "JSONL rollout 存档",
    "Electron leveldb — no session files on disk": "Electron leveldb——磁盘无会话文件",
    "storage layout undocumented": "存储布局无文档",
    "IDE SQLite; read-only only, never written": "IDE SQLite；只读，绝不写入",
    "per-vendor app data": "各厂商应用数据目录",
}


@dataclass
class Row:
    cli: str
    store: str
    reader: bool
    fixtures: int = 0
    fixture_sessions: int = 0
    fixture_messages: int = 0
    fixture_ok: bool = False
    shape_only: bool = False
    codec_missing: bool = False
    conformance: bool = False
    status: str = "unverified"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)




def derive_status(row: Row) -> str:
    """Status is a function of evidence, so it cannot be inflated."""
    if not row.reader:
        return "roadmap"
    if not row.fixtures:
        return "unverified"
    if row.codec_missing:
        # Says something about this environment, not about the format. Keep it
        # out of the "our parser is broken" bucket, and out of the counts.
        return "unavailable"
    if row.shape_only:
        return "shape-only"
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
        evidence = fixtures.measure(parser)
        row.fixtures = evidence.files
        row.fixture_sessions = evidence.sessions
        row.fixture_messages = evidence.nonempty
        row.fixture_ok = evidence.proven
        row.shape_only = evidence.shape_only
        row.codec_missing = evidence.codec_missing
        if evidence.error:
            row.notes.append(evidence.error)
        if evidence.sampled:
            row.notes.append("record-sampled")
        row.status = derive_status(row)
        rows.append(row)
    for cli in ROADMAP:
        if cli not in registered:
            rows.append(
                Row(cli=cli, store=ROADMAP[cli], reader=False, status="roadmap")
            )
    return rows


# Terminal cells: no glyph is encodable on a cp936/cp1252 console, so the CLI
# output spells its labels out. The Markdown table keeps the emoji.
ASCII_CELL = {
    "stable": "[ok] stable (fixture-proven)",
    "experimental": "[exp] experimental",
    "shape-only": "[--] shape only (source store held no dialogue)",
    "unverified": "[gap] unverified (no fixture)",
    "fixture-fails": "[!!] fixture fails to parse",
    "unavailable": "[env] needs an optional codec here",
    "roadmap": "[next] roadmap",
}


def _cell(status: str, lang: str, ascii_cell: bool = False) -> str:
    if ascii_cell:
        return ASCII_CELL.get(status, status)
    zh = {
        "stable": "✅ 稳定（有夹具证据）",
        "shape-only": "⬜ 仅形态（源存档无对话内容）",
        "unavailable": "❓ 本机缺少可选解码器（`pip install '.[zstd]'`）",
        "experimental": "🧪 实验性",
        "unverified": "⚠️ 未验证（缺脱敏夹具）",
        "fixture-fails": "❌ 夹具解析失败",
        "roadmap": "🔜 路线图",
    }
    en = {
        "stable": "✅ stable (fixture-proven)",
        "shape-only": "⬜ shape only (source store held no dialogue)",
        "unavailable": "❓ needs an optional codec (`pip install '.[zstd]'`)",
        "experimental": "🧪 experimental",
        "unverified": "⚠️ unverified (no fixture)",
        "fixture-fails": "❌ fixture fails to parse",
        "roadmap": "🔜 roadmap",
    }
    table = zh if lang == "zh" else en
    return table.get(status, status)


def render_markdown(
    lang: str = "en", rows: list[Row] | None = None, ascii_cell: bool = False
) -> str:
    """The support table. `ascii_cell` is for a console that cannot encode emoji."""
    rows = rows if rows is not None else build_rows()
    if lang == "zh":
        header = "| CLI | 存储形态 | 读取 | 脱敏夹具 | 夹具读出 | 格式指纹 | 状态 |"
        rule = "|---|---|---|---|---|---|---|"
    else:
        header = "| CLI | store | reader | fixtures | proven from fixtures | fingerprint | status |"
        rule = "|---|---|---|---|---|---|---|"
    blank = "-" if ascii_cell else "—"
    lines = [header, rule]
    for row in rows:
        store = STORE_ZH.get(row.store, row.store) if lang == "zh" else row.store
        fixtures = str(row.fixtures) if row.fixtures else blank
        proven = (
            f"{row.fixture_sessions} ses / {row.fixture_messages} msg"
            if row.fixtures
            else blank
        )
        if row.shape_only or row.codec_missing:
            # Hide the counts: without the codec they measure the environment,
            # and a shape-only fixture would print "0 ses / 0 msg" as though the
            # parser had failed.
            proven = blank
            fixtures = "—" if row.codec_missing else fixtures
        yes, no = ("yes", "no") if ascii_cell else ("✓", "—")
        fingerprint = yes if row.conformance else no
        reader = yes if row.reader else no
        lines.append(
            f"| `{row.cli}` | {store} | {reader} | {fixtures} | {proven} | {fingerprint} "
            f"| {_cell(row.status, lang, ascii_cell)} |"
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
    missing = ("unverified", "fixture-fails")
    return [r.cli for r in rows if r.reader and r.status in missing]
