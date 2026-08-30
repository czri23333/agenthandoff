# Resume Prompt Specification v0.1

The bundle markdown is for humans. The **resume prompt** (continuation brief)
is the machine-facing artifact: the exact text a user pastes into the next
agent session. This spec defines its structure, priorities, and budget
policy so output is deterministic and reviewable.

## Design principles

1. **Prevent redoing work.** The brief opens with an explicit instruction
   that completed work must not be repeated — the single most expensive
   failure mode when resuming.
2. **Separate facts from instructions.** `<facts>` (what is already done,
   verifiable) never mixes with `<rules>` (user corrections that must be
   obeyed). Mixing them causes models to re-litigate settled decisions.
3. **Executable steps.** Next steps are numbered and imperative, phrased so
   the first one can be started with no additional exploration.
4. **Anchored files.** Key artifacts are listed as concrete paths, not
   descriptions, so the new session can verify state before acting.
5. **Budgeted.** The brief fits a configurable character budget
   (`--max-chars`, default 12000) by dropping low-priority sections whole —
   never by truncating a section mid-item.

## Template

```
# Continuation brief (agenthandoff v0.1)

You are taking over an in-progress task from a previous agent session.
Do NOT redo work listed under <facts>. Start from <steps> item 1.

<project>
cwd: {cwd}
source: {cli} session {session_id} ("{title}"), last active {updated_at}
</project>

<interruption>  # only rendered when the session ended mid-flight
WARNING: the previous session ended abruptly — {interruption}.
Treat state below as possibly incomplete.
</interruption>

<objective>
{objective}
</objective>

<facts>
- {done[0]}
- {done[1]} …
</facts>

<open>
- {in_progress} / {blocked}
</open>

<rules>   # user corrections from the previous session — obey these
- {directive[0]}
- {directive[1]} …
</rules>

<artifacts>
- {path} (×{hits})
</artifacts>

<steps>
1. {next_step[0]}
2. {next_step[1]} …
</steps>

<digest>  # last assistant conclusions, lowest priority, dropped first
{context_notes}
</digest>
```

## Section priority (for budget trimming)

| Priority | Section | Rationale |
|---|---|---|
| 1 (never dropped) | header, `<project>`, `<interruption>`, `<steps>` | Resuming is meaningless — and dangerous when the session was interrupted — without these |
| 2 | `<rules>`, `<facts>` | Prevents re-violating user corrections / redoing work |
| 3 | `<objective>`, `<open>`, `<artifacts>` | Orientation; recoverable from repo state |
| 4 (dropped first) | `<digest>` | Re-derivable; kept only while budget allows |

Algorithm: render the full brief; if it exceeds the budget, drop priority-4
sections, then re-render; continue down the table until it fits. Individual
items are never truncated mid-string — a half-rule is worse than no rule.

## Language

The scaffolding (section tags, fixed sentences) is English by default for
cross-model compatibility; user-authored content (directives, notes, steps)
is passed through verbatim in its original language. `--lang zh` switches the
scaffolding to Chinese for Chinese-first target CLIs.

## Example (synthetic)

```
# Continuation brief (agenthandoff v0.1)

You are taking over an in-progress task from a previous agent session.
Do NOT redo work listed under <facts>. Start from <steps> item 1.

<project>
cwd: D:\demo\webapp
source: zcode session sess_demo01 ("Fix login redirect loop"), last active 2026-08-30T12:00:00+00:00
</project>

<objective>
Fix the login redirect loop on the /dashboard route
</objective>

<facts>
- Root cause identified: middleware runs before session cookie is set
- Reproduced in tests: tests/test_login.py::test_redirect_loop
</facts>

<open>
- (none recorded)
</open>

<rules>
- 不要引入新的依赖，用现有中间件修复
- wrong approach: do not redirect to /login from middleware
</rules>

<artifacts>
- src/middleware/auth.ts (×12)
- tests/test_login.py (×4)
</artifacts>

<steps>
1. Move the session-cookie check after cookie assignment in src/middleware/auth.ts
2. Re-run tests/test_login.py::test_redirect_loop until green
</steps>
```
