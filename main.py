#!/usr/bin/env python3
"""TerraAI — AI-powered Terraform assistant for cloud & on-prem infrastructure."""
from __future__ import annotations
import sys
import os
from pathlib import Path
from typing import Optional

# Force UTF-8 output on Windows so Rich can render emoji/unicode to the console.
# Must run before any Rich/typer imports.
if sys.platform == 'win32':
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import typer
from rich.table import Table
from rich.panel import Panel
from rich import box

sys.path.insert(0, str(Path(__file__).parent))

from config import TerraAIConfig, MODEL_PRESETS, SUPPORTED_PROVIDERS
from ui import console, banner, success, error, info, warning, model_badge

# The directory this script lives in — never use it as a workspace
_TERRAAI_SRC_DIR = Path(__file__).parent.resolve()


def _resolve_workspace(configured: Optional[str]) -> Optional[str]:
    """
    Return a valid, absolute workspace path — never the terraai source directory.

    Priority:
      1. Explicitly passed via --workspace or saved in config  → use as-is (create if missing)
      2. Not set → interactive picker: enter path or create a new named directory
    """
    # 1. Explicitly configured
    if configured:
        p = Path(configured).expanduser().resolve()
        if p == _TERRAAI_SRC_DIR:
            warning("Workspace cannot be the TerraAI source directory.")
            warning("Please choose a different path.\n")
        else:
            p.mkdir(parents=True, exist_ok=True)
            return str(p)

    # 2. Interactive picker
    console.print()
    console.print(
        "[bold cyan]📂 Workspace Setup[/bold cyan]\n"
        "[dim]Where should TerraAI write your Terraform files?[/dim]\n"
    )

    recent = _recent_workspaces()
    if recent:
        console.print("[dim]Recent workspaces:[/dim]")
        for i, r in enumerate(recent, 1):
            console.print(f"  [cyan]{i}[/cyan]  {r}")
        console.print()

    console.print(
        "  [cyan]n[/cyan]  Create a new directory\n"
        "  [cyan]p[/cyan]  Enter a path manually\n"
    )

    if recent:
        console.print("[dim]Press 1-{} to reuse a recent workspace, or n/p:[/dim]".format(len(recent)))

    choice = console.input("[bold]Choice: [/bold]").strip().lower()

    # Reuse recent
    if recent and choice.isdigit() and 1 <= int(choice) <= len(recent):
        p = Path(recent[int(choice) - 1]).resolve()
        p.mkdir(parents=True, exist_ok=True)
        success(f"Workspace: {p}")
        _save_recent_workspace(str(p))
        return str(p)

    # Manual path
    if choice == "p":
        raw = console.input("[bold]Enter path: [/bold]").strip()
        if not raw:
            error("No path entered.")
            return None
        p = Path(raw).expanduser().resolve()
        if p == _TERRAAI_SRC_DIR:
            error("Cannot use the TerraAI source directory as workspace.")
            return None
        p.mkdir(parents=True, exist_ok=True)
        success(f"Workspace: {p}")
        _save_recent_workspace(str(p))
        return str(p)

    # Create new directory
    if choice == "n" or not choice:
        name = console.input(
            "[bold]Directory name [/bold][dim](will be created in ~/terraai-workspaces/): [/dim]"
        ).strip()
        if not name:
            error("No name entered.")
            return None
        p = (Path.home() / "terraai-workspaces" / name).resolve()
        p.mkdir(parents=True, exist_ok=True)
        success(f"Created workspace: {p}")
        _save_recent_workspace(str(p))
        return str(p)

    error(f"Unknown choice: {choice}")
    return None


def _recent_workspaces(limit: int = 5) -> list[str]:
    history_file = Path.home() / ".terraai" / "workspaces.txt"
    if not history_file.exists():
        return []
    lines = [l.strip() for l in history_file.read_text().splitlines() if l.strip()]
    # Return only paths that still exist, most-recent first, deduplicated
    seen: set[str] = set()
    result = []
    for line in reversed(lines):
        if line not in seen and Path(line).exists():
            seen.add(line)
            result.append(line)
        if len(result) >= limit:
            break
    return result


def _save_recent_workspace(path: str) -> None:
    history_file = Path.home() / ".terraai" / "workspaces.txt"
    history_file.parent.mkdir(parents=True, exist_ok=True)
    existing = history_file.read_text().splitlines() if history_file.exists() else []
    existing = [l for l in existing if l.strip() and l.strip() != path]
    existing.append(path)
    history_file.write_text("\n".join(existing[-20:]) + "\n", encoding='utf-8')  # keep last 20


# Maps model prefix → (env var name, friendly name, signup URL)
API_KEY_REGISTRY: dict[str, tuple[str, str, str]] = {
    "gpt":          ("OPENAI_API_KEY",       "OpenAI",       "https://platform.openai.com/api-keys"),
    "o1":           ("OPENAI_API_KEY",       "OpenAI",       "https://platform.openai.com/api-keys"),
    "claude":       ("ANTHROPIC_API_KEY",    "Anthropic",    "https://console.anthropic.com/settings/keys"),
    "gemini":       ("GEMINI_API_KEY",       "Google Gemini","https://aistudio.google.com/app/apikey"),
    "groq":         ("GROQ_API_KEY",         "Groq",         "https://console.groq.com/keys"),
    "azure":        ("AZURE_OPENAI_API_KEY", "Azure OpenAI", "https://portal.azure.com"),
    "mistral":      ("MISTRAL_API_KEY",      "Mistral",      "https://console.mistral.ai/api-keys"),
    "cohere":       ("COHERE_API_KEY",       "Cohere",       "https://dashboard.cohere.com/api-keys"),
    "together":     ("TOGETHERAI_API_KEY",   "Together AI",  "https://api.together.xyz/settings/api-keys"),
    "ollama":       (None,                   "Ollama",       "https://ollama.com"),  # no key needed
    "huggingface":  ("HUGGINGFACE_API_KEY",  "HuggingFace",  "https://huggingface.co/settings/tokens"),
}


def _detect_provider(model: str) -> tuple[str, str, str] | tuple[None, str, str]:
    """Return (env_var, friendly_name, signup_url) for a model string."""
    model_lower = model.lower()
    # strip provider prefix like "groq/llama3" → check "groq"
    prefix = model_lower.split("/")[0]
    if prefix in API_KEY_REGISTRY:
        return API_KEY_REGISTRY[prefix]
    # fallback: check if any registry key is a substring
    for key, info in API_KEY_REGISTRY.items():
        if key in model_lower:
            return info
    return ("OPENAI_API_KEY", "OpenAI (default)", "https://platform.openai.com/api-keys")


def _check_api_key(model: str, config: TerraAIConfig) -> bool:
    """
    Check if the required API key is present for the given model.
    If not, guide the user through setting it up.
    Returns True if the key is available, False if setup was aborted.
    """
    env_var, provider_name, signup_url = _detect_provider(model)

    # Ollama needs no key
    if env_var is None:
        api_base = config.api_base or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        info(f"Ollama runs locally — no API key needed.")
        info(f"Make sure Ollama is running: ollama serve")
        info(f"Pull the model if you haven't: ollama pull {model.split('/', 1)[-1]}")
        return True

    # Check: config file key → env var
    key_value = config.api_key or os.environ.get(env_var)
    if key_value:
        return True

    # Key is missing — guide the user
    console.print()
    console.print(Panel(
        f"[bold yellow]🔑 API key required for [white]{provider_name}[/white][/bold yellow]\n\n"
        f"Model: [bold]{model}[/bold]\n"
        f"Expected env var: [bold cyan]{env_var}[/bold cyan]\n\n"
        f"Get your key at: [dim]{signup_url}[/dim]",
        title="[bold]API Key Setup[/bold]",
        border_style="yellow",
    ))
    console.print()

    choice = console.input(
        "[bold]How would you like to set it up?\n"
        "  [cyan]1[/cyan]  Enter key now (stored in ~/.terraai/config.yaml)\n"
        "  [cyan]2[/cyan]  I'll set the env var myself  (export "
        f"{env_var}=your_key)\n"
        "  [cyan]3[/cyan]  Switch to a free model (Groq / Ollama / Gemini)\n"
        "  [cyan]q[/cyan]  Quit\n"
        "Choice: [/bold]"
    ).strip().lower()

    if choice == "1":
        key = console.input(f"[bold]Paste your {provider_name} API key: [/bold]").strip()
        if not key:
            error("No key entered.")
            return False
        save = console.input("[bold]Save to ~/.terraai/config.yaml? (y/n): [/bold]").strip().lower()
        if save == "y":
            config.api_key = key
            config.save()
            success(f"Key saved to ~/.terraai/config.yaml")
        else:
            # Set for this session only via env
            os.environ[env_var] = key
            config.api_key = key
            info("Key set for this session only (not saved).")
        return True

    elif choice == "2":
        console.print(f"\n[dim]Run this before launching TerraAI:[/dim]")
        console.print(f"  [bold green]export {env_var}=your_key_here[/bold green]")
        console.print(f"\nOr save it permanently to your shell profile (~/.zshrc / ~/.bashrc).")
        return False

    elif choice == "3":
        _print_free_models()
        return False

    else:
        return False


def _print_free_models() -> None:
    console.print()
    t = Table(title="🆓 Free Models — No API Key Cost", box=box.ROUNDED, header_style="bold green")
    t.add_column("Model ID", style="bold")
    t.add_column("Provider")
    t.add_column("How to use")
    t.add_column("Key required?")

    free = [
        ("gemini/gemini-2.0-flash",           "Google", "export GEMINI_API_KEY=...",                        "Free tier at aistudio.google.com"),
        ("gemini/gemini-2.5-flash",           "Google", "export GEMINI_API_KEY=...",                        "Free tier at aistudio.google.com"),
        ("groq/llama-3.3-70b-versatile",      "Groq",   "export GROQ_API_KEY=...",                          "Free tier at console.groq.com"),
        ("groq/llama-3.1-8b-instant",         "Groq",   "export GROQ_API_KEY=...",                          "Free tier at console.groq.com"),
        ("groq/deepseek-r1-distill-llama-70b","Groq",   "export GROQ_API_KEY=...",                          "Free tier at console.groq.com"),
        ("ollama/llama3.2",                   "Ollama", "ollama serve && ollama pull llama3.2",              "No key needed (local)"),
        ("ollama/qwen2.5-coder",              "Ollama", "ollama serve && ollama pull qwen2.5-coder",         "No key needed (local)"),
        ("ollama/mistral",                    "Ollama", "ollama serve && ollama pull mistral",               "No key needed (local)"),
    ]
    for row in free:
        t.add_row(*row)
    console.print(t)
    console.print("\n[dim]Launch with:[/dim] [bold]./terraai --model ollama/llama3.2[/bold]")
    console.print("[dim]Or Groq:    [/dim] [bold]GROQ_API_KEY=xxx ./terraai --model groq/llama-3.3-70b-versatile[/bold]")
    console.print("[dim]Or Gemini:  [/dim] [bold]GEMINI_API_KEY=AIza... ./terraai --model gemini/gemini-2.0-flash[/bold]")


app = typer.Typer(
    name="terraai",
    help="🌍 TerraAI — AI-powered Terraform assistant",
    add_completion=True,
    rich_markup_mode="rich",
    no_args_is_help=False,
    invoke_without_command=True,  # run callback when no subcommand given
)


@app.callback()
def root(
    ctx: typer.Context,
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="AI model to use"),
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="Default Terraform provider"),
    api_key: Optional[str] = typer.Option(None, "--api-key", "-k", help="API key for AI model", envvar="TERRAAI_API_KEY"),
    api_base: Optional[str] = typer.Option(None, "--api-base", help="Custom API base URL (for Ollama, Azure OpenAI, etc.)"),
    web: bool = typer.Option(False, "--web", help="Launch browser dashboard instead of REPL"),
    port: int = typer.Option(7820, "--port", help="Port for the web dashboard (default: 7820)"),
) -> None:
    """
    [bold cyan]🌍 TerraAI[/bold cyan] — Manage cloud & on-prem infrastructure with natural language.

    [dim]Examples:[/dim]

      [bold]# Start interactive session (uses saved config)[/bold]
      terraai

      [bold]# Specify model and provider[/bold]
      terraai --model gpt-4o --provider azure
      terraai --model groq/llama3-70b-8192 --provider azure
      terraai --model gemini/gemini-2.0-flash

      [bold]# Local Ollama (free, no API key)[/bold]
      terraai --model ollama/codellama --api-base http://localhost:11434

      [bold]# Pass API key inline (session only, not saved)[/bold]
      terraai --model gpt-4o --api-key sk-...

      [bold]# Save defaults for future sessions[/bold]
      terraai configure --model gpt-4o --api-key sk-...
    """
    # Only run session when no subcommand was invoked
    if ctx.invoked_subcommand is not None:
        return

    from session import TerraAISession

    config = TerraAIConfig.load()

    if workspace:
        config.workspace_dir = str(Path(workspace).expanduser().resolve())
    if model:
        config.model = model
    if provider:
        config.default_provider = provider
    if api_key:
        config.api_key = api_key
    if api_base:
        config.api_base = api_base

    # First-time setup wizard
    if not config.setup_complete:
        from setup import SetupWizard
        wizard = SetupWizard(console, config, _TERRAAI_SRC_DIR)
        config = wizard.run()
        if not config.workspace_dir:
            raise typer.Exit(0)
    else:
        # Resolve workspace — must not default to the terraai source directory
        config.workspace_dir = _resolve_workspace(config.workspace_dir)
        if not config.workspace_dir:
            raise typer.Exit(0)

        # Check API key before starting the session
        if not _check_api_key(config.model, config):
            raise typer.Exit(0)

    # Apply saved Azure credentials to the process environment
    if config.default_provider == "azure":
        config.apply_azure_env()

    if web:
        from web.server import launch as _web_launch
        console.print(f"[dim]Starting web UI on http://localhost:{port} ...[/dim]")
        _web_launch(config, port=port)
        return

    session = TerraAISession(config)
    session.run()


@app.command("configure")
def configure(
    model: Optional[str] = typer.Option(None, "--model", "-m", help="AI model"),
    api_key: Optional[str] = typer.Option(None, "--api-key", "-k", help="API key"),
    api_base: Optional[str] = typer.Option(None, "--api-base", help="API base URL"),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="Default workspace"),
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="Default cloud provider"),
) -> None:
    """Save TerraAI defaults to ~/.terraai/config.yaml"""
    config = TerraAIConfig.load()
    changed = False

    if model:
        config.model = model
        changed = True
    if api_key:
        config.api_key = api_key
        changed = True
    if api_base:
        config.api_base = api_base
        changed = True
    if workspace:
        p = Path(workspace).expanduser().resolve()
        if p == _TERRAAI_SRC_DIR:
            error("Cannot set the TerraAI source directory as workspace. Choose a different path.")
            raise typer.Exit(1)
        p.mkdir(parents=True, exist_ok=True)
        config.workspace_dir = str(p)
        _save_recent_workspace(str(p))
        changed = True
    if provider:
        if provider not in SUPPORTED_PROVIDERS:
            error(f"Unknown provider: {provider}. Valid: {', '.join(SUPPORTED_PROVIDERS.keys())}")
            raise typer.Exit(1)
        config.default_provider = provider
        changed = True

    if changed:
        config.save()
        success(f"Configuration saved to ~/.terraai/config.yaml")
        model_badge(config.model, config.default_provider)
        _env_var, provider_name, _ = _detect_provider(config.model)
        if _env_var and not config.api_key and not os.environ.get(_env_var):
            warning(f"No API key found for {provider_name}. Run: terraai configure --api-key YOUR_KEY")
            warning(f"Or set: export {_env_var}=your_key")
    else:
        _show_config(config)


@app.command("models")
def list_models() -> None:
    """List all supported AI models and how to set up their API keys."""
    free_table = Table(title="🆓 Free Models", box=box.ROUNDED, header_style="bold green")
    paid_table = Table(title="💳 Paid Models", box=box.ROUNDED, header_style="bold yellow")

    for t in (free_table, paid_table):
        t.add_column("Model ID", style="bold")
        t.add_column("Provider")
        t.add_column("Env Var to set")
        t.add_column("Get key at")

    model_key_info = {
        "openai":       ("OPENAI_API_KEY",       "platform.openai.com/api-keys"),
        "anthropic":    ("ANTHROPIC_API_KEY",     "console.anthropic.com"),
        "google":       ("GEMINI_API_KEY",        "aistudio.google.com/app/apikey"),
        "groq":         ("GROQ_API_KEY",          "console.groq.com/keys"),
        "azure_openai": ("AZURE_OPENAI_API_KEY",  "portal.azure.com"),
        "ollama":       ("(none needed)",          "ollama.com — runs locally"),
    }

    for model_id, info_dict in MODEL_PRESETS.items():
        prov = info_dict.get("provider", "openai")
        env_var, url = model_key_info.get(prov, ("OPENAI_API_KEY", ""))
        row = (model_id, prov, env_var, url)
        if info_dict.get("free"):
            free_table.add_row(*row)
        else:
            paid_table.add_row(*row)

    console.print(free_table)
    console.print(paid_table)
    console.print()
    console.print(Panel(
        "[bold]How to set API keys:[/bold]\n\n"
        "  [cyan]Option 1[/cyan] — Environment variable (session only):\n"
        "    [green]export OPENAI_API_KEY=sk-...[/green]\n"
        "    [green]export GROQ_API_KEY=gsk_...[/green]\n"
        "    [green]export GEMINI_API_KEY=AIza...[/green]\n\n"
        "  [cyan]Option 2[/cyan] — Save permanently to config:\n"
        "    [green]terraai configure --model gpt-4o --api-key sk-...[/green]\n\n"
        "  [cyan]Option 3[/cyan] — Pass inline at launch (not saved):\n"
        "    [green]terraai --model gpt-4o --api-key sk-...[/green]\n\n"
        "  [cyan]Option 4[/cyan] — In session, switch model and you'll be prompted:\n"
        "    [green]/model gemini/gemini-2.0-flash[/green]",
        title="[bold]🔑 API Key Setup[/bold]",
        border_style="cyan",
    ))


@app.command("setup")
def run_setup() -> None:
    """Re-run the first-time setup wizard (workspace, git, AI model, credentials, backend)."""
    from setup import SetupWizard
    config = TerraAIConfig.load()
    config.setup_complete = False  # force wizard
    wizard = SetupWizard(console, config, _TERRAAI_SRC_DIR)
    wizard.run()


@app.command("providers")
def list_providers() -> None:
    """List supported Terraform providers."""
    t = Table(title="☁️  Supported Providers", box=box.ROUNDED, header_style="bold cyan")
    t.add_column("Provider", style="bold")
    t.add_column("Registry Source")
    t.add_column("Example Resources")

    examples = {
        "azure":      "azurerm_resource_group, azurerm_virtual_network, azurerm_storage_account",
        "aws":        "aws_vpc, aws_s3_bucket, aws_instance, aws_rds_cluster",
        "gcp":        "google_compute_instance, google_storage_bucket, google_container_cluster",
        "kubernetes": "kubernetes_deployment, kubernetes_service, kubernetes_namespace",
        "helm":       "helm_release",
        "vmware":     "vsphere_virtual_machine, vsphere_folder",
    }

    for provider, source in SUPPORTED_PROVIDERS.items():
        t.add_row(provider, source, examples.get(provider, ""))

    console.print(t)


@app.command("smoke")
def smoke_test() -> None:
    """Self-test: verify binary bundle integrity (imports, encoding, data files). Exits 0 on pass."""
    import tempfile
    import json as _json
    import pathlib as _pathlib

    results: list[tuple[str, bool, str]] = []

    def check(label: str, fn) -> None:
        try:
            fn()
            results.append((label, True, ""))
        except Exception as exc:
            results.append((label, False, str(exc)))

    # imports — catches missing PyInstaller-bundled modules
    for mod in [
        "config", "ai", "setup", "terraform", "vcs", "state",
        "ui", "providers", "session",
        "litellm", "tiktoken", "yaml", "hcl2",
        "pydantic", "prompt_toolkit", "rich", "keyring",
    ]:
        check(f"import {mod}", lambda m=mod: __import__(m))

    # tiktoken BPE files — bundled in tiktoken_cache/
    def _tiktoken() -> None:
        import tiktoken
        for name in ("cl100k_base", "o200k_base"):
            enc = tiktoken.get_encoding(name)
            assert enc.encode("hello world"), f"{name} returned empty tokens"
    check("tiktoken BPE encode (cl100k_base, o200k_base)", _tiktoken)

    # litellm JSON data — bundled via collect_data_files
    def _litellm() -> None:
        import litellm
        assert litellm.model_list is not None
    check("litellm model list loaded", _litellm)

    # UTF-8 write/read with emoji — catches Windows cp1252 charmap errors
    def _encoding() -> None:
        tmp = _pathlib.Path(tempfile.mktemp(suffix=".json"))
        data = {"emoji": "✅ 🌍 ⚙️", "accents": "héllo wörld ñoño"}
        tmp.write_text(_json.dumps(data), encoding="utf-8")
        assert _json.loads(tmp.read_text(encoding="utf-8")) == data
        tmp.unlink()
    check("UTF-8 write/read (emoji + accents)", _encoding)

    # config model_dump — catches misplaced encoding= kwarg inside model_dump()
    def _config_dump() -> None:
        from config import TerraAIConfig as _Cfg
        d = _Cfg().model_dump(exclude_none=True)
        assert isinstance(d, dict)
    check("TerraAIConfig.model_dump(exclude_none=True)", _config_dump)

    # hcl2 parse — exercises the bundled lark grammar
    def _hcl2() -> None:
        import hcl2, io
        hcl2.load(io.StringIO('resource "null_resource" "x" { triggers = {} }'))
    check("hcl2 parse", _hcl2)

    # print results
    console.print()
    failed = 0
    for label, ok, err in results:
        if ok:
            console.print(f"  [green]✓[/green]  {label}")
        else:
            console.print(f"  [red]✗[/red]  {label}")
            console.print(f"      [dim red]{err}[/dim red]")
            failed += 1

    console.print()
    total = len(results)
    if failed == 0:
        console.print(f"[bold green]All {total} checks passed.[/bold green]")
        raise typer.Exit(0)
    else:
        console.print(f"[bold red]{failed}/{total} checks failed.[/bold red]")
        raise typer.Exit(1)


def _show_config(config: TerraAIConfig) -> None:
    t = Table(box=box.ROUNDED, show_header=False)
    t.add_column("Setting", style="bold cyan", width=20)
    t.add_column("Value")
    for k, v in config.model_dump().items():
        if k == "api_key":
            display = "[bold green]set (hidden)[/bold green]" if v else "[dim]not set[/dim]"
        elif v is None:
            display = "[dim]not set[/dim]"
        else:
            display = str(v)
        t.add_row(k, display)

    # also show which env vars are active
    env_hints = []
    for prefix, (env_var, name, _) in API_KEY_REGISTRY.items():
        if env_var and os.environ.get(env_var):
            env_hints.append(f"[green]✓[/green] {env_var}")
    if env_hints:
        t.add_row("[dim]env keys active[/dim]", "  ".join(env_hints))

    console.print(Panel(t, title="[bold]⚙️  Configuration[/bold]", border_style="dim"))


if __name__ == "__main__":
    app()
