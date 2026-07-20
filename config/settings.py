from __future__ import annotations
import os
import stat
import yaml
from pathlib import Path
from pydantic import BaseModel
from typing import Optional

CONFIG_PATH = Path.home() / ".terraai" / "config.yaml"

# Keyring — secure OS-level credential storage (macOS Keychain, Windows Credential
# Manager, GNOME/KDE wallet). Falls back to chmod-600 config.yaml if unavailable.
KEYRING_SERVICE = "terraai"
try:
    import keyring as _keyring
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False

SUPPORTED_PROVIDERS = {
    "azure": "hashicorp/azurerm",
    "aws": "hashicorp/aws",
    "gcp": "hashicorp/google",
    "kubernetes": "hashicorp/kubernetes",
    "helm": "hashicorp/helm",
    "vmware": "hashicorp/vsphere",
}

PROVIDER_VERSIONS = {
    "azure": "~> 3.0",
    "aws": "~> 5.0",
    "gcp": "~> 5.0",
    "kubernetes": "~> 2.0",
    "helm": "~> 2.0",
    "vmware": "~> 2.0",
}

MODEL_PRESETS = {
    "gpt-4o": {"provider": "openai", "free": False},
    "gpt-4o-mini": {"provider": "openai", "free": False},
    "gpt-3.5-turbo": {"provider": "openai", "free": False},
    "claude-sonnet-4-6": {"provider": "anthropic", "free": False},
    "claude-haiku-4-5-20251001": {"provider": "anthropic", "free": False},
    "gemini/gemini-2.0-flash": {"provider": "google", "free": True},
    "gemini/gemini-2.5-pro": {"provider": "google", "free": True},
    "gemini/gemini-1.5-pro": {"provider": "google", "free": True},
    "gemini/gemini-1.5-flash": {"provider": "google", "free": True},
    "groq/llama3-70b-8192": {"provider": "groq", "free": True},
    "groq/mixtral-8x7b-32768": {"provider": "groq", "free": True},
    "ollama/llama3": {"provider": "ollama", "free": True},
    "ollama/mistral": {"provider": "ollama", "free": True},
    "ollama/codellama": {"provider": "ollama", "free": True},
    "azure/gpt-4o": {"provider": "azure_openai", "free": False},
}


class TerraAIConfig(BaseModel):
    model: str = "gpt-4o-mini"
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    workspace_dir: Optional[str] = None   # None = not yet set; resolved at session start
    default_provider: str = "azure"
    auto_approve: bool = False
    show_raw_hcl: bool = True
    terraform_bin: str = "terraform"
    temperature: float = 0.1
    setup_complete: bool = False          # True after first-run wizard completes

    # Azure credentials (stored here when not using keyring / env vars)
    azure_subscription_id: Optional[str] = None
    azure_tenant_id: Optional[str] = None
    azure_client_id: Optional[str] = None
    azure_use_cli_auth: bool = False      # az login — no client secret needed
    azure_use_msi: bool = False           # Managed Identity (Azure VM/AKS)

    @classmethod
    def load(cls) -> "TerraAIConfig":
        if CONFIG_PATH.exists():
            data = yaml.safe_load(CONFIG_PATH.read_text(encoding='utf-8')) or {}
            return cls(**{k: v for k, v in data.items() if v is not None})
        return cls()

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(yaml.dump(self.model_dump(exclude_none=True), default_flow_style=False), encoding='utf-8')
        # Restrict permissions so only the owner can read the config file
        try:
            CONFIG_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    # ── API key helpers ───────────────────────────────────────────────────

    def save_api_key_secure(self, key: str, provider: str) -> bool:
        """Store API key in OS keyring if available, else config.yaml."""
        if KEYRING_AVAILABLE:
            try:
                _keyring.set_password(KEYRING_SERVICE, f"api_key_{provider}", key)
                return True
            except Exception:
                pass
        # Fallback: store in config (file is chmod 600)
        self.api_key = key
        self.save()
        return False  # stored in file, not keyring

    def get_api_key_for_provider(self, provider: str) -> Optional[str]:
        """Look up API key: config.api_key → keyring → env var."""
        if self.api_key:
            return self.api_key
        if KEYRING_AVAILABLE:
            try:
                stored = _keyring.get_password(KEYRING_SERVICE, f"api_key_{provider}")
                if stored:
                    return stored
            except Exception:
                pass
        env_map = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "google": "GEMINI_API_KEY",
            "groq": "GROQ_API_KEY",
            "azure_openai": "AZURE_OPENAI_API_KEY",
            "cohere": "COHERE_API_KEY",
            "mistral": "MISTRAL_API_KEY",
        }
        return os.environ.get(env_map.get(provider, "OPENAI_API_KEY"))

    def get_api_key(self) -> Optional[str]:
        provider_info = MODEL_PRESETS.get(self.model, {})
        provider = provider_info.get("provider", "openai")
        return self.get_api_key_for_provider(provider)

    # ── Azure credential helpers ──────────────────────────────────────────

    def save_azure_secret_secure(self, client_secret: str) -> bool:
        """Store ARM_CLIENT_SECRET in keyring or env."""
        if KEYRING_AVAILABLE:
            try:
                _keyring.set_password(KEYRING_SERVICE, "azure_client_secret", client_secret)
                return True
            except Exception:
                pass
        os.environ["ARM_CLIENT_SECRET"] = client_secret
        return False

    def get_azure_client_secret(self) -> Optional[str]:
        if KEYRING_AVAILABLE:
            try:
                stored = _keyring.get_password(KEYRING_SERVICE, "azure_client_secret")
                if stored:
                    return stored
            except Exception:
                pass
        return os.environ.get("ARM_CLIENT_SECRET")

    def apply_azure_env(self) -> None:
        """Export Azure credentials into the process environment for Terraform."""
        if self.azure_subscription_id:
            os.environ.setdefault("ARM_SUBSCRIPTION_ID", self.azure_subscription_id)
        if self.azure_tenant_id:
            os.environ.setdefault("ARM_TENANT_ID", self.azure_tenant_id)
        if self.azure_client_id:
            os.environ.setdefault("ARM_CLIENT_ID", self.azure_client_id)
        if self.azure_use_cli_auth:
            os.environ.setdefault("ARM_USE_CLI", "true")
        if self.azure_use_msi:
            os.environ.setdefault("ARM_USE_MSI", "true")
        secret = self.get_azure_client_secret()
        if secret:
            os.environ.setdefault("ARM_CLIENT_SECRET", secret)

    def is_azure_configured(self) -> bool:
        """Return True if enough Azure creds exist to attempt terraform."""
        if self.azure_use_msi or self.azure_use_cli_auth:
            return bool(self.azure_subscription_id or os.environ.get("ARM_SUBSCRIPTION_ID"))
        return bool(
            (self.azure_subscription_id or os.environ.get("ARM_SUBSCRIPTION_ID"))
            and (self.azure_client_id or os.environ.get("ARM_CLIENT_ID"))
            and (self.get_azure_client_secret() or os.environ.get("ARM_CLIENT_SECRET"))
        )
