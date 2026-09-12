# -*- mode: python ; coding: utf-8 -*-
# Python sidecar 打包配置（Web 后端）
# 构建：python -m PyInstaller ncmp-server.spec --noconfirm --clean --distpath dist-sidecar
import os

PROJECT_ROOT = os.path.abspath(SPECPATH)

a = Analysis(
    ["sidecar_main.py"],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=[
        (os.path.join(PROJECT_ROOT, "web"), "web"),
    ],
    hiddenimports=[
        "nacl.public",
        "nacl.encoding",
        "nacl.exceptions",
        "nacl.bindings",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "unittest",
        "pydoc",
        "doctest",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ncmp-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,          # 保留标准输出（Tauri 外壳通过管道读取端口/令牌）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(PROJECT_ROOT, "assets", "ncmp.ico"),
)
