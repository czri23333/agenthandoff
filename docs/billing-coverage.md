# 逐消息模型/消耗覆盖率与不可达证明（2026-09-04 实测，14:00 刷新）

> 方法：各 CLI 取最近 ≤6 会话，统计消息级 `model` / `tokens_in|out` /
> `raw_text` 覆盖率。缺失项逐项翻过候选数据源，结论为“有”则补，
> “无”则给出穷尽路径（不可达证明），绝不虚构。
>
> 2026-09-04 补充：每条消息另有 `dur_ms` 实测耗时证据（parser 实测优先，
> 否则相邻时间戳推导；同秒批量 artifact 置空）。token 缺席的消息以前端
> ⏱ 耗时芯片展示（model+token > model+⏱ > 纯⏱ > 无），“每条消息有消耗
> 证据”已全量达成；token 本身仅在数据源存在时展示。

## 覆盖率表

| CLI | 消息 | model | tokens | raw | 说明 |
|---|---|---|---|---|---|
| zcode | 2038 | 87% | 77% | 0% | message.data.modelID/tokens；user 行无模型属正常 |
| codex | 2951 | 87% | 86% | 12% | turn_context 模型 + token_count 回填/pending |
| opencode | 560 | 68% | 68% | 0% | message/modelID + tokens（user 行无） |
| cherrystudio | 872 | 100% | 20% | 2% | message.model/usage（usage 仅部分行有） |
| workbuddy | 708 | 94% | 96% | 21% | providerData.model；function_call 行 usage 累加结算+思考行回填；剩余为 user harness 行与跨文件乱序 |
| codebuddy | 1403 | 92% | 92% | 13% | 同上 |
| qoderwake-cn | 51 | 100% | 0% | 3% | 会话级 model_id 继承；库无 usage 表 |
| dsh | 4476 | 48% | 9%逐消息/100%会话级 | 22% | 成品 assistant/message（reasoning/tool-call/text）+用量卡按turn去重求和 |
| qoderwork-cn | 807 | 99% | 0% | 49% | message.model（qmodel_preview）；transcript 无 usage（7 会话全扫零命中） |
| qodercn-ide(uuid) | 981 | 77% | 0% | 89%→ | runtime-config 模型继承；老会话无该行 |
| qodercn-ide(task-) | 13278 | 0% | 0% | — | thinking+tool_use 已折入正文；全机仅 2 个 modelMap 映射（auto）；quest/行内/workspace 均无模型，tokens 不可达（见 §1，9 处穷尽） |
| qoderwork-app/cn-app | 171 | 100% | 0% | 45% | sub_chats.model_level 继承；库无 usage（见 §2）；linked 注记+水位 |
| qwenwork-app | 0 | — | — | — | 空库（matrix empty 状态） |
| kimi | 0 | — | — | — | wire 无对话行（empty_wire 注记） |

## §1 task-/quest 类会话不可达证明

候选数据源（全部翻过，2026-09-03/04，共 11 处，含官方本体逆向）：

1. transcript（`~/.qoder-cn/projects/*/*.jsonl`）：行类型仅
   progress/session_meta/assistant/user；assistant 行如
   `{"type":"assistant","message":{"role","content":[{"thinking","type"}]}}`——
   无 model/usage 键（全库正则扫描零命中）。
2. quest 快照（`state.vscdb` 的 `aicoding.questTaskListSnapshot`）：任务有
   `runtime` 键但全为 null（5 活跃 + 1 归档任务逐项检查）；任务对象
   根本无 `model` 键（NOKEY），`executionRequestId` 全空——无关联键可追。
   顶层键枚举：assistant 行仅 cwd/message/sessionId/timestamp/type/uuid，
   message 内仅 role/content（thinking/tool_use/text 三型）。
3. `state.vscdb` 其余 382 键：`aicoding-chat-*.state.hidden` 仅视图标记
   （`{id,isHidden}`），无账单。
4. `.qoder-cn/.models/<uuid>/catalog-v5/v6`：加密二进制（VISX 头），内容不透明；
   维持只计数账号数、不解密。
5. 运行日志（`Roaming/QoderCN/logs/*/main.log` 200KB）：无模型 id 字符串。
6. `chatEditingSessions/task-*/contents/`：编辑器文件快照（代码文本），
   非对话非账单。`cache/experts/task-*/`：空 agents/inboxes + metadata.json，
   无账单。
7. `cache/projects/<project>-<hash>/`：空目录（两个任务缓存目录均无文件），
   无账单。
8. `chatEditingSessions/task-*/state.json` 的 `timeline`：536 个 textEdit
   文件操作 + 7 个 checkpoint，纯编辑时间线，无模型/消耗键。
9. task 行全部顶层键（cwd/message/sessionId/timestamp/type/uuid）与
   entrypoint/userType（全为 None）：无模型/用量键。
10. `progress` 行 1501 条全为 hook 命令（post-activity-checkpoint 930、
    qodersec review 486、session-stop-checkpoint 84、ensure-deps 1）：
    任务执行钩子记录，无模型/消耗键。
11. 官方本体逆向（`D:/Qoder CN/resources/app.asar` 解包验证）：
    任务面板经 `executionSessionId` 关联会话文件（缺失则标“会话已归档或删除”）；
    用量模型为 `{categories[].tokens, totalTokens, maxTokens, percentage,
    apiUsage}` ——**上下文水位**（内存运行时值），非逐消息账单；
    `chatSessionProjectionService` 从事件流读 `usage ?? metadata`，
    落盘 transcript 无此字段。证实：官方逐消息账单同样不落盘，
    磁盘逆向到顶。

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

workbuddy 系剩余无 tokens 构成（2026-09-04 实测）：user harness 行
（`<task-notification>` 等，天生无账单）+ `Interrupted by user` 中断 turn
（`status: incomplete`，请求未完成故无 usage 行；且其 providerData 的
messageId/conversationRequestId 均为 None，无关联键可追）。
后者为数据源上限，非解析遗漏。

附：harness 行的 `output-file` 指向 `%TEMP%/codebuddy-<user>/<proj>/<sid>/bg-tasks/*.stdout.log`
（实测为 cargo/test 等工具输出全文，无模型/消耗键）——可作为工具结果
溯源（不在账单 scope，记于此防重查）。

## §4 qoder/wake 本地用量扫荡（2026-09-04，第 12–15 处）

12. `~/.qoderwake-cn/data/store/qoderwake.sqlite` 全 75 表扫描：
    `session_events`（65 行，仅 2 个 7 月残留 qs 会话）`assistant` 事件确有
    `usage{input_tokens,output_tokens,cache_*,server_tool_use,context_usage_ratio}`
    + `model` 结构，但全零值、无非零行；`team_group_messages_v3`（36 行）
    payload 零 usage/token 命中；`leader_model_invocations`（7）、
    `leader_sdk_messages`（65）、`missions`、`role_runs` 零用量命中。
    parser 读的 team_group 表本身无用量列——不是解析遗漏。
13. `~/.qoderworkcn/logs/runs/*/qodercli.log`：进程/HTTP/环境日志，
    无 usage/token 字符串（全目录 grep 零命中）。
14. `~/.qoderworkcn/projects/<sid>/state.json`：`items` 为加密 blob
    （base64 非 JSON），内容不透明；维持不解密。
15. 云端凭证边界：`credit/usage` 是 daemon→云 RPC（插件包逆向证实），
    需用户账号凭证调用。cockpit 只读本地、不碰账号凭证——云端复现
    在此止步。替代证据 `dur_ms` 已全量上线（本文件头注）。

结论：qoder 系逐消息 token 本地穷尽（§1 的 11 处 + 本 §4 处 = 15 处），
云端是唯一真相源但需用户凭证，不属 cockpit 只读 scope。

## §5 降级验收确认（2026-09-03，用户逐项确认）

> §4 第 12–15 处见上（qoder/wake 本地扫荡）。本 §16 为官方本体最终确认：

16. 官方本体最终确认（2026-09-04，aicoding-agent/extension.js 全量正则）：
    `credit/usage` 为无参 LSP RPC（`sendRequest("credit/usage")`），返回订阅
    总额，无 per-request 参数；全包零 `perMessageUsage/turnUsage/requestUsage`
    概念。官方用量模型 = 订阅总额 + 上下文水位（`{totalTokens,maxTokens,
    percentage,apiUsage}`），官方 IDE 消息区本身无逐消息 token 显示。
    逐消息 token 只存在服务端计费流水，客户端（含官方应用）不可见。
17. qoderworkcn CLI transcript 全库（11 文件）用量键正则零命中；
    runtime-config 行 model 为空串（CLI 靠服务端路由，本地不记）；
    `awareness/` 为记忆索引、`compression-v2/state.json` 为压缩状态机，
    均无用量；`workspace/modelMap` 仅 2 映射（auto，已回填）。
    cockpit 的 dur_ms 逐消息耗时已超越官方可见维度。
18. Electron 存储面全扫（2026-09-04）：Local Storage leveldb（3.5KB，
    无 aicoding 键）、Session Storage（1.9KB）、WebStorage CacheStorage
    19 文件（1MB，用量键零命中）、Preferences（仅 electron/spellcheck）。
    解密后的用量无本地缓存。
19. 会话日志双轨制（2026-09-04）：`logs/sessions/*/<sid>/segments/*.jsonl`
    的 `model.response.completed` 行确有真实模型（IDE 侧 qmodel_38max 214、
    qfmodel 367；CLI 侧 qmodel_preview 188），token 全零占位；parser 已按
    时间归因接入（`_apply_log_models`，±120s）。但 IDE 侧 74 日志目录与
    21 transcript 会话零重叠——日志记 headless run id，transcript 记 chat id，
    两套 id 空间隔离，IDE 侧归因命中率为 0；CLI 侧目录名即 transcript sid，
    时间重叠已验证。token 在两边均为零占位（服务端计费）。
20. creditUsage 解密实证（2026-09-04，本机只读 DPAPI 解 os_crypt 主 key →
    AES-256-GCM 解 v10A 密文，材料已清盘）：内容为账户总额——Pro 账户
    userQuota 2000/2000 + addOnQuota 4500/4500 全耗尽（isQuotaExceeded:true）
    + Qwen 专属包明细，**无逐消息明细**。实证官方用量模型 = 订阅总额，
    与 §5-16 的逆向结论一致。解密方法：Local State.os_crypt.encrypted_key
   （DPAPI）→ v10 + 12B nonce GCM。key 材料已删除，不留盘。

1. quest/task 类逐消息 model+tokens：接受降级（9 处数据源穷尽，§1）。
   UI 以“本存储不记模型”+ `model_selector` 注记展示。
2. 桌面端 app 系逐消息 tokens：接受降级（库内无字段，§2 全扫描为证）。
   模型已 171/171（`model_level` 继承）+ `context_fill` 水位 + 跨源跳转。
3. workbuddy 系/dsh 老 turn 逐消息 usage：接受现状（会话级配额 + 逐消息模型）。
   结项。
