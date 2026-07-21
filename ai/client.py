from __future__ import annotations
import json
import os
import re
import time
from typing import Generator, Optional
import litellm
from litellm import completion
from litellm.exceptions import RateLimitError, ServiceUnavailableError
from .prompts import build_system_prompt
from config.settings import TerraAIConfig

litellm.suppress_debug_info = True

# Gemini model aliases that must be resolved to a stable v1beta path litellm
# can construct correctly.  Keys are the short names users/configs may specify;
# values are the exact model-ID strings that resolve correctly via litellm's
# Google AI Studio route.
_GEMINI_ALIAS_MAP: dict[str, str] = {
    # Deprecated model paths → working equivalents
    "gemini/gemini-2.5-flash":     "gemini/gemini-3.1-flash-lite",
    "gemini/gemini-2.5-pro":       "gemini/gemini-pro-latest",
    "gemini/gemini-2.5-flash-8b":  "gemini/gemini-3.1-flash-lite",
    "gemini/gemini-flash-latest":  "gemini/gemini-3.1-flash-lite",
    "gemini/gemini-2.0-flash":     "gemini/gemini-3.1-flash-lite",
    "gemini/gemini-2.0-flash-lite":"gemini/gemini-3.1-flash-lite",
}


class AIResponse:
    def __init__(self, raw: dict):
        self.intent: str = raw.get("intent", "create")
        self.providers: list[str] = raw.get("providers", [])
        self.summary: str = raw.get("summary", "")
        self.resources: list[dict] = raw.get("resources", [])
        self.hcl: str = raw.get("hcl", "")
        self.files: list[dict] = self._parse_files(raw.get("files", []))
        self.variables: dict = raw.get("variables", {})
        self.outputs: dict = raw.get("outputs", {})
        self.warnings: list[str] = raw.get("warnings", [])
        self.next_steps: list[str] = raw.get("next_steps", [])

    @staticmethod
    def _parse_files(raw_files: object) -> list[dict]:
        """Keep only well-formed {"path": str, "content": str} entries —
        module mode asks weaker models for a nested files[] array on top of
        the JSON they already sometimes get wrong, so a malformed entry here
        (missing key, wrong type) should be dropped rather than crash the app."""
        if not isinstance(raw_files, list):
            return []
        out = []
        for f in raw_files:
            if not isinstance(f, dict):
                continue
            path, content = f.get("path"), f.get("content")
            if isinstance(path, str) and path.strip() and isinstance(content, str):
                out.append({"path": path.strip(), "content": content})
        return out

    @property
    def has_hcl(self) -> bool:
        return bool(self.hcl and self.hcl.strip())

    @property
    def has_files(self) -> bool:
        return bool(self.files)

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

    def _resolve_model(self) -> str:
        """Return the effective litellm model string, resolving deprecated aliases."""
        return _GEMINI_ALIAS_MAP.get(self.config.model, self.config.model)

    @staticmethod
    def _completion_with_retry(max_attempts: int = 4, **kwargs) -> object:
        """Call litellm.completion with exponential back-off on 429/503."""
        delay = 5.0
        for attempt in range(1, max_attempts + 1):
            try:
                return completion(**kwargs)
            except (RateLimitError, ServiceUnavailableError) as exc:
                if attempt == max_attempts:
                    raise
                wait = delay * (2 ** (attempt - 1))
                print(f"\n[TerraAI] Rate-limited / service busy — retrying in {int(wait)}s "
                      f"(attempt {attempt}/{max_attempts})…")
                time.sleep(wait)

    def reset_history(self) -> None:
        self._history = []

    @staticmethod
    def _fix_newlines(s: str) -> str:
        """Escape literal newlines/tabs inside JSON string values."""
        result, in_string = [], False
        i = 0
        while i < len(s):
            c = s[i]
            if c == '\\' and in_string:          # already-escaped char — keep as-is
                result.append(c)
                i += 1
                if i < len(s):
                    result.append(s[i])
                    i += 1
                continue
            if c == '"':
                in_string = not in_string
            elif in_string and c == '\n':
                result.append('\\n'); i += 1; continue
            elif in_string and c == '\r':
                result.append('\\r'); i += 1; continue
            elif in_string and c == '\t':
                result.append('\\t'); i += 1; continue
            result.append(c)
            i += 1
        return ''.join(result)

    @staticmethod
    def _parse_json(text: str) -> dict:
        """Extract and parse the first JSON object from model output."""
        text = text.strip()
        # Strip markdown fences
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        for candidate in [
            text,
            TerraAIClient._fix_newlines(text),
        ]:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        # Find the outermost {...} block (handles prose wrapping JSON)
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            for candidate in [
                match.group(),
                TerraAIClient._fix_newlines(match.group()),
            ]:
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    pass
        return {}

    @staticmethod
    def _fallback(raw: str) -> AIResponse:
        return AIResponse({
            "intent": "explain",
            "summary": raw,
            "hcl": "",
            "providers": [],
            "resources": [],
            "warnings": ["Model did not return valid JSON — try /model to switch to a stronger model (e.g. claude-sonnet-4-6 or gpt-4o)"],
            "next_steps": ["/model"],
        })

    def ask(self, user_message: str, workspace_context: str = "") -> Generator[str, None, AIResponse]:
        messages = [{"role": "system", "content": build_system_prompt(self.config.structure_mode)}]

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

        model = self._resolve_model()
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": self.config.temperature,
            "stream": True,
        }

        if self.config.model.startswith("ollama"):
            kwargs["api_base"] = self.config.api_base or "http://localhost:11434"
            # Disable thinking-mode for Qwen3 and future models that support it;
            # ollama ignores unknown options so this is safe for all ollama models.
            kwargs["extra_body"] = {"think": False}

        key = self.config.get_api_key()
        if key:
            kwargs["api_key"] = key

        full_response = ""
        stream = self._completion_with_retry(**kwargs)
        for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            full_response += delta
            yield delta

        self._history.append({"role": "user", "content": user_message})
        self._history.append({"role": "assistant", "content": full_response})

        parsed = self._parse_json(full_response)
        if parsed:
            return AIResponse(parsed)
        return self._fallback(full_response)

    def ask_sync(self, user_message: str, workspace_context: str = "") -> AIResponse:
        """Non-streaming version for simple queries."""
        messages = [{"role": "system", "content": build_system_prompt(self.config.structure_mode)}]
        if workspace_context:
            messages.append({"role": "user", "content": f"[WORKSPACE CONTEXT]\n{workspace_context}"})
            messages.append({"role": "assistant", "content": '{"intent":"read","providers":[],"summary":"Context loaded.","resources":[],"hcl":"","variables":{},"outputs":{},"warnings":[],"next_steps":[]}'})

        messages.extend(self._history)
        messages.append({"role": "user", "content": user_message})

        model = self._resolve_model()
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": self.config.temperature,
        }
        if self.config.model.startswith("ollama"):
            kwargs["api_base"] = self.config.api_base or "http://localhost:11434"
            kwargs["extra_body"] = {"think": False}
        elif self.config.api_base:
            kwargs["api_base"] = self.config.api_base

        key = self.config.get_api_key()
        if key:
            kwargs["api_key"] = key

        resp = self._completion_with_retry(**kwargs)
        raw = resp.choices[0].message.content.strip()

        self._history.append({"role": "user", "content": user_message})
        self._history.append({"role": "assistant", "content": raw})

        parsed = self._parse_json(raw)
        if parsed:
            return AIResponse(parsed)
        return self._fallback(raw)
