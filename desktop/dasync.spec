# -*- mode: python ; coding: utf-8 -*-
# Сборка: pyinstaller dasync.spec --noconfirm   (результат: dist/DaSync/DaSync.exe)
import sys

hidden = ["pystray._win32"] if sys.platform == "win32" else []

a = Analysis(
    ["dasync.pyw"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # onedir: быстрее запускается и реже ругаются антивирусы, чем onefile
    name="DaSync",
    console=False,
    icon="assets/dasync.ico",
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="DaSync")
