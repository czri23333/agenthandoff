# 全软件发散式改进计划（2026-09-03，走查验收后）

> 来源：任务树展开（dsh 父节点 ▾17 子会话）+ Detail 分组截图走查、
> 全量 Agent 存储盘点（20 解析器）、217 passed 回归。
> 本轮已落地见 §0；§1 起为待办，按收益排序。

## §0 本轮已落地（证据）

- Dashboard TS1005 修复：`grouped.map` 重构为 `DomainGroup/SessionRow` 组件，
  `web/src/views/Dashboard.tsx`，`tsc -b` exit 0。
- 任务树：`/api/sessions` 父→子嵌套（16 父节点），`server/app.py`；
  走查：dsh 父节点 ▸17→▾ 展开截图。
- Detail 分组：预算/目标/话题分段/三栏/关键指令/下一步/接力词/恢复命令，
  `dsh/session-6893…` Detail 截图。
- 新解析器：`cherrystudio`（10 会话/879 消息）、`qoderwork-app`（1）、
  `qoderwork-cn-app`（2）、`qwenwork-app`（空库占位）；`qodersec` 锚点
  合并进 qoderwork 系 `files_touched`（fixture 树豁免）。
- 证据链：fixture（sanitize 补 FTS/STATIC_NAMES/%APPDATA%）、
  `conformance/*.json`×3、matrix/README 刷新、新 CLI 配色、217 passed。

## §1 解析覆盖缺口（按“有真实对话”优先）

1. `qwenwork-app` 空库：线上 0 会话，当前无 fixture = 诚实状态；
   若其库未来出现 chats，需补 fixture + conformance（脚本已通用）。
2. `.qoder-cli/ai-stats` 文件遥测：sessionId 与 IDE 会话 3/5 重合，
   可做 `qodercn-ide` load 的按 session 精确文件锚点（优于 qodersec 全局合并）。
3. IDE `chatEditingSessions`（workspaceStorage）：state.json 仅编辑 timeline，
   无对话——确认为非会话，不建解析器（已结论，记于此防重查）。
4. `cache/experts/task-*.session.execution/` 空壳目录：无对话，不建解析器。
5. 国际版 `.qoder`（仅 browser-connector）：无会话数据，不建解析器。

## §2 渲染与交互（走查发现的“可更好”）

1. Dashboard 首屏 217 行一次性渲染：虚拟化或分页（当前 DOM 快照 214KB，
   低端机卡顿风险）。
2. 子会话展开态无 URL 同步：刷新丢失展开态；可把 open=sid 记入 hash。
3. Detail 右侧接力词面板在窄屏下被截断（截图右侧滚动条）：移动端断点补。
4. `⚠ 等你回复 8` 按钮语义不明：hover 提示补“哪些会话等你”。
5. 时间显示混用（1m ago/3h ago/17d ago + 绝对时间缺失）：title 补绝对时间。

## §3 数据与证据链

1. qodersec 全局锚点按会话归属细化：execution.json 文件名 task-id 若能在
   transcript 中反查到对应会话，则改为精确合并，消除跨会话虚增。
2. conformance 基线对“补充源”分开计数：`files_transcript` vs `files_supplement`，
   让漂移报告可解释（本次 qoderwork file_anchors 0→814 曾误报 drift）。
3. matrix 对 0 会话 store（qwenwork-app）显式标注“空库·已验证无数据”，
   区别于 unverified（无 fixture）。

## §4 工程卫生

1. `sanitize_fixtures.py` FTS/trigger/sqlite_sequence 跳过已修；
   后续新增 sqlite store 若带 R*Tree/FTS5，开箱即用。
2. 前端 bundle 体积（index-FXFrNxex.js 1.4MB）：路由懒加载 Detail 面板。
3. 30s 轮询 `load()` 全量 JSON 对比（`JSON.stringify(prev)===JSON.stringify(s)`）：
   524 会话下每轮序列化开销大，改 ETag/增量。
