# 逐消息模型/消耗覆盖率与不可达证明（2026-09-03 实测）

> 方法：各 CLI 取最近 ≤4 会话，统计消息级 `model` / `tokens_in|out` /
> `raw_text` 覆盖率。缺失项逐项翻过候选数据源，结论为“有”则补，
> “无”则给出穷尽路径（不可达证明），绝不虚构。

## 覆盖率表

| CLI | 消息 | model | tokens | raw | 说明 |
|---|---|---|---|---|---|
| zcode | 3855 | 66% | 62% | 0% | message.data.modelID/tokens；user 行无模型属正常 |
| codex | 2029 | 87% | 86% | 12% | turn_context 模型 + token_count 回填/pending |
| opencode | 406 | 66% | 66% | 0% | message/modelID + tokens（user 行无） |
| cherrystudio | 609 | 100% | 22% | 2% | message.model/usage（usage 仅部分行有） |
| workbuddy | 328 | 91% | 1% | 22% | providerData.model；tokens 仅会话级配额（见下） |
| codebuddy | 132 | 88% | 3% | 18% | 同上（transcript 无逐消息 usage） |
| qoderwake-cn | 40 | 100% | 0% | 0% | 会话级 model_id 继承；库无 usage 表 |
| dsh | 917 | 48% | 21% | 22% | request/context 模型 + turn usage；老 turn 无 usage chunk |
| qoderwork-cn | 180 | 99% | 0% | 76% | providerData.model；transcript 无 usage |
| qodercn-ide(uuid) | 418 | 44% | 0% | 89% | runtime-config 模型继承；老会话无该行 |
| qodercn-ide(task-) | 1484 | 0% | 0% | 89% | 不可达（见 §1） |
| qoderwork-app/cn-app | 171 | 0% | 0% | 45% | 不可达（见 §2）；linked_cli_sessions 跨源注记 |
| qwenwork-app | 0 | — | — | — | 空库（matrix empty 状态） |
| kimi | 0 | — | — | — | wire 无对话行（empty_wire 注记） |

## §1 task-/quest 类会话不可达证明

候选数据源（全部翻过，2026-09-03）：

1. transcript（`~/.qoder-cn/projects/*/*.jsonl`）：行类型仅
   progress/session_meta/assistant/user；assistant 行如
   `{"type":"assistant","message":{"role","content":[{"thinking","type"}]}}`——
   无 model/usage 键（全库正则扫描零命中）。
2. quest 快照（`state.vscdb` 的 `aicoding.questTaskListSnapshot`）：任务有
   `runtime` 键但全为 null（5 活跃 + 1 归档任务逐项检查）。
3. `state.vscdb` 其余 382 键：`aicoding-chat-*.state.hidden` 仅视图标记
   （`{id,isHidden}`），无账单。
4. `.qoder-cn/.models/<uuid>/catalog-v5/v6`：加密二进制（VISX 头），内容不透明；
   维持只计数账号数、不解密。
5. 运行日志（`Roaming/QoderCN/logs/*/main.log` 200KB）：无模型 id 字符串。
6. `chatEditingSessions/task-*/contents/`：编辑器文件快照（代码文本），
   非对话非账单。`cache/experts/task-*/`：空 agents/inboxes + metadata.json，
   无账单。

结论：task- 类逐消息账单在本机磁盘不可达。UI 以“本存储不记模型”诚实标注。

## §2 桌面端 app 系不可达证明

`%APPDATA%/QoderWork*/data/agents.db` 全表扫描：

- `messages` 列：id/message_id/chat_id/sub_chat_id/sequence/role/parts/
  metadata/searchable_text/search_status/created_at/updated_at——无模型/消耗列。
- `parts` JSON 类型枚举：text/tool-*/error——tool 输入无模型键（全库扫描零命中
  `model` 键）。
- `metadata` JSON：仅 source/sessionId/durationMs/numTurns/resultSubtype 等——
  无模型/消耗。
- 关联：`metadata.sessionId` 对应 CLI JSONL 会话 id，已注记为
  `linked_cli_sessions:<sid>` 并在 Detail 渲染跨端跳转按钮。

结论：app 系逐消息账单在库内不可达；跨源关联是当前最优解。

## §3 dsh/老 turn 缺失说明

dsh turn 级 usage chunk 只存在于新 roll；老 turn 只有 text 流。
已按 turn 合并（usage 有则附，无则空），不向前虚构。

## §4 降级验收确认（2026-09-03，用户逐项确认）

1. quest/task 类逐消息 model+tokens：接受降级（7 处数据源穷尽，§1）。
   UI 以“本存储不记模型”+ `model_selector` 注记展示。
2. 桌面端 app 系逐消息 tokens：接受降级（库内无字段，§2 全扫描为证）。
   模型已 171/171（`model_level` 继承）+ `context_fill` 水位 + 跨源跳转。
3. workbuddy 系/dsh 老 turn 逐消息 usage：接受现状（会话级配额 + 逐消息模型）。
   结项。
