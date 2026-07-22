"""Security linter for generated Terraform HCL.

Scans generated HCL for common misconfigurations before the user saves.
Rules are pure-regex — no network calls, no extra dependencies.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    severity: str  # HIGH | MEDIUM | LOW
    code: str
    message: str


# ---------------------------------------------------------------------------
# Block extractor
# ---------------------------------------------------------------------------

def _resource_blocks(hcl: str):
    """Yield (resource_type, block_text) for each top-level resource block."""
    header_re = re.compile(r'resource\s+"([^"]+)"\s+"[^"]+"\s*\{')
    for m in header_re.finditer(hcl):
        depth = 0
        start = m.end() - 1
        for i in range(start, len(hcl)):
            if hcl[i] == '{':
                depth += 1
            elif hcl[i] == '}':
                depth -= 1
                if depth == 0:
                    yield m.group(1), hcl[start:i + 1]
                    break


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def _check_encryption(hcl: str) -> list[Finding]:
    findings: list[Finding] = []
    patterns = [
        (r'\bencrypted\s*=\s*false\b',
         "Encryption explicitly disabled (`encrypted = false`)"),
        (r'\bstorage_encrypted\s*=\s*false\b',
         "RDS/DB storage encryption disabled (`storage_encrypted = false`)"),
        (r'\benable_disk_encryption\s*=\s*false\b',
         "Disk encryption disabled (`enable_disk_encryption = false`)"),
    ]
    for pattern, msg in patterns:
        if re.search(pattern, hcl):
            findings.append(Finding("HIGH", "SEC001", msg))
    return findings


_OPEN_CIDR = re.compile(
    r'"0\.0\.0\.0/0"'
    r'|source_address_prefix\s*=\s*"[*]"'
    r'|cidr\s*=\s*"0\.0\.0\.0/0"'
)
_PORT_22   = re.compile(r'\b(from_port|to_port|destination_port_range)\s*=\s*"?22"?\b')
_PORT_3389 = re.compile(r'\b(from_port|to_port|destination_port_range)\s*=\s*"?3389"?\b')
_ALL_PORTS = re.compile(
    r'\bfrom_port\s*=\s*"?0"?\b.*\bto_port\s*=\s*"?0"?\b'
    r'|\bdestination_port_range\s*=\s*"\*"',
    re.DOTALL,
)
_INGRESS = re.compile(
    r'\btype\s*=\s*"ingress"\b'
    r'|\bdirection\s*=\s*"Inbound"\b'
    r'|\bingress\s*\{'
)


def _check_open_ports(hcl: str) -> list[Finding]:
    findings: list[Finding] = []
    for _rtype, block in _resource_blocks(hcl):
        if not _OPEN_CIDR.search(block):
            continue
        if _PORT_22.search(block):
            findings.append(Finding("HIGH", "SEC002",
                "SSH (port 22) is open to the internet (0.0.0.0/0)"))
        if _PORT_3389.search(block):
            findings.append(Finding("HIGH", "SEC002",
                "RDP (port 3389) is open to the internet (0.0.0.0/0)"))
        if _ALL_PORTS.search(block):
            findings.append(Finding("HIGH", "SEC002",
                "All ports (0–65535) are open to the internet (0.0.0.0/0)"))
        elif _INGRESS.search(block):
            findings.append(Finding("MEDIUM", "SEC003",
                "Ingress rule allows unrestricted traffic from the internet (0.0.0.0/0)"))
    return findings


def _check_public_storage(hcl: str) -> list[Finding]:
    checks = [
        (r'\bacl\s*=\s*"public-read(-write)?"',
         "HIGH",   "SEC004", "S3 bucket has a public-read ACL — any internet user can access objects"),
        (r'\bpredefined_acl\s*=\s*"(publicRead|publicReadWrite)"',
         "HIGH",   "SEC004", "GCS bucket has a public ACL — any internet user can access objects"),
        (r'\ballow_blob_public_access\s*=\s*true\b',
         "MEDIUM", "SEC005", "Azure Storage account allows public blob access (`allow_blob_public_access = true`)"),
        (r'\bblock_public_acls\s*=\s*false\b',
         "MEDIUM", "SEC005", "S3 public ACL blocking disabled (`block_public_acls = false`)"),
        (r'\bblock_public_policy\s*=\s*false\b',
         "MEDIUM", "SEC005", "S3 public policy blocking disabled (`block_public_policy = false`)"),
        (r'\brestrict_public_buckets\s*=\s*false\b',
         "MEDIUM", "SEC005", "S3 `restrict_public_buckets` is disabled"),
        (r'\buniform_bucket_level_access\s*=\s*false\b',
         "LOW",    "SEC005", "GCS uniform bucket-level access is disabled"),
        (r'\bignore_public_acls\s*=\s*false\b',
         "LOW",    "SEC005", "S3 `ignore_public_acls` is disabled"),
    ]
    return [
        Finding(sev, code, msg)
        for pattern, sev, code, msg in checks
        if re.search(pattern, hcl)
    ]


_SECRET_FIELD = re.compile(
    r'\b(password|master_password|admin_password|secret_key|access_key|private_key|secret)\s*=\s*"([^"${\n][^"\n]{2,})"',
    re.IGNORECASE,
)


def _check_plaintext_secrets(hcl: str) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[str] = set()
    for m in _SECRET_FIELD.finditer(hcl):
        field = m.group(1).lower()
        if field not in seen:
            seen.add(field)
            findings.append(Finding("HIGH", "SEC006",
                f"Potential hardcoded secret in `{m.group(1)}` — use a variable or secrets manager"))
    return findings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def lint(hcl: str) -> list[Finding]:
    """Run all rules against HCL text. Returns deduplicated findings, HIGH first."""
    raw: list[Finding] = []
    for fn in (_check_encryption, _check_open_ports, _check_public_storage, _check_plaintext_secrets):
        raw.extend(fn(hcl))

    seen: set[tuple[str, str]] = set()
    unique: list[Finding] = []
    for f in raw:
        key = (f.code, f.message)
        if key not in seen:
            seen.add(key)
            unique.append(f)

    return sorted(unique, key=lambda f: _SEVERITY_ORDER.get(f.severity, 9))
