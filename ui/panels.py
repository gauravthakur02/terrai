from __future__ import annotations
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.columns import Columns
from rich.rule import Rule
from rich.markdown import Markdown
from rich import box
from .console import console

PROVIDER_ICONS = {
    "azure": "☁️",
    "aws": "🟠",
    "gcp": "🔵",
    "kubernetes": "⎈",
    "helm": "⚓",
    "vmware": "🖥️",
    "unknown": "🌐",
}

ACTION_ICONS = {
    "create": "✅",
    "modify": "✏️",
    "delete": "🗑️",
    "read": "👁️",
    "plan": "📋",
    "apply": "🚀",
    "destroy": "💥",
    "init": "🔧",
}


def banner() -> None:
    console.print()
    console.print(Panel.fit(
        "[bold cyan]🌍 TerraAI[/bold cyan]  [dim]─[/dim]  [bold white]AI-Powered Terraform Assistant[/bold white]\n"
        "[dim]Manage cloud & on-prem infrastructure with natural language[/dim]",
        border_style="cyan",
        padding=(1, 4),
    ))
    console.print()


def section(title: str, icon: str = "▶") -> None:
    console.print(Rule(f"[bold cyan]{icon} {title}[/bold cyan]", style="dim cyan"))


def hcl_panel(code: str, title: str = "Generated Terraform HCL") -> None:
    syntax = Syntax(code, "hcl", theme="monokai", line_numbers=True, word_wrap=True)
    console.print(Panel(syntax, title=f"[bold hcl]📄 {title}[/bold hcl]", border_style="blue", padding=(0, 1)))


def plan_summary(plan_output: str, stats: dict) -> None:
    table = Table(box=box.ROUNDED, border_style="dim", show_header=True, header_style="bold")
    table.add_column("Action", style="bold", width=12)
    table.add_column("Count", justify="right", width=8)
    table.add_column("Resources")

    if stats.get("add"):
        table.add_row("[action.create]➕ Create[/action.create]", f"[action.create]{stats['add']}[/action.create]", stats.get("add_list", ""))
    if stats.get("change"):
        table.add_row("[action.modify]✏️  Modify[/action.modify]", f"[action.modify]{stats['change']}[/action.modify]", stats.get("change_list", ""))
    if stats.get("destroy"):
        table.add_row("[action.delete]🗑️  Destroy[/action.delete]", f"[action.delete]{stats['destroy']}[/action.delete]", stats.get("destroy_list", ""))

    console.print(Panel(table, title="[bold]📋 Plan Summary[/bold]", border_style="yellow", padding=(0, 1)))


def ai_thinking(message: str) -> None:
    console.print(f"\n[ai]🤖 AI:[/ai] [dim]{message}[/dim]")


def ai_response(message: str) -> None:
    console.print(Panel(
        Markdown(message),
        title="[ai]🤖 AI Analysis[/ai]",
        border_style="magenta",
        padding=(0, 1),
    ))


def success(message: str) -> None:
    console.print(f"[success]✅ {message}[/success]")


def warning(message: str) -> None:
    console.print(f"[warning]⚠️  {message}[/warning]")


def error(message: str) -> None:
    console.print(f"[error]❌ {message}[/error]")


def info(message: str) -> None:
    console.print(f"[info]ℹ️  {message}[/info]")


def model_badge(model: str, provider: str) -> None:
    console.print(
        f"[dim]Model:[/dim] [bold magenta]{model}[/bold magenta]  "
        f"[dim]Provider:[/dim] [bold cyan]{provider}[/bold cyan]"
    )


def resource_table(resources: list[dict]) -> None:
    table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold cyan")
    table.add_column("Resource", style="bold")
    table.add_column("Type")
    table.add_column("Provider")
    table.add_column("Status")

    for r in resources:
        provider = r.get("provider", "unknown")
        icon = PROVIDER_ICONS.get(provider, "🌐")
        status_color = {"tainted": "yellow", "ok": "green", "unknown": "dim"}.get(r.get("status", "ok"), "green")
        table.add_row(
            r.get("name", ""),
            r.get("type", ""),
            f"{icon} {provider}",
            f"[{status_color}]{r.get('status', 'ok')}[/{status_color}]",
        )

    console.print(table)


def confirm_action(action: str, resource_count: int) -> bool:
    icon = ACTION_ICONS.get(action, "▶")
    color = {"apply": "green", "destroy": "red", "plan": "yellow"}.get(action, "cyan")
    console.print(
        f"\n[bold {color}]{icon} Ready to {action.upper()} {resource_count} resource(s)[/bold {color}]"
    )


def provider_status_table(providers: list[str]) -> None:
    table = Table(box=box.ROUNDED, show_header=True, header_style="bold")
    table.add_column("Provider")
    table.add_column("Source")
    table.add_column("Version")

    for p in providers:
        icon = PROVIDER_ICONS.get(p, "🌐")
        table.add_row(f"{icon} {p}", f"hashicorp/{p}", "latest")

    console.print(table)
