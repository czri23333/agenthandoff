# agenthandoff

**把任意 AI 编码 CLI 的会话接力给下一个 —— 确定性、纯本地、零依赖。**

英文说明见 [README.md](README.md)。

## 解决什么问题

长会话的死法都一样：上下文窗口撑爆，新会话从零开始——除非你手工把任务、
已做的决定、踩过的坑、文件布局重新解释一遍。`agenthandoff` 把这个交接
流程自动化：

1. 读取每个 CLI **自己的本地会话存储**（SQLite / JSONL / zstd-JSONL），
2. 确定性地提取 durable 状态（目标 / 已完成 / 进行中 / 用户修正 / 文件锚点 / 下一步），
3. 产出两样东西：
   - **Handoff Bundle**：可移植、人可读的 markdown 交接包（带 JSON Schema），
   - **continuation brief**：按优先级裁剪、带字符预算的启动提示词，粘进
     *任意* CLI 的新会话即可继续。

无 API key、不联网、无 LLM 参与。同样输入 ⇒ 逐字节相同的输出——交接包
可 diff、可信。

## 支持的 CLI

证据分级：**已读** = 在维护者本机（2026-08-31，单台 Windows）解析过真实存储；
**未验证** = 代码在，但没人喂过它数据；**已证实** = 仓库内脱敏夹具在 CI 里被解析
（目前还没有任何一行达到这个级，见 [docs/limitations.md](docs/limitations.md)）。
请在自己机器上跑 `handoff doctor`——它才是这张表的真相来源。

| CLI | 读取的存储 | 证据 |
|---|---|---|
| ZCode | SQLite（`~/.zcode/cli/db/db.sqlite`） | ✅ 已读 — 453 个会话 |
| Qoder CN IDE | JSONL（`~/.qoder-cn/projects/…`，qoder-cn 家族共享） | ✅ 已读 — 118 个文件 |
| CodeBuddy | JSONL（`~/.codebuddy/projects/…`） | ✅ 已读 — 32 个文件 |
| Qoderwork（含 CN，双账号） | JSONL（`~/.qoderwork[cn]/projects/…`） | ✅ 已读 — 13 个文件，3 个账号配置 |
| Qwen Work CN | JSONL（`~/.qwenworkcn/projects/…`） | ✅ 已读 — 1 个文件 |
| dsh (DeepSeekHarness) | zstd-JSONL（`~/.dsh/sessions/…`） | ✅ 已读 — 46 个归档，含 WSL 内的存储 |
| Kimi CLI | `state.json` + `wire.jsonl` | 🧪 只读过一次 — 实验性 |
| Codex CLI | `~/.codex/sessions` | ❌ 检测到了但读不出 — rollout 结构已变 |
| Claude Code | JSONL（`~/.claude/projects/…`） | ⚠️ 未验证（没有真实存储可测，也没有夹具） |
| CodeBuddy CN | JSONL（`~/.codebuddy-cn/projects/…`） | ⚠️ 未验证 |
| opencode | `~/.local/share/opencode/storage` | 🔜 路线图 |
| Trae / IDE 形态（SQLite 状态） | 各家用户数据目录 | 🔜 路线图，且只做只读 |

WSL 发行版内的会话存储会从 Windows 侧自动发现并读取（`handoff doctor`
中以 `[wsl]` 标注）。

## 哪些地方还不成

诚实清单在 [docs/limitations.md](docs/limitations.md)：哪些支持声明有真实数据支撑、
哪些没验证过、以及 15 条已知不足——包括最要命的那条：额度耗尽后生成的接力提示词，
目前最先丢掉恰恰是最近的上下文。下面这段话如果听着像营销，就去读那个文件。

## 快速开始

```bash
pip install "agenthandoff[zstd]"     # 或 pipx / uv tool install
# 尚未发布到 PyPI —— 源码安装：git clone 后 pip install -e ".[dev,zstd]"
handoff doctor                       # 本机有哪些 CLI 存储、哪些可读
handoff list                         # 跨 CLI 列出最近会话
handoff list --cwd myproject -n 5
handoff capture                      # 最新会话 → bundle 输出到 stdout
handoff capture sess_c66487e -o handoff.md
handoff resume handoff.md            # → 启动提示词（粘贴到新会话）
handoff resume handoff.md --lang zh --max-chars 8000
handoff search "cockpit"               # 跨全部会话全文检索
handoff ui --open                   # 驾驶舱 WebUI（127.0.0.1:8620，需 [server] 扩展）
handoff publish handoff.md          # 把交接包投放到 exchange 目录
handoff inbox                       # 查看其他 agent 留下的交接包
handoff threads                     # 同一任务散落在多个 CLI 的会话聚类
handoff backup                      # 快照全部会话存储（源目录只读）
```

全程只读，绝不写入任何 CLI 的存储。

## 为什么不直接"让 agent 自己写交接文件"

市面上大多数交接工具是给模型挂一个 skill/prompt："结束前写一份
HANDOFF.md"。它恰恰在最需要的时候失效：会话崩溃、上下文撑爆、模型不配合。
它还是非确定性的——两次交接无法 diff，"已完成"无从核实。

`agenthandoff` 反转了这个设计：**CLI 自己的事件日志才是事实源**。待办状态
来自 todo 表，文件锚点来自真实工具调用，用户修正来自用户自己的发言。
调研依据见 [docs/research.md](docs/research.md)。

## 设计文档

- [架构设计](docs/architecture.md)
- [竞品调研](docs/research.md)
- [Bundle 格式规范](spec/handoff-bundle-spec.md)
- [启动提示词规范](spec/resume-prompt-spec.md)

## 隐私

- 会话内容不出本机，零网络调用。
- 仓库测试夹具全部为合成数据，不含任何真实会话记录。
- 交接包只写到 `--out` 指定的位置。

## 许可

[MIT](LICENSE)
