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

| CLI | 读取的存储 | 状态 |
|---|---|---|
| ZCode | SQLite（`~/.zcode/cli/db/db.sqlite`） | ✅ 稳定 |
| Claude Code | JSONL（`~/.claude/projects/…`） | ✅ 稳定 |
| CodeBuddy / CodeBuddy CN | JSONL（`~/.codebuddy[cn]/projects/…`） | ✅ 稳定 |
| Qoderwork（含 CN，双账号） | JSONL（`~/.qoderwork[cn]/projects/…`） | ✅ 稳定 |
| Qoder CN IDE | JSONL（`~/.qoder-cn/projects/…`，qoder-cn 家族共享） | ✅ 稳定 |
| Qwen Work CN | JSONL（`~/.qwenworkcn/projects/…`） | ✅ 稳定 |
| dsh (DeepSeekHarness) | zstd-JSONL（`~/.dsh/sessions/…`） | ✅ 稳定（`[zstd]` 扩展） |
| Kimi CLI | `state.json` + `wire.jsonl` | 🧪 实验性 |
| Codex CLI | `~/.codex/sessions` | ✅ 稳定 |
| opencode | `~/.local/share/opencode/storage` | 🔜 路线图 |

WSL 发行版内的会话存储会从 Windows 侧自动发现并读取（`handoff doctor`
中以 `[wsl]` 标注）。

## 快速开始

```bash
pip install "agenthandoff[zstd]"     # 或 pipx / uv tool install
handoff doctor                       # 本机有哪些 CLI 存储、哪些可读
handoff list                         # 跨 CLI 列出最近会话
handoff list --cwd myproject -n 5
handoff capture                      # 最新会话 → bundle 输出到 stdout
handoff capture sess_c66487e -o handoff.md
handoff resume handoff.md            # → 启动提示词（粘贴到新会话）
handoff resume handoff.md --lang zh --max-chars 8000
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
