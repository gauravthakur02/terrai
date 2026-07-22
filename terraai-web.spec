# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for TerraAI Web Dashboard — produces a single-file server binary.
Build with:  pyinstaller terraai-web.spec
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path('').resolve()))
from pyinstaller_common import web_analysis_kwargs

block_cipher = None

a = Analysis(**web_analysis_kwargs(), cipher=block_cipher)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='terraai-web',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
