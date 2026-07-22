"""Shared PyInstaller Analysis() config for terraai.spec (onefile — macOS/
Linux/Windows fallback) and terraai-onedir.spec (onedir — Windows launcher
payload, see launcher/ and scripts/package_windows.py). Keeps hiddenimports/
datas/excludes in one place so the two build targets can't drift apart.
"""
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules


def analysis_kwargs() -> dict:
    root = str(Path('').resolve())
    sys.path.insert(0, root)

    litellm_datas = collect_data_files('litellm', includes=['**/*.json', '**/*.yaml', '**/*.yml'])
    hcl2_datas = collect_data_files('hcl2')
    tiktoken_datas = [('tiktoken_cache/*.tiktoken', 'tiktoken_cache')]
    web_datas = [('web/static/index.html', 'web/static')]

    internal_hidden = (
        collect_submodules('config')
        + collect_submodules('ai')
        + collect_submodules('setup')
        + collect_submodules('terraform')
        + collect_submodules('vcs')
        + collect_submodules('state')
        + collect_submodules('ui')
        + collect_submodules('providers')
        + collect_submodules('web')
        + ['session']  # single-file module, not a package
    )

    return dict(
        scripts=['main.py'],
        pathex=[root],
        binaries=[],
        datas=litellm_datas + hcl2_datas + tiktoken_datas + web_datas,
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
            # FastAPI / uvicorn (web dashboard)
            'fastapi',
            'fastapi.responses',
            'fastapi.staticfiles',
            'uvicorn',
            'uvicorn.main',
            'uvicorn.config',
            'uvicorn.loops',
            'uvicorn.loops.auto',
            'uvicorn.protocols',
            'uvicorn.protocols.http',
            'uvicorn.protocols.http.auto',
            'uvicorn.lifespan',
            'uvicorn.lifespan.off',
            'starlette',
            'starlette.routing',
            'starlette.responses',
            'anyio',
            'anyio._backends._asyncio',
            'h11',
            'h11._connection',
            'h11._events',
            'h11._state',
        ] + internal_hidden,
        hookspath=[],
        hooksconfig={},
        runtime_hooks=['hooks/rthook_tiktoken.py'],
        excludes=[
            'tkinter', 'matplotlib', 'numpy', 'pandas',
            'scipy', 'PIL', 'cv2', 'torch',
            # Force uvicorn to use pure-Python loop/http — avoids C-extension
            # initialisation issues inside a frozen onefile binary.
            'uvloop', 'httptools',
            # litellm only reaches these from its deprecated, unused PaLM provider
            # (a lazy, try/except-guarded import — this app never exposes palm/*
            # models). googleapiclient alone was 97MB / 586 files, ~half the
            # entire onefile bundle, all Google API discovery docs unrelated to
            # the gemini/* models this app actually calls.
            'google.generativeai', 'google.ai.generativelanguage', 'googleapiclient',
        ],
        win_no_prefer_redirects=False,
        win_private_assemblies=False,
        noarchive=False,
    )
