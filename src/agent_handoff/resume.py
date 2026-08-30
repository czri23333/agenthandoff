"""Bundle → continuation-brief renderer (see spec/resume-prompt-spec.md).

Sections carry priorities; when the brief exceeds the character budget,
lowest-priority (highest number) sections are dropped whole — items are
never truncated mid-string.
"""

from __future__ import annotations

from agent_handoff.model import HandoffBundle

_SCAFFOLD_EN = {
    "intro": (
        "You are taking over an in-progress task from a previous agent session.\n"
        "Do NOT redo work listed under <facts>. Start from <steps> item 1."
    ),
    "project": "project",
    "interruption": "interruption",
    "objective": "objective",
    "facts": "facts",
    "open": "open",
    "rules": "rules",
    "artifacts": "artifacts",
    "steps": "steps",
    "digest": "digest",
}

_SCAFFOLD_ZH = {
    "intro": (
        "你正在接手一个进行中的任务（来自上一个 agent 会话）。\n"
        "不要重做 <facts> 中已完成的工作。从 <steps> 第 1 条开始。"
    ),
    "project": "项目",
    "interruption": "中断警告",
    "objective": "目标",
    "facts": "已完成事实",
    "open": "进行中/待办",
    "rules": "必须遵守的规则（来自用户此前的修正）",
    "artifacts": "关键文件",
    "steps": "下一步",
    "digest": "背景摘要",
}

# (section, drop-priority) — 1 = never dropped, 4 = dropped first.
_ORDER = [
    ("project", 1),
    ("interruption", 1),
    ("steps", 1),
    ("rules", 2),
    ("facts", 2),
    ("objective", 3),
    ("open", 3),
    ("artifacts", 3),
    ("digest", 4),
]


def _bullet(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) if items else "- (none)"


def _numbered(items: list[str]) -> str:
    return "\n".join(f"{n}. {i}" for n, i in enumerate(items, 1)) if items else "1. (none recorded)"


def render_brief(b: HandoffBundle, lang: str = "en", max_chars: int = 12000) -> str:
    t = _SCAFFOLD_ZH if lang == "zh" else _SCAFFOLD_EN
    updated = b.meta.updated_at or "unknown"

    sections: dict[str, str] = {
        "project": (
            f"cwd: {b.meta.cwd}\n"
            f"source: {b.meta.cli} session {b.meta.session_id} "
            f'("{b.meta.title}"), last active {updated}'
        ),
        "objective": b.objective or "(not captured)",
        "facts": _bullet(b.done),
        "open": _bullet(b.in_progress + b.blocked),
        "rules": _bullet(b.directives),
        "artifacts": _bullet([f"`{p}` (×{n})" for p, n in b.files]),
        "steps": _numbered(b.next_steps),
        "digest": _bullet(b.context_notes),
    }
    # Interruption warning: only rendered when the session actually ended
    # mid-flight; priority 1 so it survives any budget.
    if b.interruption.detected:
        warn = (
            "WARNING: the previous session ended abruptly — "
            f"{b.interruption.describe()}. "
            "Treat state below as possibly incomplete."
        )
        if b.interruption.kind == "user_pending" and b.interruption.pending_user_text:
            warn += (
                "\nThe user's last instruction was never executed: "
                f'"{b.interruption.pending_user_text}" — it is already '
                "step 1 in <steps>."
            )
        sections["interruption"] = warn

    def assemble(active: dict[str, str]) -> str:
        parts = ["# Continuation brief (agenthandoff v0.1)", "", t["intro"], ""]
        for name, _prio in _ORDER:
            if name in active:
                parts.append(f"<{t[name]}>\n{active[name]}\n</{t[name]}>")
                parts.append("")
        return "\n".join(parts).rstrip() + "\n"

    brief = assemble(sections)
    if len(brief) <= max_chars:
        return brief

    # Drop whole sections, highest priority number first; ties → later in doc.
    for name, _prio in sorted(_ORDER, key=lambda x: -x[1]):
        if name in sections and name != "project":
            del sections[name]
            brief = assemble(sections)
            if len(brief) <= max_chars:
                break
    return brief
