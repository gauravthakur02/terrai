"""Shared PyInstaller Analysis() config for both binaries.

cli_analysis_kwargs()  → terraai      (REPL only, no web stack)
web_analysis_kwargs()  → terraai-web  (web dashboard, no REPL setup wizard)
"""
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules


def _base() -> dict:
    """Shared foundation for both binaries."""
    root = str(Path('').resolve())
    sys.path.insert(0, root)

    litellm_datas = collect_data_files('litellm', includes=['**/*.json', '**/*.yaml', '**/*.yml'])
    hcl2_datas = collect_data_files('hcl2')
    tiktoken_datas = [('tiktoken_cache/*.tiktoken', 'tiktoken_cache')]

    core_hidden = (
        collect_submodules('config')
        + collect_submodules('ai')
        + collect_submodules('terraform')
        + collect_submodules('vcs')
        + collect_submodules('state')
        + collect_submodules('providers')
    )

    return dict(
        pathex=[root],
        binaries=[],
        datas=litellm_datas + hcl2_datas + tiktoken_datas,
        hiddenimports=[
            # LiteLLM providers
            'litellm', 'litellm.utils', 'litellm.main', 'litellm.exceptions',
            # Pydantic v2
            'pydantic', 'pydantic.v1',
            # YAML
            'yaml',
            # Rich
            'rich', 'rich.console', 'rich.panel', 'rich.table',
            'rich.syntax', 'rich.live', 'rich.spinner',
            # tiktoken encodings
            'tiktoken', 'tiktoken.registry',
            'tiktoken_ext', 'tiktoken_ext.openai_public',
            # HCL2
            'hcl2',
        ] + core_hidden,
        hookspath=[],
        hooksconfig={},
        runtime_hooks=['hooks/rthook_tiktoken.py'],
        excludes=[
            'tkinter', 'matplotlib', 'numpy', 'pandas',
            'scipy', 'PIL', 'cv2', 'torch',
            'google.generativeai', 'google.ai.generativelanguage', 'googleapiclient',
        ],
        win_no_prefer_redirects=False,
        win_private_assemblies=False,
        noarchive=False,
    )


def cli_analysis_kwargs() -> dict:
    """CLI binary (terraai) — REPL + TUI only, no web stack."""
    root = str(Path('').resolve())
    kwargs = _base()
    kwargs['scripts'] = ['main.py']
    kwargs['hiddenimports'] += [
        # prompt_toolkit (REPL autocomplete)
        'prompt_toolkit', 'prompt_toolkit.history',
        'prompt_toolkit.auto_suggest', 'prompt_toolkit.styles',
        'prompt_toolkit.formatted_text',
        # Keyring backends
        'keyring', 'keyring.backends', 'keyring.backends.macOS',
        'keyring.backends.Windows', 'keyring.backends.SecretService',
        'keyring.backends.fail',
        # Internal CLI modules
        'session',
    ] + collect_submodules('setup') + collect_submodules('ui')
    kwargs['excludes'] += ['fastapi', 'uvicorn', 'starlette', 'anyio', 'h11',
                           'uvloop', 'httptools']
    return kwargs


def web_analysis_kwargs() -> dict:
    """Web binary (terraai-web) — dashboard server only."""
    kwargs = _base()
    kwargs['scripts'] = ['web/main.py']
    kwargs['datas'] += [('web/static/index.html', 'web/static')]
    kwargs['hiddenimports'] += [
        # FastAPI / uvicorn stack
        'fastapi', 'fastapi.responses', 'fastapi.staticfiles',
        'uvicorn', 'uvicorn.main', 'uvicorn.config',
        'uvicorn.loops', 'uvicorn.loops.auto',
        'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto',
        'uvicorn.lifespan', 'uvicorn.lifespan.off',
        'starlette', 'starlette.routing', 'starlette.responses',
        'anyio', 'anyio._backends._asyncio',
        'h11', 'h11._connection', 'h11._events', 'h11._state',
        # Typer for web/main.py
        'typer',
    ] + collect_submodules('web')
    kwargs['excludes'] += ['uvloop', 'httptools']
    return kwargs
