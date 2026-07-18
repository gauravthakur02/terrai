"""
TerraAI first-run setup wizard.

Guides the user through:
  1. Workspace directory
  2. Git repo (new / clone remote / skip)
  3. AI model + API key
  4. Cloud provider + credentials
  5. State backend
"""
from __future__ import annotations
import os
import subprocess
from pathlib import Path
from typing import Optional

from rich.panel import Panel
from rich.rule import Rule
from rich import box
from rich.table import Table

from config.settings import TerraAIConfig, KEYRING_AVAILABLE

_TERRAAI_SRC_DIR = Path(__file__).parent.parent.resolve()


class SetupWizard:
    """Interactive first-run wizard. Returns a fully configured TerraAIConfig."""

    FREE_MODELS = [
        ("groq/llama3-70b-8192",    "Groq",    "Free tier — fastest option",     "GROQ_API_KEY",   "console.groq.com/keys"),
        ("gemini/gemini-1.5-flash", "Google",  "Free tier — large context",      "GEMINI_API_KEY", "aistudio.google.com/app/apikey"),
        ("ollama/codellama",        "Ollama",  "Local — no key, needs 8 GB RAM", None,             "ollama.com"),
        ("ollama/llama3",           "Ollama",  "Local — general purpose",        None,             "ollama.com"),
    ]
    PAID_MODELS = [
        ("gpt-4o",                  "OpenAI",     "Best overall quality",        "OPENAI_API_KEY",      "platform.openai.com/api-keys"),
        ("gpt-4o-mini",             "OpenAI",     "Fast & cheap",                "OPENAI_API_KEY",      "platform.openai.com/api-keys"),
        ("claude-sonnet-4-6",       "Anthropic",  "Strong HCL reasoning",        "ANTHROPIC_API_KEY",   "console.anthropic.com/settings/keys"),
        ("claude-haiku-4-5-20251001","Anthropic", "Fast Anthropic model",        "ANTHROPIC_API_KEY",   "console.anthropic.com/settings/keys"),
        ("groq/llama3-70b-8192",    "Groq",       "Fast inference, paid plan",   "GROQ_API_KEY",        "console.groq.com/keys"),
        ("azure/gpt-4o",            "Azure OpenAI","Enterprise Azure-hosted",    "AZURE_OPENAI_API_KEY","portal.azure.com"),
    ]

    def __init__(self, console, config: TerraAIConfig, src_dir: Optional[Path] = None):
        self.console = console
        self.config = config
        self._src = src_dir or _TERRAAI_SRC_DIR

    def run(self) -> TerraAIConfig:
        self.console.print()
        self.console.print(Panel(
            "[bold cyan]Welcome to TerraAI![/bold cyan]\n\n"
            "This short wizard will configure:\n"
            "  [cyan]1[/cyan]  Workspace directory\n"
            "  [cyan]2[/cyan]  Git repository\n"
            "  [cyan]3[/cyan]  AI model + API key\n"
            "  [cyan]4[/cyan]  Cloud provider credentials\n"
            "  [cyan]5[/cyan]  Terraform state backend\n\n"
            "[dim]You can re-run this at any time with:[/dim] [bold]./terraai setup[/bold]",
            title="[bold]🌍 First-Time Setup[/bold]",
            border_style="cyan",
        ))
        self.console.print()

        self._step_workspace()
        self._step_git()
        self._step_ai_model()
        self._step_provider_credentials()
        self._step_backend()

        self.config.setup_complete = True
        self.config.save()

        self.console.print()
        self.console.print(Rule("[bold green]✅ Setup complete![/bold green]", style="green"))
        self.console.print()
        self.console.print(Panel(
            "[bold]You're ready to go.[/bold]\n\n"
            "[dim]Start a session:[/dim]\n"
            "  [bold green]./terraai[/bold green]\n\n"
            "[dim]Or jump straight to a provider:[/dim]\n"
            "  [bold green]./terraai --provider azure[/bold green]\n\n"
            "[dim]In the session, just describe your infrastructure:[/dim]\n"
            '  "create a resource group named rg-prod in East US"\n'
            '  "add an AKS cluster with 3 nodes"\n'
            '  "delete the staging storage account"',
            title="[bold cyan]🚀 You're all set[/bold cyan]",
            border_style="green",
        ))
        return self.config

    # ── Step 1: Workspace ─────────────────────────────────────────────────

    def _step_workspace(self) -> None:
        self.console.print(Rule("[bold]Step 1 of 5 — Workspace[/bold]", style="cyan"))
        self.console.print(
            "[dim]Where should TerraAI write your Terraform files?\n"
            "This must be a separate directory from the TerraAI install.[/dim]\n"
        )

        if self.config.workspace_dir:
            p = Path(self.config.workspace_dir)
            reuse = self.console.input(
                f"[bold]Use existing workspace [cyan]{p}[/cyan]? (y/n): [/bold]"
            ).strip().lower()
            if reuse == "y":
                self.console.print(f"[dim]✓ Using workspace: {p}[/dim]\n")
                return

        self.console.print(
            "  [cyan]n[/cyan]  Create a new directory automatically\n"
            "  [cyan]p[/cyan]  Enter a custom path\n"
        )
        choice = self.console.input("[bold]Choice (n/p): [/bold]").strip().lower()

        if choice == "p":
            raw = self.console.input("[bold]Full path: [/bold]").strip()
            if not raw:
                self.console.print("[dim]Skipped — no path entered.[/dim]\n")
                return
            p = Path(raw).expanduser().resolve()
        else:
            name = self.console.input(
                "[bold]Directory name [/bold][dim](created under ~/terraai-workspaces/): [/dim]"
            ).strip() or "my-infra"
            p = (Path.home() / "terraai-workspaces" / name).resolve()

        if p == self._src:
            self.console.print("[bold red]✗ Cannot use the TerraAI source directory.[/bold red]\n")
            return

        p.mkdir(parents=True, exist_ok=True)
        self.config.workspace_dir = str(p)
        self.console.print(f"[green]✓ Workspace:[/green] {p}\n")

    # ── Step 2: Git ───────────────────────────────────────────────────────

    def _step_git(self) -> None:
        self.console.print(Rule("[bold]Step 2 of 5 — Git Repository[/bold]", style="cyan"))
        ws = Path(self.config.workspace_dir) if self.config.workspace_dir else None
        if ws is None:
            self.console.print("[dim]Skipped — no workspace set.[/dim]\n")
            return

        git_dir = ws / ".git"
        if git_dir.exists():
            self.console.print(f"[green]✓ Git repo already initialised in workspace.[/green]\n")
            # Optionally add a remote
            self._maybe_add_remote(ws)
            return

        self.console.print(
            "[dim]Version control lets TerraAI auto-commit every Terraform change "
            "with AI-written messages and build your Chronicle.[/dim]\n"
        )
        self.console.print(
            "  [cyan]1[/cyan]  Initialise a new git repo here\n"
            "  [cyan]2[/cyan]  Clone an existing remote repo (GitHub, GitLab, etc.)\n"
            "  [cyan]s[/cyan]  Skip\n"
        )
        choice = self.console.input("[bold]Choice (1/2/s): [/bold]").strip().lower()

        if choice == "1":
            self._git_init(ws)
            self._maybe_add_remote(ws)

        elif choice == "2":
            url = self.console.input("[bold]Remote URL (https://github.com/org/repo): [/bold]").strip()
            if url:
                self._git_clone(url, ws)
            else:
                self.console.print("[dim]No URL entered — initialising empty repo instead.[/dim]")
                self._git_init(ws)

        else:
            self.console.print("[dim]Skipped git setup.[/dim]\n")

    def _git_init(self, ws: Path) -> None:
        try:
            subprocess.run(["git", "init"], cwd=ws, capture_output=True, check=True)
            gitignore = ws / ".gitignore"
            if not gitignore.exists():
                gitignore.write_text(
                    "# TerraAI — auto-generated .gitignore\n"
                    ".terraform/\n*.tfvars\ntfplan\n.terraform.lock.hcl\n"
                    "terraform.tfstate\nterraform.tfstate.backup\n.terraai/\n"
                )
            self.console.print(f"[green]✓ Initialised git repo in {ws}[/green]\n")
        except subprocess.CalledProcessError as e:
            self.console.print(f"[yellow]⚠ git init failed: {e.stderr.decode()[:100]}[/yellow]\n")

    def _git_clone(self, url: str, ws: Path) -> None:
        self.console.print(f"[dim]Cloning {url} into {ws} …[/dim]")
        try:
            # Clone into a temp subdir, then move contents up if workspace exists
            import tempfile, shutil
            with tempfile.TemporaryDirectory() as tmp:
                subprocess.run(
                    ["git", "clone", url, tmp + "/repo"],
                    check=True,
                    capture_output=True,
                )
                src = Path(tmp) / "repo"
                for item in src.iterdir():
                    dest = ws / item.name
                    if dest.exists():
                        continue
                    shutil.move(str(item), str(dest))
            self.console.print(f"[green]✓ Cloned into {ws}[/green]\n")
        except subprocess.CalledProcessError as e:
            self.console.print(f"[red]✗ Clone failed: {e.stderr.decode()[:200]}[/red]")
            self.console.print("[dim]Falling back to fresh git init.[/dim]\n")
            self._git_init(ws)

    def _maybe_add_remote(self, ws: Path) -> None:
        res = subprocess.run(
            ["git", "remote", "-v"], cwd=ws, capture_output=True, text=True
        )
        if res.stdout.strip():
            self.console.print(f"[dim]Remote already configured:[/dim] {res.stdout.strip().splitlines()[0]}\n")
            return
        add = self.console.input(
            "[bold]Add a remote repo URL for pushing? [/bold][dim](Leave blank to skip): [/dim]"
        ).strip()
        if add:
            subprocess.run(["git", "remote", "add", "origin", add], cwd=ws, capture_output=True)
            self.console.print(f"[green]✓ Remote 'origin' → {add}[/green]\n")
        else:
            self.console.print()

    # ── Step 3: AI model + API key ────────────────────────────────────────

    def _step_ai_model(self) -> None:
        self.console.print(Rule("[bold]Step 3 of 5 — AI Model[/bold]", style="cyan"))

        t = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
        t.add_column("#", width=4)
        t.add_column("Model ID")
        t.add_column("Provider")
        t.add_column("Notes")
        t.add_column("Requires")

        rows = []
        for model, prov, note, env, _ in self.FREE_MODELS:
            rows.append((model, prov, note, "[green]Free[/green]" if env else "[dim]Local[/dim]", env))
        for model, prov, note, env, _ in self.PAID_MODELS:
            rows.append((model, prov, note, "[yellow]Paid[/yellow]", env))

        for i, (model, prov, note, tier, env) in enumerate(rows, 1):
            t.add_row(
                str(i), model, prov,
                f"{tier} — {note}",
                env or "[dim]none[/dim]",
            )
        self.console.print(t)
        self.console.print()

        current_idx = next(
            (i + 1 for i, (m, *_) in enumerate(rows) if m == self.config.model), None
        )
        prompt = f"[bold]Choose model number [/bold][dim](current: {self.config.model}"
        if current_idx:
            prompt += f", Enter to keep"
        prompt += "): [/dim]"

        raw = self.console.input(prompt).strip()
        if raw.isdigit() and 1 <= int(raw) <= len(rows):
            chosen = rows[int(raw) - 1]
            self.config.model = chosen[0]
        elif not raw and self.config.model:
            pass  # keep current
        else:
            self.console.print("[dim]Keeping current model.[/dim]")

        self.console.print(f"[green]✓ Model:[/green] {self.config.model}\n")

        # API key setup
        all_models = list(self.FREE_MODELS) + list(self.PAID_MODELS)
        model_info = next(
            (m for m in all_models if m[0] == self.config.model), None
        )
        env_var = model_info[3] if model_info else None

        if env_var is None:
            # Ollama — no key
            self.console.print(
                "[dim]Ollama runs locally — no API key needed.\n"
                "Make sure Ollama is running: [green]ollama serve[/green]\n"
                f"Pull model if needed: [green]ollama pull {self.config.model.split('/', 1)[-1]}[/green][/dim]\n"
            )
            return

        # Check if key already set
        existing = os.environ.get(env_var) or self.config.get_api_key()
        if existing:
            self.console.print(f"[green]✓ API key already set ({env_var})[/green]\n")
            return

        provider_name = model_info[1] if model_info else "provider"
        signup_url = model_info[4] if model_info else ""
        self.console.print(
            f"[bold yellow]🔑 API key required:[/bold yellow] {env_var}\n"
            f"[dim]Get one at: {signup_url}[/dim]\n"
        )
        self.console.print(
            "  [cyan]1[/cyan]  Paste key now (stored securely)\n"
            "  [cyan]2[/cyan]  I'll set the env var later\n"
            "  [cyan]s[/cyan]  Skip\n"
        )
        choice = self.console.input("[bold]Choice: [/bold]").strip().lower()

        if choice == "1":
            key = self.console.input(f"[bold]Paste {provider_name} API key: [/bold]").strip()
            if key:
                provider_slug = (model_info[1] if model_info else "openai").lower()
                used_keyring = self.config.save_api_key_secure(key, provider_slug)
                if used_keyring:
                    self.console.print(f"[green]✓ Key saved to OS keyring (not on disk)[/green]\n")
                else:
                    self.console.print(f"[green]✓ Key saved to ~/.terraai/config.yaml (chmod 600)[/green]\n")
        elif choice == "2":
            self.console.print(f"[dim]Run before launching TerraAI:\n  export {env_var}=your_key[/dim]\n")
        else:
            self.console.print("[dim]Skipped — you can set the key later.[/dim]\n")

    # ── Step 4: Cloud provider credentials ───────────────────────────────

    def _step_provider_credentials(self) -> None:
        self.console.print(Rule("[bold]Step 4 of 5 — Cloud Provider Credentials[/bold]", style="cyan"))

        providers = ["azure", "aws", "gcp", "kubernetes", "skip"]
        self.console.print(
            "  [cyan]1[/cyan]  Azure\n"
            "  [cyan]2[/cyan]  AWS\n"
            "  [cyan]3[/cyan]  GCP\n"
            "  [cyan]4[/cyan]  Kubernetes\n"
            "  [cyan]s[/cyan]  Skip (set up manually later)\n"
        )
        current = self.config.default_provider
        choice = self.console.input(
            f"[bold]Provider [dim](current: {current})[/dim]: [/bold]"
        ).strip().lower()

        if choice == "1" or (not choice and current == "azure"):
            self.config.default_provider = "azure"
            self._setup_azure()
        elif choice == "2":
            self.config.default_provider = "aws"
            self._setup_aws()
        elif choice == "3":
            self.config.default_provider = "gcp"
            self._setup_gcp()
        elif choice == "4":
            self.config.default_provider = "kubernetes"
            self.console.print("[dim]Kubernetes: ensure KUBECONFIG is set or ~/.kube/config exists.[/dim]\n")
        else:
            self.console.print("[dim]Skipped credentials setup.[/dim]\n")

    def _setup_azure(self) -> None:
        self.console.print("\n[bold]Azure Authentication[/bold]\n")

        # Detect az login
        az_logged_in = self._detect_az_login()

        self.console.print(
            "  [cyan]1[/cyan]  Azure CLI (az login) — easiest, uses your existing session\n"
            + (
                "         [green]✓ az login session detected[/green]\n"
                if az_logged_in else
                "         [dim]Run 'az login' in a terminal first[/dim]\n"
            )
            + "  [cyan]2[/cyan]  Service Principal (Client ID + Secret) — for CI/CD\n"
            "  [cyan]3[/cyan]  Managed Identity — for Azure VMs / AKS only\n"
            "  [cyan]s[/cyan]  Skip\n"
        )
        choice = self.console.input("[bold]Auth method: [/bold]").strip().lower()

        sub_id = self.console.input(
            "[bold]Azure Subscription ID[/bold] [dim](or Enter to skip): [/dim]"
        ).strip()
        if sub_id:
            self.config.azure_subscription_id = sub_id

        if choice == "1":
            self.config.azure_use_cli_auth = True
            self.config.azure_use_msi = False
            self.console.print("[green]✓ Will use Azure CLI auth (ARM_USE_CLI=true)[/green]\n")

        elif choice == "2":
            tenant = self.console.input("[bold]Tenant ID: [/bold]").strip()
            client = self.console.input("[bold]Client ID (App ID): [/bold]").strip()
            secret = self.console.input("[bold]Client Secret: [/bold]").strip()
            if tenant:
                self.config.azure_tenant_id = tenant
            if client:
                self.config.azure_client_id = client
            if secret:
                used_kr = self.config.save_azure_secret_secure(secret)
                if used_kr:
                    self.console.print("[green]✓ Client secret saved to OS keyring[/green]")
                else:
                    self.console.print("[green]✓ Client secret saved as env var ARM_CLIENT_SECRET[/green]")
            self.console.print()

        elif choice == "3":
            self.config.azure_use_msi = True
            self.console.print("[green]✓ Will use Managed Identity (ARM_USE_MSI=true)[/green]\n")

        else:
            self.console.print(
                "[dim]Skipped. Set these env vars before running /apply:\n"
                "  export ARM_SUBSCRIPTION_ID=...\n"
                "  export ARM_TENANT_ID=...\n"
                "  export ARM_CLIENT_ID=...\n"
                "  export ARM_CLIENT_SECRET=...[/dim]\n"
            )

    def _setup_aws(self) -> None:
        self.console.print("\n[bold]AWS Credentials[/bold]\n")
        self.console.print(
            "[dim]TerraAI uses the standard AWS credential chain:\n"
            "  • Environment variables (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY)\n"
            "  • ~/.aws/credentials (from 'aws configure')\n"
            "  • IAM role attached to the instance[/dim]\n"
        )
        key_id = self.console.input(
            "[bold]AWS Access Key ID[/bold] [dim](or Enter if already configured): [/dim]"
        ).strip()
        if key_id:
            os.environ["AWS_ACCESS_KEY_ID"] = key_id
            secret = self.console.input("[bold]AWS Secret Access Key: [/bold]").strip()
            if secret:
                used_kr = False
                if KEYRING_AVAILABLE:
                    try:
                        import keyring as _kr
                        _kr.set_password("terraai", "aws_secret", secret)
                        used_kr = True
                    except Exception:
                        pass
                if not used_kr:
                    os.environ["AWS_SECRET_ACCESS_KEY"] = secret
                self.console.print("[green]✓ AWS credentials stored[/green]\n")
        else:
            self.console.print("[dim]Using existing AWS credential chain.[/dim]\n")

    def _setup_gcp(self) -> None:
        self.console.print("\n[bold]GCP Credentials[/bold]\n")
        self.console.print(
            "[dim]TerraAI uses Application Default Credentials.\n"
            "Run [green]gcloud auth application-default login[/green] if not already authenticated.[/dim]\n"
        )
        project = self.console.input(
            "[bold]GCP Project ID[/bold] [dim](or Enter to skip): [/dim]"
        ).strip()
        if project:
            os.environ["GOOGLE_PROJECT"] = project
            self.console.print(f"[green]✓ GCP project: {project}[/green]\n")

    def _detect_az_login(self) -> bool:
        try:
            result = subprocess.run(
                ["az", "account", "show", "--query", "id", "-o", "tsv"],
                capture_output=True, text=True, timeout=5,
            )
            return result.returncode == 0 and result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    # ── Step 5: State backend ─────────────────────────────────────────────

    def _step_backend(self) -> None:
        self.console.print(Rule("[bold]Step 5 of 5 — State Backend[/bold]", style="cyan"))
        self.console.print(
            "[dim]The Terraform state file tracks real infrastructure. "
            "For teams, store it remotely so everyone sees the same state.[/dim]\n"
        )
        self.console.print(
            "  [cyan]1[/cyan]  Local   — state lives on this machine (fine for solo dev)\n"
            "  [cyan]2[/cyan]  Azure Blob Storage  — recommended for Azure users\n"
            "  [cyan]3[/cyan]  S3      — recommended for AWS users\n"
            "  [cyan]4[/cyan]  GCS     — recommended for GCP users\n"
            "  [cyan]5[/cyan]  PostgreSQL — on-prem / self-hosted\n"
            "  [cyan]s[/cyan]  Skip (configure later with [bold]/backend set[/bold])\n"
        )
        choice = self.console.input("[bold]Backend choice: [/bold]").strip().lower()

        backend_map = {"1": "local", "2": "azurerm", "3": "s3", "4": "gcs", "5": "pg"}
        backend_type = backend_map.get(choice)

        if backend_type == "local" or not backend_type:
            self.console.print(
                "[green]✓ Using local state — fine for now.[/green]\n"
                "[dim]Switch later with: /backend set azurerm[/dim]\n"
            )
            return

        if backend_type and choice != "s":
            self.console.print(
                f"\n[dim]Backend [bold]{backend_type}[/bold] selected. "
                f"You'll be prompted to configure it when you start a session.\n"
                f"Command: [bold]/backend set {backend_type}[/bold][/dim]\n"
            )
            # Record the intent so the session auto-prompts
            ws = Path(self.config.workspace_dir) if self.config.workspace_dir else None
            if ws:
                meta_dir = ws / ".terraai"
                meta_dir.mkdir(exist_ok=True)
                (meta_dir / "pending_backend").write_text(backend_type)
        else:
            self.console.print("[dim]Skipped. Configure later with: /backend set <type>[/dim]\n")
