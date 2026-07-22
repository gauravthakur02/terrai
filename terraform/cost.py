from __future__ import annotations
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .executor import PLAN_FILE


def is_installed() -> bool:
    """Return True if infracost binary is on PATH."""
    return shutil.which("infracost") is not None


def is_available() -> bool:
    """Return True if infracost is on PATH and INFRACOST_API_KEY is set."""
    return is_installed() and bool(os.environ.get("INFRACOST_API_KEY"))


def estimate(workspace_dir: Path, plan_file: Path | None = None) -> dict | None:
    """
    Estimate monthly cost delta for a terraform plan binary.

    Converts the binary plan to JSON via `terraform show -json`, then runs
    `infracost diff --plan-json`. Returns the parsed infracost JSON dict
    or None on any failure (binary missing, key missing, timeout, etc.).
    The caller should always guard with is_available() before calling this.
    """
    if plan_file is None:
        plan_file = workspace_dir / PLAN_FILE
    if not plan_file.exists():
        return None

    # Step 1: binary plan → JSON (terraform show -json)
    try:
        show = subprocess.run(
            ["terraform", "show", "-json", str(plan_file)],
            capture_output=True,
            text=True,
            cwd=workspace_dir,
            timeout=30,
        )
    except Exception:
        return None

    if show.returncode != 0 or not show.stdout.strip():
        return None

    # Step 2: write temp JSON, run infracost diff
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".json", dir=workspace_dir)
    try:
        with os.fdopen(tmp_fd, "w") as fh:
            fh.write(show.stdout)

        ic = subprocess.run(
            [
                "infracost", "diff",
                "--path", str(workspace_dir),
                "--plan-json", tmp_path,
                "--format", "json",
            ],
            capture_output=True,
            text=True,
            cwd=workspace_dir,
            timeout=60,
        )
        if ic.returncode != 0 or not ic.stdout.strip():
            return None
        return json.loads(ic.stdout)
    except Exception:
        return None
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
