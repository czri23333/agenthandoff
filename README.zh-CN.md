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

<!-- MATRIX BEGIN: generated, do not edit -->
下表由 `tests/fixtures/sanitized/` 里的脱敏真实格式夹具推导生成，不是手写（推导日期见 `config/support-matrix.json`）。其中 8 项有夹具证据：克隆后运行 `pip install -e . && python -m agent_handoff.evidence --check` 即可复现；其余状态标注的是证据缺口，不是功能承诺。

| CLI | 存储形态 | 读取 | 脱敏夹具 | 夹具读出 | 格式指纹 | 状态 |
|---|---|---|---|---|---|---|
| `zcode` | SQLite（只读 URI 打开） | ✓ | 2 | 3 ses / 46 msg | ✓ | ✅ 稳定（有夹具证据） |
| `claude` | JSONL 目录 | ✓ | — | — | — | ⚠️ 未验证（缺脱敏夹具） |
| `codebuddy` | JSONL 目录 | ✓ | 25 | 24 ses / 59 msg | ✓ | ✅ 稳定（有夹具证据） |
| `codebuddy-cn` | JSONL 目录 | ✓ | — | — | — | ⚠️ 未验证（缺脱敏夹具） |
| `qoderwork` | JSONL 目录 | ✓ | 4 | 2 ses / 3 msg | ✓ | ✅ 稳定（有夹具证据） |
| `qoderwork-cn` | JSONL 目录 | ✓ | 25 | 2 ses / 34 msg | ✓ | ✅ 稳定（有夹具证据） |
| `qodercn-ide` | JSONL 目录 | ✓ | 25 | 5 ses / 31 msg | ✓ | ✅ 稳定（有夹具证据） |
| `qwenwork` | JSONL 目录 | ✓ | 3 | 1 ses / 2 msg | ✓ | ✅ 稳定（有夹具证据） |
| `dsh` | zstd 压缩 JSONL 目录 | ✓ | 4 | 3 ses / 7 msg | ✓ | ✅ 稳定（有夹具证据） |
| `kimi` | state.json + wire.jsonl | ✓ | 4 | — | ✓ | ⬜ 仅形态（源存档无对话内容） |
| `codex` | JSONL rollout 存档 | ✓ | 21 | 19 ses / 426 msg | ✓ | ✅ 稳定（有夹具证据） |
| `qoder-ide` | Electron leveldb——磁盘无会话文件 | — | — | — | — | 🔜 路线图 |
| `opencode` | 存储布局无文档 | — | — | — | — | 🔜 路线图 |
| `trae` | IDE SQLite；只读，绝不写入 | — | — | — | — | 🔜 路线图 |

图例：稳定 = 夹具能解析出真实对话；仅形态 = 源存档本身没有对话内容；未验证 = 有读取器但没有夹具；夹具解析失败 = 夹具读不出来；路线图 = 尚无读取器；本机不可用 = 这里缺可选解码器。
<!-- MATRIX END -->


WSL 发行版内的会话存储会从 Windows 侧自动发现并读取（`handoff doctor`
中以 `[wsl]` 标注）。

## 哪些地方还不成

诚实清单在 [docs/limitations.md](docs/limitations.md)：哪些支持声明有夹具解析作证、哪些只
是写了读取代码却没验证过、以及已知不足——其中最要紧的两条是：夹具只能把格式冻结在采样那一刻，
以及驾驶舱从未在并发压力下实测过。下面任何一句听起来像宣传的话，都请以那份文件为准。

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

## 开发与验证

```bash
pip install -e ".[dev,zstd,server]"
pytest                                   # 库 + 每一个随仓库分发的脱敏夹具
handoff matrix                           # 支持矩阵：由夹具推导，不手写
python -m agent_handoff.evidence --check      # README/JSON 与夹具是否一致
python -m agent_handoff.conformance --check   # 格式指纹是否发生漂移
```

上表每一格的证据都在仓库里：夹具是真实存档的脱敏样本（结构保留、内容替换），
CI 里解析并断言其形态。任何一格与夹具不符，CI 直接红。

## 许可

[MIT](LICENSE)
