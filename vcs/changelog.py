from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Optional
import json


CHANGELOG_FILE = "INFRASTRUCTURE.md"
CHRONICLE_FILE = ".terraai/chronicle.json"


class InfrastructureChangelog:
    """
    Maintains a human-readable infrastructure changelog alongside git history.
    This is TerraAI's unique 'Chronicle' — AI-authored explanations of every
    infrastructure change, separate from git commit messages.
    """

    def __init__(self, workspace_dir: str):
        self.root = Path(workspace_dir)
        self._chronicle_path = self.root / CHRONICLE_FILE
        self._chronicle_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_chronicle(self) -> list[dict]:
        if self._chronicle_path.exists():
            try:
                return json.loads(self._chronicle_path.read_text(encoding='utf-8'))
            except Exception:
                pass
        return []

    def _save_chronicle(self, entries: list[dict]) -> None:
        self._chronicle_path.write_text(json.dumps(entries, indent=2), encoding='utf-8')

    def record_change(
        self,
        git_sha: str,
        intent: str,
        summary: str,
        providers: list[str],
        resources: list[dict],
        warnings: list[str],
        user_request: str,
        hcl_file: str = "",
    ) -> None:
        entries = self._load_chronicle()
        entry = {
            "sha": git_sha[:8] if git_sha else "uncommitted",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "intent": intent,
            "summary": summary,
            "providers": providers,
            "resources": [{"name": r.get("name"), "type": r.get("type"), "action": r.get("action")} for r in resources],
            "warnings": warnings,
            "user_request": user_request,
            "hcl_file": hcl_file,
        }
        entries.insert(0, entry)
        self._save_chronicle(entries)
        self._rebuild_markdown(entries)

    def _rebuild_markdown(self, entries: list[dict]) -> None:
        md_path = self.root / CHANGELOG_FILE
        lines = [
            "# Infrastructure Changelog",
            "",
            "> Auto-maintained by [TerraAI](https://github.com/terraai). "
            "Each entry captures what changed, why, and what to watch out for.",
            "",
        ]

        for e in entries:
            ts = e.get("timestamp", "")[:16].replace("T", " ")
            sha = e.get("sha", "")
            intent = e.get("intent", "").upper()
            summary = e.get("summary", "")
            providers = ", ".join(e.get("providers", []))
            resources = e.get("resources", [])
            warnings = e.get("warnings", [])
            user_req = e.get("user_request", "")
            hcl_file = e.get("hcl_file", "")

            intent_icon = {
                "CREATE": "✅", "MODIFY": "✏️", "DELETE": "🗑️",
                "CONFIGURE": "⚙️", "EXPLAIN": "📖",
            }.get(intent, "▶️")

            lines += [
                f"## {intent_icon} `{sha}` — {ts}",
                "",
                f"**{summary}**",
                "",
            ]

            if user_req:
                lines += [f"> 💬 *\"{user_req}\"*", ""]

            if providers:
                lines.append(f"**Providers:** {providers}")

            if hcl_file:
                lines.append(f"**File:** `{hcl_file}`")

            if resources:
                lines += ["", "**Resources:**"]
                for r in resources:
                    action_icon = {"create": "➕", "modify": "✏️", "delete": "➖"}.get(r.get("action", ""), "▸")
                    lines.append(f"- {action_icon} `{r.get('type', '')}`.`{r.get('name', '')}`")

            if warnings:
                lines += ["", "**⚠️ Warnings:**"]
                for w in warnings:
                    lines.append(f"- {w}")

            lines += ["", "---", ""]

        md_path.write_text("\n".join(lines), encoding='utf-8')

    def get_entries(self, limit: int = 20) -> list[dict]:
        return self._load_chronicle()[:limit]

    def get_entry_by_sha(self, sha: str) -> Optional[dict]:
        for e in self._load_chronicle():
            if e.get("sha", "").startswith(sha):
                return e
        return None

    def diff_summary(self, sha1: str, sha2: str) -> str:
        """Return a human-readable diff between two chronicle entries."""
        entries = {e["sha"]: e for e in self._load_chronicle()}
        e1 = entries.get(sha1)
        e2 = entries.get(sha2)
        if not e1 or not e2:
            return "Could not find entries for comparison"

        lines = [f"Infrastructure diff: {sha1} → {sha2}", ""]
        r1_types = {r["type"] for r in e1.get("resources", [])}
        r2_types = {r["type"] for r in e2.get("resources", [])}

        added = r2_types - r1_types
        removed = r1_types - r2_types
        if added:
            lines.append(f"Added resource types: {', '.join(added)}")
        if removed:
            lines.append(f"Removed resource types: {', '.join(removed)}")
        if not added and not removed:
            lines.append("Same resource types — likely configuration changes only")
        return "\n".join(lines)
