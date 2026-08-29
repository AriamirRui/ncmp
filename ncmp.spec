# -*- mode: python ; coding: utf-8 -*-
# ncmp PyInstaller 打包配置：python -m PyInstaller ncmp.spec --noconfirm --clean
# 构建前先运行 python assets/make_icon.py 生成图标
import os

PROJECT_ROOT = os.path.abspath(SPECPATH)

a = Analysis(
    ["gui.py"],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=[],
    hiddenimports=[
        "nacl.public",
        "nacl.encoding",
        "nacl.exceptions",
        "nacl.bindings",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
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
    name="ncmp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(PROJECT_ROOT, "assets", "ncmp.ico"),
)
