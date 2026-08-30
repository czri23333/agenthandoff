"""Bundle → continuation-brief renderer (see spec/resume-prompt-spec.md).

Sections carry priorities; when the brief exceeds the character budget,
lowest-priority sections are dropped whole. Protected sections are never dropped
whole — the resume pack is trimmed **from its oldest turn** instead, so a tight
budget costs the stalest context rather than the freshest.

That rule is the point of this module. A brief can only ever summarise: the
freshest turns used to be the first casualty of a tight budget, which is
backwards for the scenario the tool exists for — a session killed by quota has
the least budget *and* the most to preserve. Vendor practice agrees: OpenCode
refuses to prune the newest 40 000 tokens and the last two user turns; MiMo
checkpoints at 20/45/70 % of the window rather than at the wall
(docs/context-management-survey.md).
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
    "resume_pack": "recent context (verbatim, oldest first)",
    "unfinished": "the previous reply was cut off here — continue this sentence",
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
    "resume_pack": "接续上下文（原文，按时间顺序，旧→新）",
    "unfinished": "上一段回复在这里被截断——请接着写",
}

# (section, drop-priority) — 1 = never dropped whole, 4 = dropped first.
# The verbatim tail is what a context death takes with it, so it is protected and
# trimmed only from its oldest end. `digest` holds older assistant conclusions,
# which are the cheapest thing to lose once the pack is present — so it still
# goes first, exactly as before.
_ORDER = [
    ("project", 1),
    ("interruption", 1),
    ("steps", 1),
    ("resume_pack", 1),
    ("rules", 2),
    ("facts", 2),
    ("objective", 3),
    ("open", 3),
    ("artifacts", 3),
    ("digest", 4),
]

# Never removed wholesale; only trimmed from the oldest end.
_PROTECTED = ("project", "resume_pack")

# Even under a brutal budget, that many recent turns stay verbatim.
_MIN_TURNS_KEPT = 2


def _bullet(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) if items else "- (none)"


def _numbered(items: list[str]) -> str:
    if not items:
        return "1. (none recorded)"
    return "\n".join(f"{n}. {i}" for n, i in enumerate(items, 1))


def _pack_body(recent: list[tuple[str, str]], unfinished: str, t: dict[str, str]) -> str:
    parts = [f"[{role}] {text}" for role, text in recent]
    if unfinished:
        parts.append(f"[{t['unfinished']}]\n{unfinished}")
    return "\n\n".join(parts)


def render_brief(
    b: HandoffBundle,
    lang: str = "en",
    max_chars: int = 12000,
    with_pack: bool = True,
) -> str:
    """Compile a bundle into a paste-ready brief within ``max_chars``."""
    t = _SCAFFOLD_ZH if lang == "zh" else _SCAFFOLD_EN
    updated = b.meta.updated_at or "unknown"

    sections: dict[str, str] = {
        "project": (
            f"cwd: {b.meta.cwd}\n"
            f"source: {b.meta.cli} session {b.meta.session_id} "
            f'("{b.meta.title}"), last active {updated}'
            + (f"\nprovider: {b.meta.provider}" if b.meta.provider else "")
            + (f"\nparent session: {b.meta.parent_session_id}" if b.meta.parent_session_id else "")
            + (("\nnotes: " + "; ".join(b.meta.notes)) if b.meta.notes else "")
        ),
        "objective": b.objective or "(not captured)",
        "facts": _bullet(b.done),
        "open": _bullet(b.in_progress + b.blocked),
        "rules": _bullet(b.directives),
        "artifacts": _bullet([f"`{p}` (×{n})" for p, n in b.files]),
        "steps": _numbered(b.next_steps),
        "digest": _bullet(b.context_notes),
    }

    recent = list(b.recent)
    if with_pack and (recent or b.unfinished):
        sections["resume_pack"] = _pack_body(recent, b.unfinished, t)

    # Interruption warning: only when the session actually ended mid-flight, and
    # priority 1 so it survives any budget.
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
        parts = ["# Continuation brief (agenthandoff v0.2)", "", t["intro"], ""]
        for name, _prio in _ORDER:
            if name in active:
                parts.append(f"<{t[name]}>\n{active[name]}\n</{t[name]}>")
                parts.append("")
        return "\n".join(parts).rstrip() + "\n"

    brief = assemble(sections)
    if len(brief) <= max_chars:
        return brief

    # Pass 1: the cheap-to-lose sections go first — older summaries and long
    # anchor lists (priority >= 3).
    for name, prio in sorted(_ORDER, key=lambda x: -x[1]):
        if prio < 3:
            break
        if name in sections:
            del sections[name]
            brief = assemble(sections)
            if len(brief) <= max_chars:
                return brief

    # Pass 2: sacrifice the OLDEST verbatim turns, never the newest. This comes
    # before dropping rules/facts: user corrections are short and irreplaceable,
    # stale context is neither.
    while len(recent) > _MIN_TURNS_KEPT:
        recent.pop(0)
        sections["resume_pack"] = _pack_body(recent, b.unfinished, t)
        brief = assemble(sections)
        if len(brief) <= max_chars:
            return brief

    # Pass 3: last resort — the remaining unprotected sections.
    for name, _prio in sorted(_ORDER, key=lambda x: -x[1]):
        if name in sections and name not in _PROTECTED:
            del sections[name]
            brief = assemble(sections)
            if len(brief) <= max_chars:
                break
    return brief
