from __future__ import annotations
import json
import hashlib
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class DriftReport:
    has_drift: bool
    drifted_resources: list[dict] = field(default_factory=list)
    missing_resources: list[dict] = field(default_factory=list)
    extra_resources: list[dict] = field(default_factory=list)
    last_known_sha: str = ""
    current_sha: str = ""
    detected_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    @property
    def total_issues(self) -> int:
        return len(self.drifted_resources) + len(self.missing_resources) + len(self.extra_resources)


class DriftDetector:
    """
    Detects drift between committed Terraform state and live infrastructure.
    Compares state file snapshots stored in .terraai/snapshots/ against
    the current terraform.tfstate to surface out-of-band manual changes.
    """

    SNAPSHOT_DIR = ".terraai/snapshots"

    def __init__(self, workspace_dir: str):
        self.root = Path(workspace_dir)
        self.snapshot_dir = self.root / self.SNAPSHOT_DIR
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

    def snapshot_state(self, git_sha: str) -> Optional[str]:
        """Store a snapshot of current tfstate keyed by git SHA."""
        state_file = self.root / "terraform.tfstate"
        if not state_file.exists():
            return None

        content = state_file.read_text(encoding='utf-8')
        snap_path = self.snapshot_dir / f"{git_sha[:8]}.json"
        snap_path.write_text(content, encoding='utf-8')

        checksum = hashlib.sha256(content.encode()).hexdigest()
        meta_path = self.snapshot_dir / f"{git_sha[:8]}.meta"
        meta_path.write_text(json.dumps({
            "sha": git_sha,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "checksum": checksum,
        }))
        return checksum

    def detect_drift(self, baseline_sha: str) -> DriftReport:
        """Compare current state against a baseline snapshot."""
        current_state = self._read_current_state()
        baseline_state = self._read_snapshot(baseline_sha)

        if not current_state and not baseline_state:
            return DriftReport(has_drift=False, last_known_sha=baseline_sha)

        if not baseline_state:
            return DriftReport(has_drift=False, last_known_sha=baseline_sha)

        baseline_resources = self._index_resources(baseline_state)
        current_resources = self._index_resources(current_state) if current_state else {}

        drifted, missing, extra = [], [], []

        for key, base_res in baseline_resources.items():
            if key not in current_resources:
                missing.append({"key": key, "type": base_res.get("type"), "name": base_res.get("name")})
            else:
                curr_attrs = current_resources[key].get("instances", [{}])[0].get("attributes", {})
                base_attrs = base_res.get("instances", [{}])[0].get("attributes", {})
                changed_keys = [
                    k for k in set(list(curr_attrs.keys()) + list(base_attrs.keys()))
                    if curr_attrs.get(k) != base_attrs.get(k)
                    and k not in ("timeouts", "id", "tags_all")
                ]
                if changed_keys:
                    drifted.append({
                        "key": key,
                        "type": base_res.get("type"),
                        "name": base_res.get("name"),
                        "changed_attributes": changed_keys[:10],
                    })

        for key in current_resources:
            if key not in baseline_resources:
                r = current_resources[key]
                extra.append({"key": key, "type": r.get("type"), "name": r.get("name")})

        has_drift = bool(drifted or missing or extra)
        return DriftReport(
            has_drift=has_drift,
            drifted_resources=drifted,
            missing_resources=missing,
            extra_resources=extra,
            last_known_sha=baseline_sha,
        )

    def list_snapshots(self) -> list[dict]:
        snapshots = []
        for f in sorted(self.snapshot_dir.glob("*.meta"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                meta = json.loads(f.read_text(encoding='utf-8'))
                snapshots.append(meta)
            except Exception:
                pass
        return snapshots

    def _read_current_state(self) -> Optional[dict]:
        state_file = self.root / "terraform.tfstate"
        if not state_file.exists():
            return None
        try:
            return json.loads(state_file.read_text(encoding='utf-8'))
        except Exception:
            return None

    def _read_snapshot(self, sha: str) -> Optional[dict]:
        snap = self.snapshot_dir / f"{sha[:8]}.json"
        if not snap.exists():
            return None
        try:
            return json.loads(snap.read_text(encoding='utf-8'))
        except Exception:
            return None

    def _index_resources(self, state: dict) -> dict[str, dict]:
        index = {}
        for resource in state.get("resources", []):
            key = f"{resource.get('type')}.{resource.get('name')}"
            index[key] = resource
        return index
