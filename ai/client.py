from __future__ import annotations
import json
import os
from typing import Generator, Optional
import litellm
from litellm import completion
from .prompts import SYSTEM_PROMPT
from config.settings import TerraAIConfig

litellm.suppress_debug_info = True


class AIResponse:
    def __init__(self, raw: dict):
        self.intent: str = raw.get("intent", "create")
        self.providers: list[str] = raw.get("providers", [])
        self.summary: str = raw.get("summary", "")
        self.resources: list[dict] = raw.get("resources", [])
        self.hcl: str = raw.get("hcl", "")
        self.variables: dict = raw.get("variables", {})
        self.outputs: dict = raw.get("outputs", {})
        self.warnings: list[str] = raw.get("warnings", [])
        self.next_steps: list[str] = raw.get("next_steps", [])

    @property
    def has_hcl(self) -> bool:
        return bool(self.hcl and self.hcl.strip())

    @property
    def is_destructive(self) -> bool:
        return any(r.get("action") == "delete" for r in self.resources)


class TerraAIClient:
    def __init__(self, config: TerraAIConfig):
        self.config = config
        self._history: list[dict] = []
        self._setup_env()

    def _setup_env(self) -> None:
        key = self.config.get_api_key()
        if key:
            model = self.config.model
            if model.startswith("claude") or "anthropic" in model:
                os.environ["ANTHROPIC_API_KEY"] = key
            elif model.startswith("gemini"):
                os.environ["GEMINI_API_KEY"] = key
            elif model.startswith("groq"):
                os.environ["GROQ_API_KEY"] = key
            elif "azure" in model:
                os.environ["AZURE_OPENAI_API_KEY"] = key
            else:
                os.environ["OPENAI_API_KEY"] = key

        if self.config.api_base:
            os.environ["OPENAI_API_BASE"] = self.config.api_base

    def reset_history(self) -> None:
        self._history = []

    def ask(self, user_message: str, workspace_context: str = "") -> Generator[str, None, AIResponse]:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        if workspace_context:
            messages.append({
                "role": "user",
                "content": f"[WORKSPACE CONTEXT]\n{workspace_context}\n[END CONTEXT]"
            })
            messages.append({
                "role": "assistant",
                "content": '{"intent": "read", "providers": [], "summary": "Context loaded.", "resources": [], "hcl": "", "variables": {}, "outputs": {}, "warnings": [], "next_steps": []}'
            })

        messages.extend(self._history)
        messages.append({"role": "user", "content": user_message})

        kwargs = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "stream": True,
        }

        if self.config.api_base and self.config.model.startswith("ollama"):
            kwargs["api_base"] = self.config.api_base or "http://localhost:11434"

        full_response = ""
        stream = completion(**kwargs)
        for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            full_response += delta
            yield delta

        self._history.append({"role": "user", "content": user_message})
        self._history.append({"role": "assistant", "content": full_response})

        try:
            cleaned = full_response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
            return AIResponse(json.loads(cleaned))
        except (json.JSONDecodeError, ValueError):
            return AIResponse({
                "intent": "explain",
                "summary": full_response,
                "hcl": "",
                "providers": [],
                "resources": [],
                "warnings": ["Could not parse structured response"],
                "next_steps": [],
            })

    def ask_sync(self, user_message: str, workspace_context: str = "") -> AIResponse:
        """Non-streaming version for simple queries."""
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if workspace_context:
            messages.append({"role": "user", "content": f"[WORKSPACE CONTEXT]\n{workspace_context}"})
            messages.append({"role": "assistant", "content": '{"intent":"read","providers":[],"summary":"Context loaded.","resources":[],"hcl":"","variables":{},"outputs":{},"warnings":[],"next_steps":[]}'})

        messages.extend(self._history)
        messages.append({"role": "user", "content": user_message})

        kwargs = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
        }
        if self.config.api_base:
            kwargs["api_base"] = self.config.api_base

        resp = completion(**kwargs)
        raw = resp.choices[0].message.content.strip()

        self._history.append({"role": "user", "content": user_message})
        self._history.append({"role": "assistant", "content": raw})

        try:
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            return AIResponse(json.loads(raw))
        except (json.JSONDecodeError, ValueError):
            return AIResponse({"intent": "explain", "summary": raw, "hcl": "", "providers": [], "resources": [], "warnings": [], "next_steps": []})
