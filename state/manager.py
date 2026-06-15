from __future__ import annotations
import json
import subprocess
from pathlib import Path
from typing import Optional
from .backends import BackendConfig, BackendBuilder, BACKEND_DISPLAY

STATE_CONFIG_FILE = ".terraai/state_config.json"
BACKEND_TF_FILE = "backend.tf"


class StateManager:
    """
    Manages Terraform state backend configuration.
    Supports multi-environment routing: dev/staging/prod can each point
    to different backends from a single federated config.
    """

    def __init__(self, workspace_dir: str):
        self.root = Path(workspace_dir)
        self._config_path = self.root / STATE_CONFIG_FILE
        self._config_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_all(self) -> dict:
        if self._config_path.exists():
            try:
                return json.loads(self._config_path.read_text())
            except Exception:
                pass
        return {}

    def _save_all(self, data: dict) -> None:
        self._config_path.write_text(json.dumps(data, indent=2))

    def set_backend(self, config: BackendConfig, environment: str = "default") -> None:
        """Save backend config for a given environment."""
        all_configs = self._load_all()
        all_configs[environment] = config.to_dict()
        self._save_all(all_configs)

    def get_backend(self, environment: str = "default") -> Optional[BackendConfig]:
        all_configs = self._load_all()
        data = all_configs.get(environment) or all_configs.get("default")
        return BackendConfig.from_dict(data) if data else None

    def list_environments(self) -> list[str]:
        return list(self._load_all().keys())

    def write_backend_tf(self, environment: str = "default") -> Optional[Path]:
        """Write backend.tf for the active environment."""
        config = self.get_backend(environment)
        if not config:
            return None
        backend_tf = self.root / BACKEND_TF_FILE
        backend_tf.write_text(config.to_hcl() + "\n")
        return backend_tf

    def migrate_state(self, executor_bin: str = "terraform") -> subprocess.CompletedProcess:
        """Run terraform init -migrate-state after backend change."""
        return subprocess.run(
            [executor_bin, "init", "-migrate-state", "-force-copy", "-no-color"],
            cwd=self.root,
            capture_output=True,
            text=True,
        )

    def get_federation_map(self) -> dict:
        """Returns all environments and their backend types — the federation map."""
        result = {}
        for env, cfg in self._load_all().items():
            result[env] = {
                "type": cfg.get("type"),
                "icon": BACKEND_DISPLAY.get(cfg.get("type", ""), ("🌐",))[0],
                "description": BACKEND_DISPLAY.get(cfg.get("type", ""), ("", "", ""))[2],
                "params_summary": _summarize_params(cfg.get("params", {})),
            }
        return result


def _summarize_params(params: dict) -> str:
    key_map = {
        "path": lambda v: f"path={v}",
        "storage_account_name": lambda v: f"storage={v}",
        "bucket": lambda v: f"bucket={v}",
        "conn_str": lambda v: "conn=***",
        "address": lambda v: f"addr={v}",
        "namespace": lambda v: f"ns={v}",
    }
    parts = []
    for k, fmt in key_map.items():
        if k in params:
            parts.append(fmt(params[k]))
    return ", ".join(parts[:3]) if parts else "configured"


class BackendWizard:
    """
    Interactive wizard for configuring state backends.
    Returns a BackendConfig without touching files — caller decides when to write.
    """

    def __init__(self, console):
        self.console = console

    def run(self, backend_type: str, environment: str = "default") -> Optional[BackendConfig]:
        from ui import info, warning
        t = backend_type.lower()

        if t == "local":
            return self._wizard_local()
        elif t == "azurerm":
            return self._wizard_azurerm(environment)
        elif t == "s3":
            return self._wizard_s3(environment)
        elif t == "gcs":
            return self._wizard_gcs(environment)
        elif t == "pg":
            return self._wizard_pg()
        elif t == "consul":
            return self._wizard_consul()
        elif t == "kubernetes":
            return self._wizard_kubernetes()
        elif t == "http":
            return self._wizard_http()
        else:
            warning(f"Unknown backend type: {t}")
            return None

    def _prompt(self, label: str, default: str = "") -> str:
        suffix = f" [{default}]" if default else ""
        val = self.console.input(f"  [cyan]{label}{suffix}:[/cyan] ").strip()
        return val or default

    def _wizard_local(self) -> BackendConfig:
        self.console.print("\n[bold]📁 Local Backend Configuration[/bold]")
        path = self._prompt("State file path", "./terraform.tfstate")
        return BackendBuilder.local(path=path)

    def _wizard_azurerm(self, env: str) -> BackendConfig:
        self.console.print("\n[bold]☁️  Azure Blob Storage Backend[/bold]")
        self.console.print("[dim]Requires: Storage Account with a container for state files.[/dim]")
        self.console.print("[dim]Auth: ARM_ACCESS_KEY, ARM_SAS_TOKEN, or MSI env vars.[/dim]\n")
        rg = self._prompt("Resource Group name")
        sa = self._prompt("Storage Account name")
        container = self._prompt("Container name", "tfstate")
        key = self._prompt("Blob key (state file name)", f"{env}/terraform.tfstate")
        use_msi = self._prompt("Use Managed Identity? (y/n)", "n").lower() == "y"
        sub_id = self._prompt("Subscription ID (optional, or set ARM_SUBSCRIPTION_ID)", "")
        return BackendBuilder.azurerm(
            resource_group=rg, storage_account=sa,
            container=container, key=key,
            use_msi=use_msi, subscription_id=sub_id,
        )

    def _wizard_s3(self, env: str) -> BackendConfig:
        self.console.print("\n[bold]🟠 AWS S3 Backend[/bold]")
        self.console.print("[dim]Requires: S3 bucket + optional DynamoDB table for state locking.[/dim]\n")
        bucket = self._prompt("S3 bucket name")
        key = self._prompt("State key path", f"terraform/{env}/terraform.tfstate")
        region = self._prompt("AWS region", "us-east-1")
        ddb = self._prompt("DynamoDB table for locking (optional)", "")
        profile = self._prompt("AWS profile (optional, or use default)", "")
        return BackendBuilder.s3(
            bucket=bucket, key=key, region=region,
            dynamodb_table=ddb, encrypt=True, profile=profile,
        )

    def _wizard_gcs(self, env: str) -> BackendConfig:
        self.console.print("\n[bold]🔵 Google Cloud Storage Backend[/bold]")
        self.console.print("[dim]Requires: GCS bucket. Auth via GOOGLE_CREDENTIALS or Application Default.[/dim]\n")
        bucket = self._prompt("GCS bucket name")
        prefix = self._prompt("State prefix path", f"terraform/{env}")
        return BackendBuilder.gcs(bucket=bucket, prefix=prefix)

    def _wizard_pg(self) -> BackendConfig:
        self.console.print("\n[bold]🐘 PostgreSQL Backend[/bold]")
        self.console.print("[dim]Self-hosted open-source option. State stored in a PG table.[/dim]")
        self.console.print("[dim]Set PG_CONN_STR env var or provide connection string below.[/dim]\n")
        conn = self._prompt("Connection string (or set PG_CONN_STR env var)", "")
        schema = self._prompt("Schema name", "terraform_state")
        return BackendBuilder.pg(conn_str=conn or os.environ.get("PG_CONN_STR", ""), schema_name=schema)

    def _wizard_consul(self) -> BackendConfig:
        self.console.print("\n[bold]🔶 HashiCorp Consul Backend[/bold]")
        self.console.print("[dim]Open-source. Ideal if you already run Consul for service mesh.[/dim]\n")
        addr = self._prompt("Consul address", "127.0.0.1:8500")
        path = self._prompt("KV path", "terraform")
        scheme = self._prompt("Scheme", "http")
        return BackendBuilder.consul(address=addr, path=path, scheme=scheme)

    def _wizard_kubernetes(self) -> BackendConfig:
        self.console.print("\n[bold]⎈ Kubernetes Secret Backend[/bold]")
        self.console.print("[dim]State stored as a K8s Secret. Ideal for K8s-native workflows.[/dim]\n")
        suffix = self._prompt("Secret suffix (e.g. 'prod-cluster')")
        namespace = self._prompt("Namespace", "default")
        kubeconfig = self._prompt("kubeconfig path (optional)", "")
        return BackendBuilder.kubernetes(secret_suffix=suffix, namespace=namespace, config_path=kubeconfig)

    def _wizard_http(self) -> BackendConfig:
        self.console.print("\n[bold]🌐 HTTP Backend[/bold]")
        self.console.print("[dim]Generic REST backend. Bring your own state server.[/dim]\n")
        addr = self._prompt("State endpoint URL")
        lock = self._prompt("Lock endpoint URL (optional)", "")
        unlock = self._prompt("Unlock endpoint URL (optional)", "")
        user = self._prompt("Username (optional)", "")
        return BackendBuilder.http(address=addr, lock_address=lock, unlock_address=unlock, username=user)


import os  # noqa: E402 — needed for wizard methods
