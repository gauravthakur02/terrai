from __future__ import annotations
import subprocess
import hashlib
import json
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class GitCommit:
    sha: str
    message: str
    author: str
    timestamp: str
    files_changed: list[str] = field(default_factory=list)

    @property
    def short_sha(self) -> str:
        return self.sha[:8]

    @property
    def summary(self) -> str:
        return self.message.splitlines()[0]


class GitManager:
    """Manages git version control for Terraform workspaces."""

    def __init__(self, workspace_dir: str):
        self.root = Path(workspace_dir)
        self._user_name = "TerraAI"
        self._user_email = "terraai@localhost"

    def _run(self, *args, check: bool = False) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=check,
        )

    def is_git_repo(self) -> bool:
        r = self._run("rev-parse", "--git-dir")
        return r.returncode == 0

    def init(self) -> bool:
        if self.is_git_repo():
            return True
        r = self._run("init")
        if r.returncode != 0:
            return False
        self._write_gitignore()
        self._run("config", "user.name", self._user_name)
        self._run("config", "user.email", self._user_email)
        return True

    def _write_gitignore(self) -> None:
        gitignore = self.root / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(
                "# Terraform provider cache & plan artefacts\n"
                ".terraform/\n"
                ".terraform.lock.hcl\n"
                "tfplan\n\n"
                "# Sensitive variable files — never commit secrets\n"
                "*.tfvars\n"
                "*.tfvars.json\n\n"
                "# Terraform state — store in a remote backend instead\n"
                "terraform.tfstate\n"
                "terraform.tfstate.backup\n\n"
                "# Override files (local dev only)\n"
                "override.tf\n"
                "override.tf.json\n"
                "*_override.tf\n"
                "*_override.tf.json\n\n"
                "# TerraAI internal data (chronicle, snapshots, keyring cache)\n"
                ".terraai/\n"
                "*.enc\n\n"
                "# OS metadata\n"
                ".DS_Store\n"
                "Thumbs.db\n"
            )

    def stage_all(self) -> None:
        self._run("add", "-A")

    def commit(self, message: str, author: str = "TerraAI") -> Optional[str]:
        """Commit staged changes. Returns commit SHA or None if nothing to commit."""
        r_status = self._run("status", "--porcelain")
        if not r_status.stdout.strip():
            return None

        self._run("add", "-A")
        r = self._run(
            "commit",
            f"--author={author} <terraai@localhost>",
            "-m", message,
        )
        if r.returncode != 0:
            return None

        sha_r = self._run("rev-parse", "HEAD")
        return sha_r.stdout.strip() if sha_r.returncode == 0 else None

    def get_log(self, limit: int = 20) -> list[GitCommit]:
        r = self._run(
            "log", f"-{limit}",
            "--pretty=format:%H|%s|%an|%ai",
            "--name-only",
        )
        if r.returncode != 0:
            return []

        commits = []
        current: dict = {}
        for line in r.stdout.splitlines():
            if "|" in line and len(line.split("|")) == 4:
                if current:
                    commits.append(GitCommit(**current))
                parts = line.split("|", 3)
                current = {
                    "sha": parts[0],
                    "message": parts[1],
                    "author": parts[2],
                    "timestamp": parts[3],
                    "files_changed": [],
                }
            elif line.strip() and current:
                current["files_changed"].append(line.strip())

        if current:
            commits.append(GitCommit(**current))
        return commits

    def get_diff(self, sha1: str = "HEAD~1", sha2: str = "HEAD") -> str:
        r = self._run("diff", sha1, sha2, "--", "*.tf")
        return r.stdout

    def get_diff_staged(self) -> str:
        r = self._run("diff", "--cached")
        return r.stdout

    def get_file_at(self, sha: str, filename: str) -> Optional[str]:
        r = self._run("show", f"{sha}:{filename}")
        return r.stdout if r.returncode == 0 else None

    def checkout_file(self, sha: str, filename: str) -> bool:
        r = self._run("checkout", sha, "--", filename)
        return r.returncode == 0

    def create_tag(self, tag: str, message: str = "") -> bool:
        args = ["tag", "-a", tag, "-m", message or tag]
        return self._run(*args).returncode == 0

    def list_tags(self) -> list[str]:
        r = self._run("tag", "-l", "--sort=-creatordate")
        return [t.strip() for t in r.stdout.splitlines() if t.strip()]

    def get_current_branch(self) -> str:
        r = self._run("branch", "--show-current")
        return r.stdout.strip() or "main"

    def create_branch(self, name: str) -> bool:
        return self._run("checkout", "-b", name).returncode == 0

    def list_branches(self) -> list[str]:
        r = self._run("branch", "--format=%(refname:short)")
        return [b.strip() for b in r.stdout.splitlines() if b.strip()]

    def switch_branch(self, name: str) -> bool:
        return self._run("checkout", name).returncode == 0

    def stash(self) -> bool:
        return self._run("stash").returncode == 0

    def stash_pop(self) -> bool:
        return self._run("stash", "pop").returncode == 0

    def has_uncommitted_changes(self) -> bool:
        r = self._run("status", "--porcelain")
        return bool(r.stdout.strip())

    def get_status(self) -> list[dict]:
        r = self._run("status", "--porcelain=v1")
        results = []
        for line in r.stdout.splitlines():
            if len(line) >= 4:
                xy = line[:2]
                path = line[3:].strip()
                status_map = {
                    "M": "modified", "A": "added", "D": "deleted",
                    "R": "renamed", "C": "copied", "?": "untracked",
                }
                results.append({
                    "status": status_map.get(xy.strip()[0], xy.strip()),
                    "path": path,
                })
        return results

    def build_commit_message(self, ai_summary: str, intent: str, providers: list[str], resources: list[dict]) -> str:
        """Build a conventional-commits style message from AI response data."""
        type_map = {
            "create": "feat",
            "modify": "fix",
            "delete": "refactor",
            "configure": "chore",
            "explain": "docs",
        }
        commit_type = type_map.get(intent, "feat")
        provider_scope = providers[0] if providers else "infra"

        resource_names = [r.get("type", "") for r in resources[:3] if r.get("type")]
        scope_detail = ", ".join(resource_names[:2]) if resource_names else provider_scope

        first_line = f"{commit_type}({provider_scope}): {ai_summary[:72]}"

        body_lines = []
        if resources:
            actions = {}
            for r in resources:
                action = r.get("action", "create")
                actions.setdefault(action, []).append(r.get("type", r.get("name", "")))
            for action, types in actions.items():
                body_lines.append(f"  {action}: {', '.join(types[:5])}")

        body = "\n".join(body_lines)
        footer = f"Generated-By: TerraAI\nTimestamp: {datetime.utcnow().isoformat()}Z"

        parts = [first_line]
        if body:
            parts.extend(["", body])
        parts.extend(["", footer])
        return "\n".join(parts)
