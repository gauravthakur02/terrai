from __future__ import annotations
import os
import yaml
from pathlib import Path
from pydantic import BaseModel
from typing import Optional

CONFIG_PATH = Path.home() / ".terraai" / "config.yaml"

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
    workspace_dir: str = str(Path.cwd())
    default_provider: str = "azure"
    auto_approve: bool = False
    show_raw_hcl: bool = True
    terraform_bin: str = "terraform"
    temperature: float = 0.1

    @classmethod
    def load(cls) -> "TerraAIConfig":
        if CONFIG_PATH.exists():
            data = yaml.safe_load(CONFIG_PATH.read_text()) or {}
            return cls(**{k: v for k, v in data.items() if v is not None})
        return cls()

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(yaml.dump(self.model_dump(exclude_none=True), default_flow_style=False))

    def get_api_key(self) -> Optional[str]:
        if self.api_key:
            return self.api_key
        env_map = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "google": "GOOGLE_API_KEY",
            "groq": "GROQ_API_KEY",
            "azure_openai": "AZURE_OPENAI_API_KEY",
            "cohere": "COHERE_API_KEY",
            "mistral": "MISTRAL_API_KEY",
        }
        provider_info = MODEL_PRESETS.get(self.model, {})
        provider = provider_info.get("provider", "openai")
        return os.environ.get(env_map.get(provider, "OPENAI_API_KEY"))
