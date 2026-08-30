# AgentHandoff 单文件便携版 — Windows

> **未验证**：下面的构建步骤从未在本仓库执行过（没有 `dist/` 产物，
> 维护机未安装 PyInstaller）。这是一份提案，不是一份已跑通的配方。
> 见 docs/limitations.md 缺口 4。

**偏好**：本机 Windows 桌面用户偏好 **双击一个 exe 即开驾驶舱、关窗口即停**，无需 Python/npm。

## Build

```bat
pip install pyinstaller
pyinstaller agenthandoff-ui.spec  --clean --noconfirm
:: 产物：dist/agenthandoff-ui.exe   (含前端 dist，不含 zstd/可选 extras 时仍可跑，非 zstd 存储直接可用)
```

spec 已在 `agenthandoff-ui.spec` 中声明前端 static 的 `datas` 引入与
`agent_handoff/server/*` 的 hidden imports。Uvicorn 绑定 `127.0.0.1:8620`
（仅本机），浏览器自动打开 `http://127.0.0.1:8620`。托盘退出或关窗口即退出。

## Dev preview

```bat
handoff ui --open
```
