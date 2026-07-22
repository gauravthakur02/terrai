from __future__ import annotations
import subprocess
import re
import json
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Generator


PLAN_FILE = "tfplan"


@dataclass
class TerraformResult:
    success: bool
    stdout: str
    stderr: str
    return_code: int
    plan_stats: dict = field(default_factory=dict)


class TerraformExecutor:
    def __init__(self, workspace_dir: str, terraform_bin: str = "terraform"):
        self.workspace_dir = Path(workspace_dir)
        self.bin = terraform_bin
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    def _run(self, *args, env_extra: dict | None = None) -> TerraformResult:
        env = {**os.environ, **(env_extra or {})}
        try:
            result = subprocess.run(
                [self.bin, *args],
                cwd=self.workspace_dir,
                capture_output=True,
                text=True,
                env=env,
            )
            return TerraformResult(
                success=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                return_code=result.returncode,
            )
        except FileNotFoundError:
            return TerraformResult(
                success=False,
                stdout="",
                stderr=f"Terraform binary '{self.bin}' not found. Install from https://developer.hashicorp.com/terraform/install",
                return_code=127,
            )

    def _stream(self, *args) -> Generator[str, None, TerraformResult]:
        try:
            proc = subprocess.Popen(
                [self.bin, *args],
                cwd=self.workspace_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            full_output = ""
            for line in proc.stdout:
                full_output += line
                yield line
            proc.wait()
            return TerraformResult(
                success=proc.returncode == 0,
                stdout=full_output,
                stderr="",
                return_code=proc.returncode,
            )
        except FileNotFoundError:
            yield "❌ Terraform binary not found.\n"
            return TerraformResult(success=False, stdout="", stderr="not found", return_code=127)

    def is_installed(self) -> bool:
        r = self._run("version")
        return r.success

    def version(self) -> str:
        r = self._run("version", "-json")
        if r.success:
            try:
                data = json.loads(r.stdout)
                return data.get("terraform_version", "unknown")
            except Exception:
                pass
        return "unknown"

    def init(self) -> Generator[str, None, None]:
        yield from self._stream("init", "-no-color")

    def validate(self) -> TerraformResult:
        return self._run("validate", "-no-color")

    def plan(self, out_file: str = "tfplan") -> Generator[str, None, TerraformResult]:
        yield from self._stream("plan", "-no-color", f"-out={out_file}")

    def apply(self, plan_file: str = "tfplan", auto_approve: bool = False) -> Generator[str, None, None]:
        args = ["apply", "-no-color"]
        if auto_approve:
            args.append("-auto-approve")
        args.append(plan_file)
        yield from self._stream(*args)

    def destroy(self, target: str | None = None) -> Generator[str, None, None]:
        args = ["destroy", "-no-color", "-auto-approve"]
        if target:
            args.extend(["-target", target])
        yield from self._stream(*args)

    def show_state(self) -> TerraformResult:
        return self._run("show", "-no-color")

    def list_resources(self) -> list[str]:
        r = self._run("state", "list")
        if r.success:
            return [line.strip() for line in r.stdout.splitlines() if line.strip()]
        return []

    def get_outputs(self) -> dict:
        r = self._run("output", "-json")
        if r.success:
            try:
                return json.loads(r.stdout)
            except Exception:
                pass
        return {}

    def parse_plan_stats(self, plan_output: str) -> dict:
        stats = {"add": 0, "change": 0, "destroy": 0, "add_list": "", "change_list": "", "destroy_list": ""}
        match = re.search(r"Plan: (\d+) to add, (\d+) to change, (\d+) to destroy", plan_output)
        if match:
            stats["add"] = int(match.group(1))
            stats["change"] = int(match.group(2))
            stats["destroy"] = int(match.group(3))

        add_resources, change_resources, destroy_resources = [], [], []
        for line in plan_output.splitlines():
            stripped = line.strip()
            if stripped.startswith("+ ") or stripped.startswith("  + "):
                add_resources.append(stripped.lstrip("+ ").split(" ")[0])
            elif stripped.startswith("~ ") or stripped.startswith("  ~ "):
                change_resources.append(stripped.lstrip("~ ").split(" ")[0])
            elif stripped.startswith("- ") or stripped.startswith("  - "):
                destroy_resources.append(stripped.lstrip("- ").split(" ")[0])

        stats["add_list"] = ", ".join(add_resources[:5])
        stats["change_list"] = ", ".join(change_resources[:5])
        stats["destroy_list"] = ", ".join(destroy_resources[:5])
        return stats
