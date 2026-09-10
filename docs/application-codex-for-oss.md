# Codex for OSS — 申请材料（agenthandoff）

> **状态：2026-09-09 已提交**（滚动评审，结果通过邮件通知）。提交回执截图留在本地，不入库（含个人信息）。
> 提交入口：**https://openai.com/form/codex-for-oss/**（需用你的 ChatGPT 账号登录提交；我无法代提交）
> 表单规则：评审是滚动进行的，通过后邮件通知。每个长字段**上限 500 字符**，下面的文本已按上限核对。
> 原则：每一句都可在本仓库复现；没有把握的数字一律不写（条款 §6：不实信息可被撤销）。

## 0. 提交前先备好这 5 项

| 字段 | 填什么 |
|---|---|
| First name / Last name | 你的真名 |
| Email | **与 ChatGPT 账号绑定的邮箱**（表单明确要求） |
| GitHub username | `czri23333`（确认 profile 是公开的） |
| GitHub repository URL | `https://github.com/czri23333/agenthandoff`（公开） |
| OpenAI Organization ID | platform.openai.com → Settings → Organization → General → Organization ID |

## 1. 字段文本（直接粘贴）

**Describe your role** → 选 `Primary maintainer`

**Why does this repository qualify?**（476 字符，上限 500）

```
agenthandoff is infrastructure for the coding-agent ecosystem: every AI CLI keeps sessions in a private format, so interrupted work is stranded. It reads 20 such stores read-only and compiles a brief any agent can paste. Codex is a first-class source - its rollout store is fixture-proven (19 sessions / 439 messages). Claims are measured, not typed: 11 CLI rows proven by sanitized fixtures in CI, 235 tests on 3 OSes x 3 Pythons, and CI fails if the published matrix drifts.
```

**I'm interested in...** → 勾选 `API credits for my project`；`Codex Security` 可选（勾选理由见「Anything else」，不勾也不影响主申请）

**How will you use API credits for your project?**（467 字符，上限 500）

```
Run Codex in CI on every pull request (the repo already runs a 9-leg test matrix): automated review, test-gap detection, release notes. A nightly vendor-drift sentinel - regenerate sanitized fixtures from real stores, run the conformance gate, open an issue/PR when a vendor changes its format (today users find that drift, not us). Release automation. And closing the honest gaps: proving the 8 readers currently labelled unverified by collecting sanitized fixtures.
```

**Anything else we should know?**（422 字符，上限 500）

```
Honest context: 10 days old, 0 stars - applying on ecosystem-importance grounds, as the program invites. Everything is verifiable from a clean clone: two gates (generated support matrix, format fingerprints) fail CI when a claim drifts from the fixtures, and docs/limitations.md lists what is not proven. Read-only by design, never touches credentials. Codex Security would help: the parsers consume untrusted vendor data.
```

## 2. 为什么这样写（对着官方口径）

官方原文的关键句：

- 「We look for projects with **meaningful usage, broad adoption, or clear importance to the software ecosystem**.」
- 「We review signals such as repository usage, **ecosystem importance, and evidence of active maintenance** — pull request review, issue triage, release management…」
- 「If a project does not neatly fit the criteria but **plays an important role in the ecosystem, applicants should still apply and explain why**.」

因此材料按「生态重要性 + 可验证的维护证据」组织，而不是硬凑采用量：

| 评审关心 | 我们给的事实 | 复现方式 |
|---|---|---|
| 生态重要性 | 20 个 AI CLI 的会话存储读取器；Codex 自己的 rollout 存储是一等来源（19 会话 / 439 消息） | `python -c "from agent_handoff.parsers import all_parsers; print(len(all_parsers()))"` |
| 使用/证明 | 11 行由脱敏夹具在 CI 中证明，8 行诚实标注 unverified | `python -m agent_handoff.evidence --check` |
| 活跃维护 | 235 个测试；CI 9 条腿（3 OS × 3 Python）全绿；两道证据门（支持表 + 格式指纹） | `pytest`；仓库 Actions 页 |
| 工程可信度 | 只读设计、零依赖核心、limitations 明列未证明项 | `docs/limitations.md` |

**没有写、也不该写的**：stars、下载量、用户数（现在是 0 / 未发布 / 1 人）。虚报会触发条款 §6 撤销。

## 3. 提交前的两个加分动作（都正当，且便宜）

1. **打一个 v0.1.0 标签 + GitHub Release**：表单明确看「release workflows」，且给评审一个稳定版本。标签我已推送；你只需在 GitHub 上点一次「Draft a new release」选 `v0.1.0` 发布。
2. **给仓库加 topics**：仓库首页右上 `About` ⚙ → `Topics`，建议填
   `ai-agents`、`codex`、`claude-code`、`session-management`、`local-first`、`developer-tools`。
   （有 token 的话我可以用 API 直接加；浏览器点也是一分钟。）

## 4. 诚实的风险与备选

- 项目 **2026-08-30 创建、10 天、0 star**：按常规标准命中率不高。但官方页面明确邀请「不够格也请申请并解释」，所以策略是把「生态角色 + 可验证的维护质量」讲清楚，而不是装作成熟项目。
- 若未通过：3–6 个月后带**真实采用数据**（stars、下载、issue/PR 活动）重申；那时申请文本里的「why qualify」可以换成真实数字。
- 若只想先拿 Codex 用起来：申请照投，同时项目本身已经支持把 Codex 会话接力出去（`handoff list --cli codex`）。

## 5. 提交清单（照着勾）

- [ ] ChatGPT 账号能登录，邮箱确认
- [ ] GitHub profile 与仓库都是 public
- [ ] Organization ID 已复制
- [ ] 三段文本已粘贴（并确认没被表单截断）
- [ ] 勾选 API credits（Codex Security 按需）
- [ ] 提交后把回执截图留档
