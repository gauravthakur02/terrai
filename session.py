from __future__ import annotations
import re
import sys
from pathlib import Path
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import HTML
from rich.live import Live
from rich.text import Text
from rich.spinner import Spinner
from rich.panel import Panel

from config import TerraAIConfig, model_supports_modules, RECOMMENDED_MODULE_MODEL
from ai import TerraAIClient, AIResponse
from terraform import TerraformExecutor, WorkspaceManager
from vcs import GitManager, InfrastructureChangelog, DriftDetector, InfrastructureDiagram
from state import StateManager, BackendWizard, BACKEND_DISPLAY
from ui import (
    console, banner, section, hcl_panel, plan_summary, ai_response,
    success, warning, error, info, model_badge, resource_table,
    PROVIDER_ICONS,
)

PROMPT_STYLE = Style.from_dict({
    "prompt": "ansicyan bold",
    "provider": "ansiblue",
})

HELP_TEXT = """
[bold cyan]TerraAI Commands[/bold cyan]

[bold]Infrastructure[/bold]
  [bold]/init[/bold]                  Run terraform init
  [bold]/plan[/bold]                  Run terraform plan
  [bold]/apply[/bold]                 Apply planned changes
  [bold]/destroy[/bold]               Destroy all resources (with confirmation)
  [bold]/state[/bold]                 Show current Terraform state
  [bold]/resources[/bold]             List managed resources
  [bold]/outputs[/bold]               Show Terraform outputs
  [bold]/files[/bold]                 List .tf files in workspace
  [bold]/diagram[/bold]               Generate interactive architecture diagram (HTML)
  [bold]/structure[/bold]             Show current generation layout (flat/module)
  [bold]/structure flat[/bold]        Generate resources directly in root .tf files (default)
  [bold]/structure module[/bold]      Generate reusable modules/<name>/{main,variables,outputs}.tf

[bold]Version Control (Chronicle)[/bold]
  [bold]/history[/bold]               Show git commit log for this workspace
  [bold]/chronicle[/bold]             Show AI-authored infrastructure changelog
  [bold]/diff [sha1] [sha2][/bold]    Show HCL diff between two commits
  [bold]/rollback <sha>[/bold]        Restore .tf files from a previous commit
  [bold]/tag <name> [msg][/bold]      Tag current state (e.g. v1.0-prod)
  [bold]/tags[/bold]                  List all tags
  [bold]/branch <name>[/bold]         Create and switch to a new git branch
  [bold]/branches[/bold]              List all git branches
  [bold]/drift[/bold]                 Detect out-of-band infrastructure drift

[bold]State Backend[/bold]
  [bold]/backend[/bold]               Show current state backend config
  [bold]/backend set <type>[/bold]    Configure backend: local azurerm s3 gcs pg consul kubernetes http
  [bold]/backend env <name>[/bold]    Switch active environment (dev/staging/prod)
  [bold]/backend list[/bold]          Show all environment→backend mappings
  [bold]/backend migrate[/bold]       Migrate state to newly configured backend

[bold]Config[/bold]
  [bold]/config[/bold]                Show current configuration
  [bold]/model <name>[/bold]          Switch AI model (e.g. /model gpt-4o)
  [bold]/apikey <key>[/bold]          Update stored API key (use after revoking/rotating a key)
  [bold]/workspace[/bold]             Switch workspace (interactive picker: recent, new, or path)
  [bold]/workspace <path>[/bold]      Switch straight to a workspace directory (created if missing)
  [bold]/workspace new <name>[/bold]  Create a new workspace under ~/terraai-workspaces/
  [bold]/workspaces[/bold]            List recent workspaces
  [bold]/providers[/bold]             List supported Terraform providers
  [bold]/models[/bold]                List supported AI models
  [bold]/clear[/bold]                 Clear conversation history
  [bold]/web[/bold]                   Open browser dashboard (default port 7820)
  [bold]/web <port>[/bold]            Open dashboard on a custom port
  [bold]/help[/bold]                  Show this help
  [bold]/exit[/bold]                  Exit TerraAI

[dim]Or just type naturally:[/dim]
  "create an Azure VNet with two subnets in East US"
  "add a storage account with blob versioning and encryption"
  "modify the VM size to Standard_D4s_v3 for the prod VM"
  "delete the staging resource group"
"""

SUPPORTED_MODELS_TABLE = {
    "Free Models (API key, free tier)": [
        ("gemini/gemini-2.0-flash",           "Google",  "Recommended — large context, fast"),
        ("gemini/gemini-2.5-flash",           "Google",  "Latest flash — best free Gemini"),
        ("groq/llama-3.3-70b-versatile",      "Groq",    "Fast + very capable"),
        ("groq/llama-3.1-8b-instant",         "Groq",    "Ultra fast, lightweight"),
        ("groq/deepseek-r1-distill-llama-70b","Groq",    "Strong reasoning, free tier"),
    ],
    "Paid Models": [
        ("gpt-4o",                    "OpenAI",      "Best overall quality"),
        ("gpt-4o-mini",               "OpenAI",      "Fast & affordable"),
        ("gpt-4.1",                   "OpenAI",      "Latest GPT-4 series"),
        ("gpt-4.1-mini",              "OpenAI",      "Latest, fast & cheap"),
        ("claude-sonnet-5",           "Anthropic",   "Strong HCL reasoning"),
        ("claude-opus-4-8",           "Anthropic",   "Most capable Anthropic"),
        ("claude-haiku-4-5-20251001", "Anthropic",   "Fast & cheap Anthropic"),
        ("azure/gpt-4o",              "Azure OpenAI","Enterprise Azure-hosted"),
    ],
    "Local Models (Ollama — no API key)": [
        ("ollama/llama3.2",     "Ollama", "Meta Llama 3.2 · 3B · very fast"),
        ("ollama/llama3.1",     "Ollama", "Meta Llama 3.1 · 8B · balanced"),
        ("ollama/qwen2.5-coder","Ollama", "Qwen 2.5 Coder · 7B · code-focused"),
        ("ollama/qwen3.5",      "Ollama", "Qwen 3.5 · strong reasoning"),
        ("ollama/mistral",      "Ollama", "Mistral 7B · general purpose"),
        ("ollama/codellama",    "Ollama", "Code Llama · code generation"),
    ],
    "Custom": [
        ("<litellm-model-id>",  "Any",    "Any provider litellm supports — see /custom"),
    ],
}


class TerraAISession:
    def __init__(self, config: TerraAIConfig):
        self.config = config
        self.client = TerraAIClient(config)
        self.workspace = WorkspaceManager(config.workspace_dir)
        self.executor = TerraformExecutor(config.workspace_dir, config.terraform_bin)
        self.git = GitManager(config.workspace_dir)
        self.changelog = InfrastructureChangelog(config.workspace_dir)
        self.drift = DriftDetector(config.workspace_dir)
        self.state_mgr = StateManager(config.workspace_dir)
        self._active_env = "default"
        self._ensure_git_init()
        self._prompt_pending_backend()
        history_path = Path.home() / ".terraai" / "history"
        history_path.parent.mkdir(parents=True, exist_ok=True)
        self._prompt_session = PromptSession(
            history=FileHistory(str(history_path)),
            auto_suggest=AutoSuggestFromHistory(),
            style=PROMPT_STYLE,
        )

    def _ensure_git_init(self) -> None:
        if not self.git.is_git_repo():
            self.git.init()
            info(f"Initialized git repository in workspace: {self.config.workspace_dir}")

    def _prompt_pending_backend(self) -> None:
        """If setup wizard recorded a pending backend choice, offer to configure it now."""
        pending = Path(self.config.workspace_dir) / ".terraai" / "pending_backend"
        if not pending.exists():
            return
        backend_type = pending.read_text(encoding='utf-8').strip()
        pending.unlink(missing_ok=True)
        if not backend_type:
            return
        console.print()
        icon, label, _ = BACKEND_DISPLAY.get(backend_type, ("🗂️", backend_type, ""))
        want = console.input(
            f"[bold cyan]🗂️  Configure {icon} {label} state backend now?[/bold cyan] (y/n): "
        ).strip().lower()
        if want == "y":
            wizard = BackendWizard(console)
            cfg = wizard.run(backend_type, self._active_env)
            if cfg:
                self.state_mgr.set_backend(cfg, self._active_env)
                path = self.state_mgr.write_backend_tf(self._active_env)
                success(f"Backend configured: {cfg.type}")
                if path:
                    hcl_panel(path.read_text(encoding='utf-8'), title=f"backend.tf ({cfg.type})")
                self.git.commit(
                    f"chore(backend): configure {cfg.type} backend for {self._active_env}",
                    author="TerraAI",
                )
        console.print()

    def _switch_workspace(self, path: str) -> None:
        """Switch the active session to `path`, creating it if needed, and
        re-point every workspace-scoped manager (git, changelog, drift,
        state, executor) — not just self.workspace — at the new directory."""
        from main import _TERRAAI_SRC_DIR, _save_recent_workspace

        p = Path(path).expanduser().resolve()
        if p == _TERRAAI_SRC_DIR:
            error("Cannot use the TerraAI source directory as workspace.")
            return

        p.mkdir(parents=True, exist_ok=True)
        self.config.workspace_dir = str(p)
        self.config.save()

        self.workspace = WorkspaceManager(self.config.workspace_dir)
        self.executor = TerraformExecutor(self.config.workspace_dir, self.config.terraform_bin)
        self.git = GitManager(self.config.workspace_dir)
        self.changelog = InfrastructureChangelog(self.config.workspace_dir)
        self.drift = DriftDetector(self.config.workspace_dir)
        self.state_mgr = StateManager(self.config.workspace_dir)
        self._active_env = "default"

        self._ensure_git_init()
        self._prompt_pending_backend()
        _save_recent_workspace(str(p))
        success(f"Workspace: {p}")

    def _workspace_picker(self) -> None:
        from main import _recent_workspaces

        console.print()
        console.print(f"[dim]Current workspace:[/dim] {self.config.workspace_dir}\n")

        recent = [w for w in _recent_workspaces(limit=8) if w != self.config.workspace_dir]
        if recent:
            console.print("[dim]Recent workspaces:[/dim]")
            for i, r in enumerate(recent, 1):
                console.print(f"  [cyan]{i}[/cyan]  {r}")
            console.print()

        console.print(
            "  [cyan]n[/cyan]  Create a new workspace\n"
            "  [cyan]p[/cyan]  Enter a path manually\n"
            "  [cyan]c[/cyan]  Cancel\n"
        )
        choice = console.input("[bold]Choice: [/bold]").strip().lower()

        if choice in ("c", ""):
            info("Cancelled")
            return

        if recent and choice.isdigit() and 1 <= int(choice) <= len(recent):
            self._switch_workspace(recent[int(choice) - 1])
            return

        if choice == "p":
            raw = console.input("[bold]Enter path: [/bold]").strip()
            if not raw:
                error("No path entered.")
                return
            self._switch_workspace(raw)
            return

        if choice == "n":
            name = console.input(
                "[bold]Directory name [/bold][dim](created in ~/terraai-workspaces/): [/dim]"
            ).strip()
            if not name:
                error("No name entered.")
                return
            self._switch_workspace(str(Path.home() / "terraai-workspaces" / name))
            return

        error(f"Unknown choice: {choice}")

    def _list_workspaces(self) -> None:
        from main import _recent_workspaces
        from rich.table import Table
        from rich import box

        recent = _recent_workspaces(limit=10)
        if not recent:
            info("No recent workspaces recorded yet.")
            return

        t = Table(box=box.SIMPLE, header_style="bold cyan")
        t.add_column("")
        t.add_column("Path")
        for r in recent:
            marker = "➤" if r == self.config.workspace_dir else ""
            t.add_row(marker, r)
        console.print(t)
        console.print("[dim]Use /workspace <path>, /workspace new <name>, or /workspace to pick[/dim]")

    def _prompt_text(self) -> HTML:
        provider_icon = PROVIDER_ICONS.get(self.config.default_provider, "🌐")
        workspace_name = Path(self.config.workspace_dir).name
        branch = self.git.get_current_branch() if self.git.is_git_repo() else ""
        branch_str = f" ⎇{branch}" if branch and branch != "main" else ""
        env_str = f" [{self._active_env}]" if self._active_env != "default" else ""
        return HTML(
            f'<provider>{provider_icon} {self.config.default_provider}</provider>'
            f'<prompt>[{workspace_name}{branch_str}{env_str}] ❯ </prompt>'
        )

    def run(self) -> None:
        banner()
        model_badge(self.config.model, self.config.default_provider)
        tf_version = self.executor.version()
        if tf_version != "unknown":
            info(f"Terraform {tf_version} detected")
        else:
            warning("Terraform not found — HCL generation will work but execution commands will fail")
        console.print(f"\n[dim]Type [bold]/help[/bold] for commands or describe your infrastructure needs[/dim]\n")

        while True:
            try:
                user_input = self._prompt_session.prompt(self._prompt_text).strip()
            except (KeyboardInterrupt, EOFError):
                console.print("\n[dim]Goodbye! 👋[/dim]")
                sys.exit(0)

            if not user_input:
                continue

            # Allow bare words for common commands (e.g. "apply" == "/apply")
            _BARE = {"apply", "plan", "init", "destroy", "help", "quit", "exit",
                     "history", "state", "files", "config", "diagram", "drift"}
            if user_input.startswith("/"):
                self._handle_command(user_input)
            elif user_input.split()[0].lower() in _BARE:
                self._handle_command("/" + user_input)
            else:
                self._handle_ai_request(user_input)

    def _maybe_warn_weak_model_for_modules(self) -> None:
        """If module structure is active and the current model isn't known to
        reliably hold multi-file output together, say so and point at a
        stronger option. Advisory only — never blocks generation."""
        if self.config.structure_mode != "module" or model_supports_modules(self.config.model):
            return
        warning(
            f"[bold]{self.config.model}[/bold] isn't known to reliably keep module output "
            f"consistent (main.tf/variables.tf/outputs.tf per module, kept in sync with root "
            f"wiring across turns) — local/small models are the ones most likely to drift."
        )
        console.print(
            f"[dim]   Consider: [/dim][bold]/model {RECOMMENDED_MODULE_MODEL}[/bold][dim] (free) "
            f"— or /models for other options[/dim]"
        )

    def _handle_command(self, cmd: str) -> None:
        parts = cmd.split(maxsplit=1)
        command = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if command == "/help":
            console.print(Panel(HELP_TEXT, title="[bold cyan]📖 Help[/bold cyan]", border_style="cyan"))

        elif command == "/config":
            from rich.table import Table
            from rich import box
            t = Table(box=box.ROUNDED, show_header=False)
            t.add_column("Key", style="bold cyan")
            t.add_column("Value")
            for k, v in self.config.model_dump().items():
                t.add_row(k, str(v) if k != "api_key" else ("***" if v else "[dim]not set[/dim]"))
            console.print(Panel(t, title="[bold]⚙️  Configuration[/bold]", border_style="dim"))

        elif command == "/model":
            if not arg or arg.lower() in ("list", "ls"):
                info(f"Current model: {self.config.model}")
                console.print("[dim]Run /models to see all available models[/dim]")
                return
            from main import _check_api_key
            self.config.model = arg
            if not _check_api_key(arg, self.config):
                info(f"Model not switched — key setup incomplete. Still using: {self.config.model.split(arg)[0] or arg}")
                return
            self.config.save()
            self.client = TerraAIClient(self.config)
            success(f"Switched to model: {arg}")
            self._maybe_warn_weak_model_for_modules()

        elif command == "/structure":
            sub = arg.strip().lower()
            if not sub:
                icon = "📦" if self.config.structure_mode == "module" else "📄"
                info(f"{icon} Structure mode: {self.config.structure_mode}")
                console.print("[dim]Switch with /structure flat or /structure module[/dim]")
                self._maybe_warn_weak_model_for_modules()
                return
            if sub not in ("flat", "module"):
                error("Usage: /structure [flat|module]")
                return
            self.config.structure_mode = sub
            self.config.save()
            success(f"Structure mode: {sub}")
            if sub == "module":
                console.print(
                    "[dim]New requests generate modules/<name>/{main,variables,outputs}.tf "
                    "plus root wiring instead of flat resource files.[/dim]"
                )
                self._maybe_warn_weak_model_for_modules()

        elif command == "/workspace":
            if not arg:
                self._workspace_picker()
                return
            sub = arg.split(maxsplit=1)
            if sub[0].lower() in ("new", "create"):
                if len(sub) < 2 or not sub[1].strip():
                    error("Usage: /workspace new <name>")
                    return
                new_path = Path.home() / "terraai-workspaces" / sub[1].strip()
                self._switch_workspace(str(new_path))
                return
            self._switch_workspace(arg)

        elif command == "/workspaces":
            self._list_workspaces()

        elif command == "/files":
            files = self.workspace.list_files()
            if not files:
                info("No .tf files in workspace")
                return
            from rich.table import Table
            from rich import box
            t = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
            t.add_column("File")
            t.add_column("Lines", justify="right")
            t.add_column("Size", justify="right")
            for f in files:
                t.add_row(f"📄 {f['name']}", str(f["lines"]), f"{f['size']} B")
            console.print(t)

        elif command == "/state":
            result = self.executor.show_state()
            if result.success:
                from rich.syntax import Syntax
                console.print(Syntax(result.stdout[:3000], "hcl", theme="monokai"))
            else:
                warning(f"No state found or error: {result.stderr[:200]}")

        elif command == "/resources":
            resources = self.executor.list_resources()
            if resources:
                for r in resources:
                    console.print(f"  [cyan]▸[/cyan] {r}")
            else:
                info("No resources in state (run /init and /apply first)")

        elif command == "/outputs":
            outputs = self.executor.get_outputs()
            if outputs:
                from rich.table import Table
                from rich import box
                t = Table(box=box.SIMPLE)
                t.add_column("Output", style="bold")
                t.add_column("Value")
                for k, v in outputs.items():
                    t.add_row(k, str(v.get("value", "")))
                console.print(t)
            else:
                info("No outputs defined")

        elif command == "/init":
            section("Terraform Init", "🔧")
            for line in self.executor.init():
                _print_terraform_line(line)

        elif command == "/plan":
            section("Terraform Plan", "📋")
            plan_output = ""
            for line in self.executor.plan():
                plan_output += line
                _print_terraform_line(line)
            stats = self.executor.parse_plan_stats(plan_output)
            if any(stats[k] for k in ("add", "change", "destroy")):
                plan_summary(plan_output, stats)
                if not _has_terraform_error(plan_output):
                    self._show_cost_estimate()
            if _has_terraform_error(plan_output):
                self._explain_terraform_error(plan_output, "plan")

        elif command == "/apply":
            section("Terraform Apply", "🚀")
            if not self.config.auto_approve:
                self._show_cost_estimate()
                console.print("[bold yellow]⚠️  This will apply changes to real infrastructure.[/bold yellow]")
                confirm = console.input("[bold]Type 'yes' to confirm: [/bold]")
                if confirm.strip().lower() != "yes":
                    info("Apply cancelled")
                    return
            apply_output = ""
            for line in self.executor.apply(auto_approve=True):
                apply_output += line
                _print_terraform_line(line)
            if _has_terraform_error(apply_output):
                self._explain_terraform_error(apply_output, "apply")

        elif command == "/destroy":
            section("Terraform Destroy", "💥")
            console.print("[bold red]⚠️  DANGER: This will DESTROY all resources in your workspace![/bold red]")
            confirm = console.input("[bold red]Type 'destroy' to confirm: [/bold red]")
            if confirm.strip().lower() != "destroy":
                info("Destroy cancelled")
                return
            for line in self.executor.destroy():
                _print_terraform_line(line)

        elif command == "/clear":
            self.client.reset_history()
            success("Conversation history cleared")

        # ── Version Control ──────────────────────────────────────────────
        elif command == "/history":
            commits = self.git.get_log(limit=int(arg) if arg.isdigit() else 15)
            if not commits:
                info("No commits yet. Changes are committed automatically after each AI operation.")
                return
            from rich.table import Table
            from rich import box
            t = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold cyan")
            t.add_column("SHA", style="bold yellow", width=10)
            t.add_column("Message")
            t.add_column("Author", width=12)
            t.add_column("Date", width=20)
            for c in commits:
                t.add_row(c.short_sha, c.summary[:60], c.author, c.timestamp[:16])
            console.print(t)

        elif command == "/chronicle":
            entries = self.changelog.get_entries(limit=20)
            if not entries:
                info("No chronicle entries yet — ask TerraAI to create some infrastructure first.")
                return
            section("Infrastructure Chronicle", "📖")
            for e in entries:
                intent_icon = {"create": "✅", "modify": "✏️", "delete": "🗑️", "configure": "⚙️"}.get(e.get("intent", ""), "▶️")
                ts = e.get("timestamp", "")[:16].replace("T", " ")
                console.print(f"\n[bold]{intent_icon} [{e.get('sha','')}][/bold] [dim]{ts}[/dim]")
                console.print(f"  [white]{e.get('summary', '')}[/white]")
                if e.get("user_request"):
                    console.print(f"  [dim]💬 \"{e['user_request']}\"[/dim]")
                if e.get("resources"):
                    for r in e["resources"][:4]:
                        act_icon = {"create": "➕", "modify": "✏️", "delete": "➖"}.get(r.get("action", ""), "▸")
                        console.print(f"  [dim]{act_icon} {r.get('type','')}.{r.get('name','')}[/dim]")

        elif command == "/diff":
            args = arg.split() if arg else []
            sha1 = args[0] if args else "HEAD~1"
            sha2 = args[1] if len(args) > 1 else "HEAD"
            diff = self.git.get_diff(sha1, sha2)
            if diff:
                from rich.syntax import Syntax
                console.print(Syntax(diff, "diff", theme="monokai", line_numbers=True))
            else:
                info(f"No HCL differences between {sha1} and {sha2}")

        elif command == "/rollback":
            if not arg:
                error("Usage: /rollback <sha>")
                return
            commits = self.git.get_log()
            target = next((c for c in commits if c.sha.startswith(arg)), None)
            if not target:
                error(f"Commit {arg} not found. Run /history to list commits.")
                return
            console.print(f"[bold yellow]⚠️  Roll back to: {target.short_sha} — {target.summary}[/bold yellow]")
            confirm = console.input("[bold]Type 'yes' to restore .tf files from this commit: [/bold]")
            if confirm.strip().lower() != "yes":
                info("Rollback cancelled")
                return
            tf_files = [f["name"] for f in self.workspace.list_files()]
            for fname in tf_files:
                if self.git.checkout_file(target.sha, fname):
                    success(f"Restored {fname}")
                else:
                    warning(f"Could not restore {fname} from {target.short_sha}")
            info("Files restored. Run /plan to review changes before applying.")

        elif command == "/tag":
            args = arg.split(maxsplit=1) if arg else []
            if not args:
                error("Usage: /tag <name> [message]")
                return
            tag_name = args[0]
            msg = args[1] if len(args) > 1 else f"TerraAI: {tag_name}"
            if self.git.create_tag(tag_name, msg):
                success(f"Tagged current state as: {tag_name}")
            else:
                error(f"Failed to create tag '{tag_name}' (tag may already exist)")

        elif command == "/tags":
            tags = self.git.list_tags()
            if tags:
                for t in tags:
                    console.print(f"  [bold yellow]🏷️  {t}[/bold yellow]")
            else:
                info("No tags yet. Use /tag <name> to tag a state.")

        elif command == "/branch":
            if not arg:
                error("Usage: /branch <name>")
                return
            if self.git.create_branch(arg):
                success(f"Created and switched to branch: {arg}")
            else:
                if self.git.switch_branch(arg):
                    success(f"Switched to existing branch: {arg}")
                else:
                    error(f"Could not create or switch to branch: {arg}")

        elif command == "/branches":
            branches = self.git.list_branches()
            current = self.git.get_current_branch()
            for b in branches:
                marker = "[bold green]✓[/bold green] " if b == current else "  "
                console.print(f"{marker}[cyan]⎇[/cyan] {b}")

        elif command == "/drift":
            section("Drift Detection", "🔍")
            snapshots = self.drift.list_snapshots()
            if not snapshots:
                warning("No state snapshots found. Snapshots are taken automatically after each apply.")
                return
            latest = snapshots[0]
            baseline_sha = latest.get("sha", "")[:8]
            info(f"Comparing current state against snapshot: {baseline_sha} ({latest.get('timestamp', '')[:16]})")
            report = self.drift.detect_drift(baseline_sha)
            if not report.has_drift:
                success("No drift detected — infrastructure matches last known state ✅")
            else:
                console.print(f"\n[bold red]⚠️  Drift detected! {report.total_issues} issue(s) found[/bold red]")
                if report.drifted_resources:
                    console.print("\n[bold yellow]Modified (out-of-band changes):[/bold yellow]")
                    for r in report.drifted_resources:
                        console.print(f"  [yellow]✏️  {r['key']}[/yellow]  attrs: {', '.join(r.get('changed_attributes', []))}")
                if report.missing_resources:
                    console.print("\n[bold red]Missing (deleted outside Terraform):[/bold red]")
                    for r in report.missing_resources:
                        console.print(f"  [red]➖ {r['key']}[/red]")
                if report.extra_resources:
                    console.print("\n[bold cyan]Extra (created outside Terraform):[/bold cyan]")
                    for r in report.extra_resources:
                        console.print(f"  [cyan]➕ {r['key']}[/cyan]")
                console.print("\n[dim]Run /plan to reconcile, or ask TerraAI to fix the drift.[/dim]")

        # ── State Backend ─────────────────────────────────────────────────
        elif command == "/backend":
            sub = arg.strip().split(maxsplit=1) if arg else []
            sub_cmd = sub[0] if sub else ""
            sub_arg = sub[1] if len(sub) > 1 else ""

            if not sub_cmd or sub_cmd == "show":
                cfg = self.state_mgr.get_backend(self._active_env)
                if cfg:
                    from rich.table import Table
                    from rich import box
                    icon, label, desc = BACKEND_DISPLAY.get(cfg.type, ("🌐", cfg.type, ""))
                    console.print(f"\n[bold]{icon} Backend:[/bold] {label}  [dim]{desc}[/dim]")
                    t = Table(box=box.SIMPLE, show_header=False)
                    t.add_column("Key", style="bold cyan")
                    t.add_column("Value")
                    for k, v in cfg.params.items():
                        t.add_row(k, "***" if "key" in k.lower() or "conn" in k.lower() else str(v))
                    console.print(t)
                    console.print(f"\n[dim]Active environment:[/dim] [bold]{self._active_env}[/bold]")
                else:
                    info("No backend configured. Using Terraform default (local).")
                    console.print("[dim]Configure with: /backend set <type>[/dim]")
                    console.print("[dim]Types: local  azurerm  s3  gcs  pg  consul  kubernetes  http[/dim]")

            elif sub_cmd == "set":
                if not sub_arg:
                    error("Usage: /backend set <type>  (local azurerm s3 gcs pg consul kubernetes http)")
                    return
                wizard = BackendWizard(console)
                cfg = wizard.run(sub_arg, self._active_env)
                if cfg:
                    self.state_mgr.set_backend(cfg, self._active_env)
                    path = self.state_mgr.write_backend_tf(self._active_env)
                    success(f"Backend configured: {cfg.type}")
                    if path:
                        hcl_panel(path.read_text(encoding='utf-8'), title=f"backend.tf ({cfg.type})")
                    sha = self.git.commit(
                        f"chore(backend): configure {cfg.type} state backend for {self._active_env}",
                        author="TerraAI"
                    )
                    if sha:
                        success(f"Committed backend config [{sha[:8]}]")
                    info("Run /backend migrate to move existing state to this backend.")

            elif sub_cmd == "migrate":
                info("Running terraform init -migrate-state ...")
                result = self.state_mgr.migrate_state(self.config.terraform_bin)
                for line in result.stdout.splitlines():
                    _print_terraform_line(line)
                if result.returncode == 0:
                    success("State migration complete")
                else:
                    error(f"Migration failed: {result.stderr[:300]}")

            elif sub_cmd == "env":
                if not sub_arg:
                    envs = self.state_mgr.list_environments()
                    info(f"Available environments: {', '.join(envs) or 'none configured'}")
                    return
                self._active_env = sub_arg
                cfg = self.state_mgr.get_backend(sub_arg)
                if cfg:
                    self.state_mgr.write_backend_tf(sub_arg)
                    success(f"Switched to environment: {sub_arg} (backend: {cfg.type})")
                else:
                    info(f"Switched to environment: {sub_arg} (no backend configured — use /backend set)")

            elif sub_cmd == "list":
                federation = self.state_mgr.get_federation_map()
                if not federation:
                    info("No backends configured. Use /backend set <type>.")
                    return
                from rich.table import Table
                from rich import box
                t = Table(title="🗺️  State Federation Map", box=box.ROUNDED, header_style="bold cyan")
                t.add_column("Environment", style="bold")
                t.add_column("Backend")
                t.add_column("Config Summary")
                t.add_column("Active")
                for env, b in federation.items():
                    active = "[bold green]✓[/bold green]" if env == self._active_env else ""
                    t.add_row(env, f"{b['icon']} {b['type']}", b["params_summary"], active)
                console.print(t)

            else:
                error(f"Unknown backend subcommand: {sub_cmd}. Try /backend set/list/env/migrate")

        elif command == "/diagram":
            self._handle_diagram(arg)

        elif command == "/providers":
            from ui.panels import provider_status_table
            from config import SUPPORTED_PROVIDERS
            provider_status_table(list(SUPPORTED_PROVIDERS.keys()))

        elif command == "/models":
            from rich.table import Table
            from rich import box
            for category, models in SUPPORTED_MODELS_TABLE.items():
                if category == "Custom":
                    continue  # printed as footer note below
                t = Table(title=category, box=box.ROUNDED, show_header=True, header_style="bold cyan")
                t.add_column("Model ID")
                t.add_column("Provider")
                t.add_column("Notes")
                for m in models:
                    t.add_row(*m)
                console.print(t)
            console.print(
                "\n[dim]Switch model:[/dim] [bold]/model <model-id>[/bold]\n"
                "[dim]Custom model:[/dim] [bold]/model <any-litellm-id>[/bold]  "
                "[dim]e.g. /model mistral/mistral-large-latest[/dim]\n"
                "[dim]Update API key:[/dim] [bold]/apikey <key>[/bold]"
            )

        elif command == "/apikey":
            if not arg:
                error("Usage: /apikey <key>")
                info("Tip: Get a free Gemini key at https://aistudio.google.com/app/apikey")
                return
            self.config.api_key = arg
            self.config.save()
            self.client = TerraAIClient(self.config)
            success("API key updated and saved.")
            info(f"Model: {self.config.model}")

        elif command == "/web":
            from web.server import launch as _web_launch
            port = int(arg) if arg and arg.isdigit() else 7820
            console.print(f"[dim]Starting web UI on http://localhost:{port} ...[/dim]")
            _web_launch(self.config, port=port)

        elif command in ("/exit", "/quit", "/q"):
            console.print("[dim]Goodbye! 👋[/dim]")
            sys.exit(0)

        else:
            error(f"Unknown command: {command}. Type /help for available commands.")

    def _handle_diagram(self, arg: str) -> None:
        """Generate and open an interactive architecture diagram."""
        section("Architecture Diagram", "🗺️")
        diag = InfrastructureDiagram(self.config.workspace_dir)
        resources = diag.parse_resources()

        if not resources:
            warning(
                "No resources found. Run /apply first, or make sure .tf files are in the workspace."
            )
            return

        edges = diag.detect_relationships(resources)
        console.print(diag.ascii_summary(resources, edges))
        console.print()

        filename = arg.strip() or "architecture.html"
        out = diag.save(resources, edges, filename)
        success(f"Diagram saved → {out}")
        info(f"Open in browser: file://{out}")

        # Auto-open in browser if possible
        import subprocess, sys
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(out)])
            elif sys.platform == "linux":
                subprocess.Popen(["xdg-open", str(out)])
            elif sys.platform == "win32":
                subprocess.Popen(["start", str(out)], shell=True)
        except Exception:
            pass

    def _handle_ai_request(self, user_input: str) -> None:
        workspace_context = self.workspace.get_context()
        ai_resp: AIResponse | None = None

        console.print()
        self._maybe_warn_weak_model_for_modules()
        try:
            with Live(Spinner("dots", text="[magenta]🤖 Thinking...[/magenta]"), refresh_per_second=10, console=console):
                ai_resp = self.client.ask_sync(user_input, workspace_context)
        except Exception as exc:
            _handle_ai_error(exc, self.config.model)
            return

        if not ai_resp:
            error("No response from AI")
            return

        section(f"{ai_resp.intent.upper()} — {ai_resp.summary[:60]}", PROVIDER_ICONS.get(
            ai_resp.providers[0] if ai_resp.providers else "unknown", "🌐"
        ))

        if ai_resp.summary:
            console.print(f"\n[bold white]{ai_resp.summary}[/bold white]")

        if ai_resp.warnings:
            for w in ai_resp.warnings:
                warning(w)

        if ai_resp.resources:
            resource_table([
                {**r, "provider": ai_resp.providers[0] if ai_resp.providers else "unknown", "status": "pending"}
                for r in ai_resp.resources
            ])

        if ai_resp.has_hcl and not ai_resp.has_files and self.config.show_raw_hcl:
            hcl_panel(ai_resp.hcl)

        if ai_resp.has_files:
            if ai_resp.is_destructive:
                console.print("[bold red]⚠️  This action will DELETE resources.[/bold red]")

            from rich.table import Table
            from rich import box
            t = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan", title="📦 Module files")
            t.add_column("Path")
            t.add_column("Lines", justify="right")
            for f in ai_resp.files:
                t.add_row(f["path"], str(len(f["content"].splitlines())))
            console.print(t)

            if self.config.show_raw_hcl:
                for f in ai_resp.files:
                    hcl_panel(f["content"], title=f["path"])

            conflicts = self.workspace.find_conflicting_files(ai_resp.files)
            if conflicts:
                warning("These resources already exist elsewhere in the workspace:")
                for addr, existing_path in conflicts.items():
                    console.print(f"  [yellow]▸[/yellow] {addr} → already in [bold]{existing_path}[/bold]")
                console.print("[dim]Saving anyway may leave duplicate declarations Terraform will reject.[/dim]")

            action = console.input(
                f"[bold cyan]💾 Save {len(ai_resp.files)} file(s)? "
                f"([green]y[/green]=yes, [red]n[/red]=skip, [blue]p[/blue]=plan after save): [/bold cyan]"
            ).strip().lower()

            if action in ("y", "yes", "p"):
                saved_paths = self.workspace.write_files(ai_resp.files)
                for p in saved_paths:
                    success(f"Saved → {p}")
                hcl_file = ", ".join(f["path"] for f in ai_resp.files)
                self._auto_commit(ai_resp, hcl_file, user_input)

                if action == "p":
                    section("Terraform Plan", "📋")
                    plan_output = ""
                    for line in self.executor.plan():
                        plan_output += line
                        _print_terraform_line(line)
                    stats = self.executor.parse_plan_stats(plan_output)
                    if any(stats[k] for k in ("add", "change", "destroy")):
                        plan_summary(plan_output, stats)
                        if not _has_terraform_error(plan_output):
                            self._show_cost_estimate()
                    if _has_terraform_error(plan_output):
                        self._explain_terraform_error(plan_output, "plan")
            else:
                info("Files not saved (you can ask again or modify your request)")

        elif ai_resp.has_hcl:
            if ai_resp.is_destructive:
                console.print("[bold red]⚠️  This action will DELETE resources.[/bold red]")

            suggested_file = self.workspace.suggest_filename(
                ai_resp.intent, ai_resp.providers, ai_resp.resources, ai_resp.hcl
            )

            console.print(f"\n[dim]Suggested file:[/dim] [bold]{suggested_file}[/bold]")
            action = console.input(
                f"[bold cyan]💾 Save to [white]{suggested_file}[/white]? "
                f"([green]y[/green]=yes, [yellow]r[/yellow]=rename, [red]n[/red]=skip, "
                f"[blue]p[/blue]=plan after save): [/bold cyan]"
            ).strip().lower()

            if action in ("y", "yes", "p"):
                saved_path = self.workspace.write_hcl(suggested_file, ai_resp.hcl)
                success(f"Saved → {saved_path}")
                self._auto_commit(ai_resp, suggested_file, user_input)

                if action == "p":
                    section("Terraform Plan", "📋")
                    plan_output = ""
                    for line in self.executor.plan():
                        plan_output += line
                        _print_terraform_line(line)
                    stats = self.executor.parse_plan_stats(plan_output)
                    if any(stats[k] for k in ("add", "change", "destroy")):
                        plan_summary(plan_output, stats)
                        if not _has_terraform_error(plan_output):
                            self._show_cost_estimate()
                    if _has_terraform_error(plan_output):
                        self._explain_terraform_error(plan_output, "plan")

            elif action == "r":
                new_name = console.input("[bold]Enter filename (without .tf): [/bold]").strip()
                if new_name:
                    saved_path = self.workspace.write_hcl(new_name, ai_resp.hcl)
                    success(f"Saved → {saved_path}")
                    self._auto_commit(ai_resp, new_name + ".tf", user_input)
            else:
                info("HCL not saved (you can ask again or modify your request)")

        if ai_resp.next_steps:
            console.print("\n[bold cyan]💡 Suggested next steps:[/bold cyan]")
            for step in ai_resp.next_steps:
                console.print(f"  [dim]▸[/dim] {step}")

        console.print()

    def _auto_commit(self, ai_resp: AIResponse, hcl_file: str, user_request: str) -> None:
        """Auto-commit HCL change to git and record it in the chronicle."""
        commit_msg = self.git.build_commit_message(
            ai_resp.summary, ai_resp.intent,
            ai_resp.providers, ai_resp.resources,
        )
        sha = self.git.commit(commit_msg, author="TerraAI")
        if sha:
            console.print(f"[dim]📝 Auto-committed [{sha[:8]}] — /history to view[/dim]")
            self.changelog.record_change(
                git_sha=sha,
                intent=ai_resp.intent,
                summary=ai_resp.summary,
                providers=ai_resp.providers,
                resources=ai_resp.resources,
                warnings=ai_resp.warnings,
                user_request=user_request,
                hcl_file=hcl_file,
            )
            self.drift.snapshot_state(sha)

    def _show_cost_estimate(self) -> None:
        """Estimate costs for the current plan file and display a summary panel."""
        from terraform.cost import is_available, is_installed, estimate, PLAN_FILE
        if not is_available():
            if is_installed():
                console.print("[dim]💡 Cost estimates: set INFRACOST_API_KEY to enable[/dim]")
            return
        plan_path = self.executor.workspace_dir / PLAN_FILE
        if not plan_path.exists():
            return
        try:
            with Live(
                Spinner("dots", text="[cyan]Estimating costs...[/cyan]"),
                refresh_per_second=10,
                console=console,
            ):
                data = estimate(self.executor.workspace_dir, plan_path)
        except Exception:
            return
        if not data:
            return
        try:
            diff_val = float(data.get("diffTotalMonthlyCost") or "0")
        except (ValueError, TypeError):
            return
        sign = "+" if diff_val > 0 else ""
        color = "red" if diff_val > 0 else "green" if diff_val < 0 else "dim"
        diff_str = f"[{color}]{sign}${diff_val:,.2f} / month[/{color}]"
        lines = [f"Monthly delta:  {diff_str}", ""]
        resources: list[tuple[float, str]] = []
        for project in data.get("projects", []):
            for res in project.get("diff", {}).get("resources", []):
                name = res.get("name", "")
                try:
                    cost = float(res.get("monthlyCost") or "0")
                except (ValueError, TypeError):
                    cost = 0.0
                if name and cost != 0.0:
                    resources.append((cost, name))
        if resources:
            resources.sort(key=lambda x: abs(x[0]), reverse=True)
            lines.append("Resource breakdown:")
            for cost_v, name in resources[:8]:
                s = "+" if cost_v > 0 else ""
                c = "red" if cost_v > 0 else "green"
                lines.append(f"  {name:<44} [{c}]{s}${cost_v:,.2f}[/{c}]")
            if len(resources) > 8:
                lines.append(f"  [dim]… and {len(resources) - 8} more[/dim]")
            lines.append("")
        lines.append("[dim]Estimates use on-demand rates · excludes data transfer and free tier[/dim]")
        console.print(Panel(
            "\n".join(lines),
            title="[bold cyan]💰 Cost Estimate[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        ))
        console.print()

    def _explain_terraform_error(self, output: str, operation: str) -> None:
        """Send failed terraform output to AI and print a plain-English explanation."""
        try:
            with Live(
                Spinner("dots", text="[yellow]Analyzing error...[/yellow]"),
                refresh_per_second=10,
                console=console,
            ):
                explanation = self.client.explain_error_sync(output, operation)
        except Exception:
            return
        if explanation:
            console.print(Panel(
                explanation,
                title="[bold yellow]AI Error Analysis[/bold yellow]",
                border_style="yellow",
                padding=(1, 2),
            ))
            console.print()


def _has_terraform_error(output: str) -> bool:
    """Return True if terraform output contains an error line."""
    return bool(re.search(r'(?m)^[ \t│]*Error:', output))


def _handle_ai_error(exc: Exception, model: str) -> None:
    """Translate LiteLLM exceptions into friendly, actionable messages."""
    from rich.panel import Panel
    msg = str(exc)

    # Ollama: model not pulled
    if "model" in msg and "not found" in msg and model.startswith("ollama/"):
        model_name = model.split("/", 1)[-1]
        console.print(Panel(
            f"[bold red]Ollama model not found:[/bold red] [white]{model_name}[/white]\n\n"
            f"Pull it first:\n"
            f"  [bold green]ollama pull {model_name}[/bold green]\n\n"
            f"Then re-run your request. Check available models with:\n"
            f"  [bold green]ollama list[/bold green]",
            title="[bold yellow]⚠️  Ollama Model Missing[/bold yellow]",
            border_style="yellow",
        ))
        return

    # Ollama: server not running
    if ("connection refused" in msg.lower() or "connection error" in msg.lower()) and model.startswith("ollama/"):
        console.print(Panel(
            "[bold red]Cannot connect to Ollama.[/bold red]\n\n"
            "Start Ollama first:\n"
            "  [bold green]ollama serve[/bold green]\n\n"
            "Default address: [cyan]http://localhost:11434[/cyan]\n"
            "Custom address:  [cyan]./terraai --model ollama/codellama --api-base http://HOST:PORT[/cyan]",
            title="[bold yellow]⚠️  Ollama Not Running[/bold yellow]",
            border_style="yellow",
        ))
        return

    # Auth / API key errors
    if any(k in msg.lower() for k in ("401", "403", "unauthorized", "invalid api key", "authentication")):
        env_var = _model_to_env_var(model)
        console.print(Panel(
            f"[bold red]Authentication failed for model:[/bold red] [white]{model}[/white]\n\n"
            f"Your API key is missing or invalid.\n\n"
            f"Fix options:\n"
            f"  [cyan]1[/cyan]  export [bold]{env_var}[/bold]=your_key\n"
            f"  [cyan]2[/cyan]  ./terraai configure --api-key your_key\n"
            f"  [cyan]3[/cyan]  ./terraai --api-key your_key  (inline, not saved)\n\n"
            f"Run [bold]./terraai models[/bold] to see which env var each model needs.",
            title="[bold red]🔑 API Key Error[/bold red]",
            border_style="red",
        ))
        return

    # Rate limit
    if any(k in msg.lower() for k in ("429", "rate limit", "quota")):
        console.print(Panel(
            f"[bold yellow]Rate limit hit for:[/bold yellow] [white]{model}[/white]\n\n"
            "Wait a moment and try again, or switch to a different model:\n"
            "  [bold green]/model groq/llama3-70b-8192[/bold green]   (generous free tier)\n"
            "  [bold green]/model ollama/codellama[/bold green]        (local, no limits)",
            title="[bold yellow]⚠️  Rate Limited[/bold yellow]",
            border_style="yellow",
        ))
        return

    # Model not found on provider
    if any(k in msg.lower() for k in ("model not found", "no such model", "does not exist", "404")):
        # Gemini 404 almost always means a revoked or invalid API key
        if model.startswith("gemini"):
            console.print(Panel(
                f"[bold red]Gemini request failed:[/bold red] [white]{model}[/white]\n\n"
                "This usually means your API key is [bold]expired or revoked[/bold].\n\n"
                "Get a fresh key at:\n"
                "  [cyan]https://aistudio.google.com/app/apikey[/cyan]\n\n"
                "Then update TerraAI in-session:\n"
                "  [bold green]/apikey YOUR_NEW_GEMINI_KEY[/bold green]\n\n"
                "Or set as env var before starting:\n"
                "  [bold green]export GEMINI_API_KEY=YOUR_KEY[/bold green]",
                title="[bold red]❌ Gemini API Key Error[/bold red]",
                border_style="red",
            ))
            return
        console.print(Panel(
            f"[bold red]Model not found:[/bold red] [white]{model}[/white]\n\n"
            "Check the model ID is correct. Run:\n"
            "  [bold green]./terraai models[/bold green]  — to list valid model IDs\n\n"
            "Common fixes:\n"
            "  • Ollama: [bold]ollama pull codellama[/bold]\n"
            "  • Groq: check [cyan]console.groq.com[/cyan] for available model names\n"
            "  • OpenAI: use [bold]gpt-4o[/bold] or [bold]gpt-4o-mini[/bold]",
            title="[bold red]❌ Model Not Found[/bold red]",
            border_style="red",
        ))
        return

    # Timeout
    if "timeout" in msg.lower():
        console.print(Panel(
            f"[bold yellow]Request timed out for:[/bold yellow] [white]{model}[/white]\n\n"
            "The model took too long to respond.\n"
            "Try a faster model:\n"
            "  [bold green]/model groq/llama3-70b-8192[/bold green]   (very fast)\n"
            "  [bold green]/model gpt-4o-mini[/bold green]            (fast + cheap)",
            title="[bold yellow]⏱️  Timeout[/bold yellow]",
            border_style="yellow",
        ))
        return

    # Generic fallback — show error but don't crash
    console.print(Panel(
        f"[bold red]AI request failed[/bold red]\n\n"
        f"Model: [white]{model}[/white]\n"
        f"Error: [yellow]{msg[:300]}[/yellow]\n\n"
        "You can:\n"
        "  • Try rephrasing your request\n"
        "  • Switch model: [bold]/model gpt-4o-mini[/bold]\n"
        "  • Check your API key: [bold]/config[/bold]",
        title="[bold red]❌ AI Error[/bold red]",
        border_style="red",
    ))


def _model_to_env_var(model: str) -> str:
    prefix = model.lower().split("/")[0]
    return {
        "gpt": "OPENAI_API_KEY", "o1": "OPENAI_API_KEY",
        "claude": "ANTHROPIC_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "groq": "GROQ_API_KEY",
        "azure": "AZURE_OPENAI_API_KEY",
        "mistral": "MISTRAL_API_KEY",
        "cohere": "COHERE_API_KEY",
    }.get(prefix, "OPENAI_API_KEY")


def _print_terraform_line(line: str) -> None:
    line = line.rstrip()
    if not line:
        return
    if "Error" in line or "error" in line:
        console.print(f"[red]{line}[/red]")
    elif "Warning" in line or "warning" in line:
        console.print(f"[yellow]{line}[/yellow]")
    elif line.startswith("  +") or "will be created" in line:
        console.print(f"[green]{line}[/green]")
    elif line.startswith("  -") or "will be destroyed" in line:
        console.print(f"[red]{line}[/red]")
    elif line.startswith("  ~") or "will be updated" in line:
        console.print(f"[yellow]{line}[/yellow]")
    elif "Apply complete" in line or "successfully" in line.lower():
        console.print(f"[bold green]{line}[/bold green]")
    elif "Plan:" in line:
        console.print(f"[bold yellow]{line}[/bold yellow]")
    else:
        console.print(f"[dim]{line}[/dim]")
