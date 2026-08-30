# -*- mode: python ; coding: utf-8 -*-
# pyinstaller agenthandoff-ui.spec  --clean --noconfirm  →  dist/agenthandoff-ui.exe
# 仅本机 (127.0.0.1:8620)，需 PyInstaller + 前端已构建（npm run build）。

from pathlib import Path

block_cipher = None

a = Analysis(
    ["src/agent_handoff/server/app.py"],
    pathex=[str(Path.cwd() / "src")],
    binaries=[],
    datas=[("src/agent_handoff/server/static", "agent_handoff/server/static")],
    hiddenimports=[
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "agent_handoff.server.app",
        "agent_handoff.parsers.zcode",
        "agent_handoff.parsers.jsonl_family",
        "agent_handoff.parsers.codex",
        "agent_handoff.parsers.dsh",
        "agent_handoff.parsers.kimi",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="agenthandoff-ui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # 无黑框，托盘退出即关；调试可改 True 看日志
    icon=None,
)
