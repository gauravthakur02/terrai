#!/usr/bin/env python3
"""TerraAI — AI-powered Terraform assistant for cloud & on-prem infrastructure."""
from __future__ import annotations
import sys
import os
from pathlib import Path
from typing import Optional

import typer
from rich.table import Table
from rich.panel import Panel
from rich import box

sys.path.insert(0, str(Path(__file__).parent))

from config import TerraAIConfig, MODEL_PRESETS, SUPPORTED_PROVIDERS
from ui import console, banner, success, error, info, warning, model_badge

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
        ("groq/llama3-70b-8192",    "Groq",   "export GROQ_API_KEY=...",              "Free tier at console.groq.com"),
        ("groq/mixtral-8x7b-32768", "Groq",   "export GROQ_API_KEY=...",              "Free tier at console.groq.com"),
        ("gemini/gemini-1.5-flash", "Google", "export GEMINI_API_KEY=...",            "Free tier at aistudio.google.com"),
        ("gemini/gemini-1.5-pro",   "Google", "export GEMINI_API_KEY=...",            "Free tier at aistudio.google.com"),
        ("ollama/llama3",           "Ollama", "ollama serve && ollama pull llama3",   "❌ No key needed (local)"),
        ("ollama/codellama",        "Ollama", "ollama serve && ollama pull codellama","❌ No key needed (local)"),
        ("ollama/mistral",          "Ollama", "ollama serve && ollama pull mistral",  "❌ No key needed (local)"),
    ]
    for row in free:
        t.add_row(*row)
    console.print(t)
    console.print("\n[dim]Launch with:[/dim] [bold]./terraai --model ollama/codellama[/bold]")
    console.print("[dim]Or Groq:    [/dim] [bold]GROQ_API_KEY=xxx ./terraai --model groq/llama3-70b-8192[/bold]")


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
) -> None:
    """
    [bold cyan]🌍 TerraAI[/bold cyan] — Manage cloud & on-prem infrastructure with natural language.

    [dim]Examples:[/dim]

      [bold]# Start interactive session (uses saved config)[/bold]
      terraai

      [bold]# Specify model and provider[/bold]
      terraai --model gpt-4o --provider azure
      terraai --model groq/llama3-70b-8192 --provider azure
      terraai --model gemini/gemini-1.5-pro

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

    # Check API key before starting the session
    if not _check_api_key(config.model, config):
        raise typer.Exit(0)

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
        config.workspace_dir = str(Path(workspace).expanduser().resolve())
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
        "    [green]/model gemini/gemini-1.5-pro[/green]",
        title="[bold]🔑 API Key Setup[/bold]",
        border_style="cyan",
    ))


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
