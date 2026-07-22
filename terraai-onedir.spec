# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for TerraAI — produces a onedir build (dist/terraai/ folder
of terraai.exe + supporting files, no self-extraction on launch). This is
the payload the Go launcher (launcher/) wraps into a single distributable
.exe for Windows — see scripts/package_windows.py.
Build with:  pyinstaller terraai-onedir.spec

Shared Analysis() config lives in pyinstaller_common.py — edit there, not
here, so this and terraai.spec can't drift apart.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path('').resolve()))
from pyinstaller_common import cli_analysis_kwargs

block_cipher = None

a = Analysis(**cli_analysis_kwargs(), cipher=block_cipher)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='terraai',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='terraai',
)
