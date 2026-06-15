from __future__ import annotations
import json
from pathlib import Path
from typing import Optional


class WorkspaceManager:
    def __init__(self, workspace_dir: str):
        self.root = Path(workspace_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def get_tf_files(self) -> list[Path]:
        return sorted(self.root.glob("*.tf"))

    def get_context(self) -> str:
        """Build context string from existing .tf files and state for AI."""
        parts = []
        tf_files = self.get_tf_files()
        if tf_files:
            parts.append("## Existing Terraform Files")
            for f in tf_files:
                parts.append(f"\n### {f.name}\n```hcl\n{f.read_text()}\n```")
        else:
            parts.append("## Existing Terraform Files\nNo .tf files found in workspace.")

        state_file = self.root / "terraform.tfstate"
        if state_file.exists():
            try:
                state = json.loads(state_file.read_text())
                resources = state.get("resources", [])
                if resources:
                    parts.append(f"\n## Current State ({len(resources)} resources)")
                    for r in resources[:20]:
                        parts.append(f"- {r.get('type')}.{r.get('name')} ({r.get('provider', 'unknown')})")
                    if len(resources) > 20:
                        parts.append(f"... and {len(resources) - 20} more")
            except Exception:
                pass

        return "\n".join(parts)

    def write_hcl(self, filename: str, content: str) -> Path:
        if not filename.endswith(".tf"):
            filename += ".tf"
        path = self.root / filename
        path.write_text(content)
        return path

    def read_hcl(self, filename: str) -> Optional[str]:
        path = self.root / filename
        return path.read_text() if path.exists() else None

    def delete_hcl(self, filename: str) -> bool:
        path = self.root / filename
        if path.exists():
            path.unlink()
            return True
        return False

    def list_files(self) -> list[dict]:
        result = []
        for f in self.get_tf_files():
            result.append({
                "name": f.name,
                "size": f.stat().st_size,
                "lines": len(f.read_text().splitlines()),
            })
        return result

    def has_provider_block(self, provider: str) -> bool:
        for f in self.get_tf_files():
            if provider in f.read_text():
                return True
        return False

    def suggest_filename(self, intent: str, providers: list[str], resources: list[dict]) -> str:
        if intent == "configure" or not resources:
            return "main.tf"
        first_resource = resources[0] if resources else {}
        rtype = first_resource.get("type", "")
        if "resource_group" in rtype:
            return "resource_group.tf"
        if "network" in rtype or "vnet" in rtype or "subnet" in rtype:
            return "networking.tf"
        if "vm" in rtype or "virtual_machine" in rtype:
            return "compute.tf"
        if "storage" in rtype or "blob" in rtype:
            return "storage.tf"
        if "sql" in rtype or "database" in rtype or "cosmos" in rtype:
            return "database.tf"
        if "aks" in rtype or "kubernetes" in rtype:
            return "kubernetes.tf"
        if "key_vault" in rtype:
            return "keyvault.tf"
        if "app_service" in rtype or "function" in rtype:
            return "appservice.tf"
        if providers:
            return f"{providers[0]}_resources.tf"
        return "main.tf"
