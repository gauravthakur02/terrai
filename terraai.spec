# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for TerraAI — produces a single-file executable.
Build with:  pyinstaller terraai.spec
"""
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Bundle all litellm data files (JSON/YAML model pricing + config)
litellm_datas = collect_data_files('litellm', includes=['**/*.json', '**/*.yaml', '**/*.yml'])

# Bundle tiktoken BPE encoding files (pre-downloaded, avoids runtime internet fetch)
tiktoken_datas = [('tiktoken_cache/*.tiktoken', 'tiktoken_cache')]

# Collect all submodules of internal packages so PyInstaller doesn't miss any
internal_hidden = (
    collect_submodules('config')
    + collect_submodules('ai')
    + collect_submodules('session')
    + collect_submodules('setup')
    + collect_submodules('terraform')
    + collect_submodules('vcs')
    + collect_submodules('state')
    + collect_submodules('ui')
    + collect_submodules('providers')
)

a = Analysis(
    ['main.py'],
    pathex=[str(Path('').resolve())],
    binaries=[],
    datas=litellm_datas + tiktoken_datas,
    hiddenimports=[
        # LiteLLM providers
        'litellm',
        'litellm.utils',
        'litellm.main',
        'litellm.exceptions',
        # Pydantic v2
        'pydantic',
        'pydantic.v1',
        # YAML
        'yaml',
        # prompt_toolkit
        'prompt_toolkit',
        'prompt_toolkit.history',
        'prompt_toolkit.auto_suggest',
        'prompt_toolkit.styles',
        'prompt_toolkit.formatted_text',
        # Rich
        'rich',
        'rich.console',
        'rich.panel',
        'rich.table',
        'rich.syntax',
        'rich.live',
        'rich.spinner',
        # Keyring backends
        'keyring',
        'keyring.backends',
        'keyring.backends.macOS',
        'keyring.backends.Windows',
        'keyring.backends.SecretService',
        'keyring.backends.fail',
        # tiktoken encodings
        'tiktoken',
        'tiktoken.registry',
        'tiktoken_ext',
        'tiktoken_ext.openai_public',
        # HCL2
        'hcl2',
    ] + internal_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['hooks/rthook_tiktoken.py'],
    excludes=[
        'tkinter', 'matplotlib', 'numpy', 'pandas',
        'scipy', 'PIL', 'cv2', 'torch',
    ],
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
    [],
    name='terraai',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
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
