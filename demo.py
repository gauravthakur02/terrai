#!/usr/bin/env python3
"""
TerraAI — End-to-end demo
Shows the exact flow for: "create an Azure resource group and storage account"
Uses a realistic AI response so no API key is needed to run this demo.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from rich.live import Live
from rich.spinner import Spinner
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.markdown import Markdown
from rich import box

from ui import console
from ui.panels import banner, hcl_panel, plan_summary, success, warning, info, section
from vcs.git_manager import GitManager
from vcs.changelog import InfrastructureChangelog
from vcs.drift_detector import DriftDetector
from terraform.executor import TerraformExecutor
from terraform.workspace import WorkspaceManager
from ai.client import AIResponse

WORKSPACE = Path.home() / "terraai-demo"

# ── Realistic AI response the model would return ─────────────────────────────
MOCK_AI_RESPONSE = AIResponse({
    "intent": "create",
    "providers": ["azure"],
    "summary": "Create Azure Resource Group 'rg-demo' and Storage Account in East US",
    "resources": [
        {"name": "rg_demo",      "type": "azurerm_resource_group",  "action": "create"},
        {"name": "st_demo",      "type": "azurerm_storage_account", "action": "create"},
    ],
    "hcl": '''\
terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

variable "subscription_id" {
  description = "Azure Subscription ID"
  type        = string
}

variable "location" {
  description = "Azure region"
  type        = string
  default     = "East US"
}

variable "tags" {
  description = "Common resource tags"
  type        = map(string)
  default = {
    managed_by  = "TerraAI"
    environment = "demo"
    project     = "terraai-demo"
  }
}

# ── Resource Group ────────────────────────────────────────────────────────────
resource "azurerm_resource_group" "rg_demo" {
  name     = "rg-demo"
  location = var.location
  tags     = var.tags
}

# ── Storage Account ───────────────────────────────────────────────────────────
resource "azurerm_storage_account" "st_demo" {
  name                     = "stterraaidemo"          # must be globally unique
  resource_group_name      = azurerm_resource_group.rg_demo.name
  location                 = azurerm_resource_group.rg_demo.location
  account_tier             = "Standard"
  account_replication_type = "LRS"

  blob_properties {
    versioning_enabled = true
  }

  tags = var.tags
}

# ── Outputs ───────────────────────────────────────────────────────────────────
output "resource_group_name" {
  value       = azurerm_resource_group.rg_demo.name
  description = "Resource Group name"
}

output "storage_account_name" {
  value       = azurerm_storage_account.st_demo.name
  description = "Storage Account name"
}

output "storage_primary_endpoint" {
  value       = azurerm_storage_account.st_demo.primary_blob_endpoint
  description = "Primary blob endpoint"
}
''',
    "variables": {
        "subscription_id": "<your-azure-subscription-id>",
        "location": "East US",
    },
    "outputs": {
        "resource_group_name": "Name of the created resource group",
        "storage_account_name": "Name of the storage account",
        "storage_primary_endpoint": "Primary blob storage endpoint URL",
    },
    "warnings": [
        "Storage account name 'stterraaidemo' must be globally unique across all of Azure — change it if already taken.",
        "Set ARM_SUBSCRIPTION_ID (or var.subscription_id in terraform.tfvars) before running terraform apply.",
    ],
    "next_steps": [
        "Run /init to download the azurerm provider",
        "Run /plan to preview what will be created",
        "Set ARM_SUBSCRIPTION_ID=<your-id> before /apply",
        "Consider adding /backend set azurerm to store state in Azure Blob Storage",
    ],
})


def pause(secs: float = 0.6) -> None:
    time.sleep(secs)


def demo_thinking(label: str, secs: float = 1.8) -> None:
    with Live(Spinner("dots", text=f"[magenta]{label}[/magenta]"),
              refresh_per_second=10, console=console, transient=True):
        time.sleep(secs)


def main() -> None:
    # ── 1. Banner ─────────────────────────────────────────────────────────────
    banner()
    console.print("[dim]Model:[/dim] [bold magenta]claude-sonnet-4-6[/bold magenta]  "
                  "[dim]Provider:[/dim] [bold cyan]azure[/bold cyan]")
    info("Terraform 1.15.5 detected")
    info(f"Workspace: {WORKSPACE}")
    console.print()

    # ── 2. Init workspace & git ───────────────────────────────────────────────
    wm  = WorkspaceManager(str(WORKSPACE))
    git = GitManager(str(WORKSPACE))
    cl  = InfrastructureChangelog(str(WORKSPACE))
    tf  = TerraformExecutor(str(WORKSPACE))

    if not git.is_git_repo():
        git.init()
        info("Initialized git repository in workspace")
    pause()

    # ── 3. Simulate user prompt ───────────────────────────────────────────────
    console.print(
        "[bold cyan]☁️ azure[/bold cyan][bold white][[/bold white]"
        "[cyan]terraai-demo[/cyan][bold white]] ❯ [/bold white]"
        "create an Azure resource group 'rg-demo' and a storage account in East US"
    )
    console.print()

    # ── 4. AI thinking ────────────────────────────────────────────────────────
    demo_thinking("🤖 Thinking...", secs=2.0)

    ai = MOCK_AI_RESPONSE

    # ── 5. Section header ─────────────────────────────────────────────────────
    console.print(Rule(
        "[bold cyan]☁️  CREATE — Create Azure Resource Group 'rg-demo' and Storage Account in East US[/bold cyan]",
        style="dim cyan"
    ))

    console.print(f"\n[bold white]{ai.summary}[/bold white]")
    console.print()

    # ── 6. Resource table ─────────────────────────────────────────────────────
    t = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan", border_style="dim")
    t.add_column("Resource Name")
    t.add_column("Resource Type")
    t.add_column("Provider")
    t.add_column("Action")
    for r in ai.resources:
        t.add_row(
            f"[bold]{r['name']}[/bold]",
            f"[dim]{r['type']}[/dim]",
            "☁️  azure",
            f"[bold green]{r['action']}[/bold green]",
        )
    console.print(t)

    # ── 7. Warnings ───────────────────────────────────────────────────────────
    console.print()
    for w in ai.warnings:
        warning(w)

    # ── 8. HCL panel ─────────────────────────────────────────────────────────
    console.print()
    hcl_panel(ai.hcl, title="Generated Terraform HCL — main.tf")

    # ── 9. Save prompt (auto-accept for demo) ─────────────────────────────────
    console.print()
    console.print("[dim]Suggested file:[/dim] [bold]main.tf[/bold]")
    console.print(
        "[bold cyan]💾 Save to [white]main.tf[/white]? "
        "([green]y[/green]=yes, [yellow]r[/yellow]=rename, "
        "[red]n[/red]=skip, [blue]p[/blue]=plan after save): [/bold cyan]"
        "[green]y[/green]  [dim]← auto-accepted for demo[/dim]"
    )
    console.print()

    saved = wm.write_hcl("main", ai.hcl)
    success(f"Saved → {saved}")

    # ── 10. Auto git commit ───────────────────────────────────────────────────
    demo_thinking("📝 Committing to git...", secs=0.8)
    msg = git.build_commit_message(ai.summary, ai.intent, ai.providers, ai.resources)
    sha = git.commit(msg, author="TerraAI")
    if sha:
        console.print(f"[dim]📝 Auto-committed [{sha[:8]}] — /history to view[/dim]")
        cl.record_change(
            git_sha=sha, intent=ai.intent, summary=ai.summary,
            providers=ai.providers, resources=ai.resources,
            warnings=ai.warnings, user_request="create an Azure resource group and storage account",
            hcl_file="main.tf",
        )
    pause(0.3)

    # ── 11. Next steps ────────────────────────────────────────────────────────
    console.print("\n[bold cyan]💡 Suggested next steps:[/bold cyan]")
    for step in ai.next_steps:
        console.print(f"  [dim]▸[/dim] {step}")
    console.print()

    # ── 12. /history ──────────────────────────────────────────────────────────
    console.print(
        "[bold cyan]☁️ azure[/bold cyan][bold white][[/bold white]"
        "[cyan]terraai-demo[/cyan][bold white]] ❯ [/bold white]/history"
    )
    commits = git.get_log(limit=5)
    ht = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold cyan")
    ht.add_column("SHA",     style="bold yellow", width=10)
    ht.add_column("Message")
    ht.add_column("Author",  width=10)
    ht.add_column("Date",    width=20)
    for c in commits:
        ht.add_row(c.short_sha, c.summary[:65], c.author, c.timestamp[:16])
    console.print(ht)
    pause(0.4)

    # ── 13. /chronicle ────────────────────────────────────────────────────────
    console.print(
        "\n[bold cyan]☁️ azure[/bold cyan][bold white][[/bold white]"
        "[cyan]terraai-demo[/cyan][bold white]] ❯ [/bold white]/chronicle"
    )
    console.print(Rule("[bold cyan]📖 Infrastructure Chronicle[/bold cyan]", style="dim cyan"))
    for e in cl.get_entries():
        icon = {"create":"✅","modify":"✏️","delete":"🗑️"}.get(e.get("intent",""),"▶️")
        ts   = e.get("timestamp","")[:16].replace("T"," ")
        console.print(f"\n[bold]{icon} [{e.get('sha','')}][/bold] [dim]{ts}[/dim]")
        console.print(f"  [white]{e.get('summary','')}[/white]")
        console.print(f"  [dim]💬 \"{e.get('user_request','')}\"[/dim]")
        for r in e.get("resources", [])[:4]:
            act_icon = {"create":"➕","modify":"✏️","delete":"➖"}.get(r.get("action",""),"▸")
            console.print(f"  [dim]{act_icon} {r.get('type','')}.{r.get('name','')}[/dim]")
    pause(0.4)

    # ── 14. /backend show ─────────────────────────────────────────────────────
    console.print(
        "\n[bold cyan]☁️ azure[/bold cyan][bold white][[/bold white]"
        "[cyan]terraai-demo[/cyan][bold white]] ❯ [/bold white]/backend"
    )
    console.print(Panel(
        "[dim]No backend configured yet — using Terraform default (local state).[/dim]\n\n"
        "To store state in Azure Blob Storage run:\n"
        "  [bold green]/backend set azurerm[/bold green]\n\n"
        "Other options: [cyan]s3  gcs  pg  consul  kubernetes  http[/cyan]",
        title="[bold]🗂️  State Backend[/bold]",
        border_style="dim",
    ))
    pause(0.4)

    # ── 15. terraform init ────────────────────────────────────────────────────
    console.print(
        "\n[bold cyan]☁️ azure[/bold cyan][bold white][[/bold white]"
        "[cyan]terraai-demo[/cyan][bold white]] ❯ [/bold white]/init"
    )
    console.print(Rule("[bold]🔧 Terraform Init[/bold]", style="dim cyan"))
    demo_thinking("Initialising providers...", secs=1.2)
    for line in tf.init():
        _tf_line(line)
    pause(0.4)

    # ── 16. terraform plan ────────────────────────────────────────────────────
    console.print(
        "\n[bold cyan]☁️ azure[/bold cyan][bold white][[/bold white]"
        "[cyan]terraai-demo[/cyan][bold white]] ❯ [/bold white]/plan"
    )
    console.print(Rule("[bold]📋 Terraform Plan[/bold]", style="dim cyan"))
    demo_thinking("Planning...", secs=1.0)
    plan_out = ""
    for line in tf.plan():
        plan_out += line
        _tf_line(line)

    stats = tf.parse_plan_stats(plan_out)
    if any(stats[k] for k in ("add","change","destroy")):
        plan_summary(plan_out, stats)

    # ── 17. Final state ───────────────────────────────────────────────────────
    console.print()
    console.print(Rule("[bold green]✅ Demo complete[/bold green]", style="dim green"))
    console.print()
    console.print(Panel(
        f"[bold]Workspace:[/bold] {WORKSPACE}\n"
        "[bold]Files written:[/bold]\n"
        "  📄 main.tf           ← Terraform HCL (resource group + storage account)\n"
        "  📖 INFRASTRUCTURE.md ← AI-authored changelog\n"
        "  🗂️  .git/             ← Version controlled\n"
        "  🗄️  .terraai/         ← Chronicle + state snapshots\n\n"
        "[bold]What's next to deploy for real:[/bold]\n"
        "  1. [green]export ARM_SUBSCRIPTION_ID=<your-id>[/green]\n"
        "  2. [green]export ARM_CLIENT_ID=<app-id>[/green]\n"
        "  3. [green]export ARM_CLIENT_SECRET=<secret>[/green]\n"
        "  4. [green]export ARM_TENANT_ID=<tenant-id>[/green]\n"
        f"  5. Run [bold]./terraai --workspace {WORKSPACE}[/bold]\n"
        "  6. Type [bold]/init[/bold] then [bold]/apply[/bold]",
        title="[bold cyan]🌍 TerraAI Demo Summary[/bold cyan]",
        border_style="cyan",
    ))
    console.print()

    files = list(WORKSPACE.glob("*.tf")) + [WORKSPACE / "INFRASTRUCTURE.md"]
    console.print("[dim]Files on disk:[/dim]")
    for f in files:
        if f.exists():
            lines = len(f.read_text().splitlines())
            console.print(f"  [cyan]📄 {f.name}[/cyan]  ({lines} lines)")
    console.print()


def _tf_line(line: str) -> None:
    line = line.rstrip()
    if not line:
        return
    if "Error" in line or "error" in line:
        console.print(f"[red]{line}[/red]")
    elif "Warning" in line:
        console.print(f"[yellow]{line}[/yellow]")
    elif line.lstrip().startswith("+ ") or "will be created" in line:
        console.print(f"[green]{line}[/green]")
    elif line.lstrip().startswith("- ") or "will be destroyed" in line:
        console.print(f"[red]{line}[/red]")
    elif line.lstrip().startswith("~ "):
        console.print(f"[yellow]{line}[/yellow]")
    elif "Plan:" in line or "Apply complete" in line:
        console.print(f"[bold yellow]{line}[/bold yellow]")
    elif "Initializing" in line or "successfully" in line.lower():
        console.print(f"[bold green]{line}[/bold green]")
    else:
        console.print(f"[dim]{line}[/dim]")


if __name__ == "__main__":
    main()
