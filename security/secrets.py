"""Secrets scanner — detect patterns that look like hardcoded credentials in HCL.

Runs as a blocking gate before writing .tf files.  Complements the advisory
SEC006 rule in the security linter, which shows before the save prompt; this
module fires after the user types 'y', requiring explicit confirmation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import NamedTuple


@dataclass(frozen=True)
class SecretMatch:
    name: str     # Human-readable pattern name
    snippet: str  # Redacted value shown to user
    line: int     # 1-based line number in the HCL text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _redact(value: str) -> str:
    """Show first 4 and last 4 chars; mask the middle."""
    if len(value) <= 8:
        return "****"
    mid = min(8, len(value) - 8)
    return f"{value[:4]}{'*' * mid}{value[-4:]}"


def _line_of(hcl: str, pos: int) -> int:
    return hcl[:pos].count("\n") + 1


# Values that look like placeholders, not real secrets
_PLACEHOLDER = re.compile(
    r"changeme|change.me|placeholder|your[_\-]|<[^>]+>"
    r"|example[_\-]?|dummy|fake|test123|pass(word)?123"
    r"|todo|fixme|replace.me|insert.here|secret123",
    re.IGNORECASE,
)

# Variable/data references that are definitely not literals
_VAR_REF = re.compile(r"^\$\{|^var\.|^data\.|^module\.|^local\.")


class _Pat(NamedTuple):
    name: str
    regex: re.Pattern
    group: int = 1   # capture group that holds the secret value


# ---------------------------------------------------------------------------
# Pattern tables
# ---------------------------------------------------------------------------

# High-confidence structural patterns (format is inherently secret-shaped)
_STRUCTURAL: list[_Pat] = [
    _Pat("AWS Access Key ID",
         re.compile(r"\b(AKIA[0-9A-Z]{16})\b")),
    _Pat("GCP API Key",
         re.compile(r"\b(AIza[0-9A-Za-z\-_]{35})\b")),
    _Pat("GitHub Personal Access Token",
         re.compile(r"\b(ghp_[A-Za-z0-9]{36})\b")),
    _Pat("GitHub Fine-Grained Token",
         re.compile(r"\b(github_pat_[A-Za-z0-9_]{82})\b")),
    _Pat("GitLab Personal Access Token",
         re.compile(r"\b(glpat-[A-Za-z0-9\-]{20})\b")),
    _Pat("Slack Bot Token",
         re.compile(r"\b(xoxb-[0-9]{11}-[0-9]{11}-[A-Za-z0-9]{24})\b")),
    _Pat("Slack User/App Token",
         re.compile(r"\b(xox[psa]-[0-9A-Za-z\-]{16,})\b")),
    _Pat("PEM private key",
         re.compile(r"(-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----)", 0),
         group=1),
    _Pat("Azure Storage account key",
         re.compile(r"AccountKey=([A-Za-z0-9+/]{50,}={0,2})")),
    _Pat("Azure SAS signature",
         re.compile(r"(?:sig=)([A-Za-z0-9%+/]{30,})")),
]

# Named-field patterns — field name in HCL makes it clearly credential-shaped
_NAMED: list[_Pat] = [
    _Pat("Hardcoded password",
         re.compile(
             r"\b(?:password|passwd|master_password|admin_password|db_password|rds_password)"
             r'\s*=\s*"([^"${\n]{8,})"',
             re.IGNORECASE,
         )),
    _Pat("Hardcoded API key",
         re.compile(
             r"\b(?:api_key|apikey|api_secret|app_key)"
             r'\s*=\s*"([^"${\n]{16,})"',
             re.IGNORECASE,
         )),
    _Pat("Hardcoded token",
         re.compile(
             r"\b(?:access_token|auth_token|bearer_token|refresh_token|secret_token)"
             r'\s*=\s*"([^"${\n]{16,})"',
             re.IGNORECASE,
         )),
    _Pat("Hardcoded secret / private key",
         re.compile(
             r"\b(?:client_secret|app_secret|secret_key|private_key|access_key_secret)"
             r'\s*=\s*"([^"${\n]{16,})"',
             re.IGNORECASE,
         )),
    _Pat("Hardcoded connection string",
         re.compile(
             r"\b(?:connection_string|conn_string|database_url|db_url)"
             r'\s*=\s*"([^"${\n]{20,})"',
             re.IGNORECASE,
         )),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_secrets(hcl: str) -> list[SecretMatch]:
    """Scan HCL text for patterns that look like hardcoded secrets.

    Returns matches sorted by line number, deduplicated per line.
    """
    matches: list[SecretMatch] = []
    seen_lines: set[int] = set()

    for pat in _STRUCTURAL:
        for m in pat.regex.finditer(hcl):
            value = m.group(pat.group) if m.lastindex and m.lastindex >= pat.group else m.group(0)
            line = _line_of(hcl, m.start())
            if line not in seen_lines:
                seen_lines.add(line)
                matches.append(SecretMatch(pat.name, _redact(value), line))

    for pat in _NAMED:
        for m in pat.regex.finditer(hcl):
            value = m.group(pat.group)
            if _VAR_REF.match(value) or _PLACEHOLDER.search(value):
                continue
            line = _line_of(hcl, m.start())
            if line not in seen_lines:
                seen_lines.add(line)
                matches.append(SecretMatch(pat.name, _redact(value), line))

    return sorted(matches, key=lambda x: x.line)
