#!/usr/bin/env python3
"""
Packages TerraAI for Windows as a single self-extracting .exe:
  1. Build the onedir payload (terraai-onedir.spec)
  2. Zip it
  3. Build the Go launcher (launcher/)
  4. Concatenate: launcher.exe + payload.zip + [64B version][8B length] footer

Produces: dist/terraai-windows-x64.exe

Usage:  python scripts/package_windows.py
"""
from __future__ import annotations
import datetime
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
OUTPUT = DIST / "terraai-windows-x64.exe"

# Must match the footer layout launcher/main.go's readFooter() expects.
VERSION_FIELD_SIZE = 64
LENGTH_FIELD_SIZE = 8


def sh(args: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def run(args: list[str], cwd: Path = ROOT) -> str:
    result = sh(args, cwd)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise SystemExit(f"command failed: {' '.join(args)}")
    return result.stdout.strip()


def resolve_version() -> str:
    git_dir = sh(["git", "rev-parse", "--git-dir"])
    if git_dir.returncode == 0:
        sha = run(["git", "rev-parse", "--short", "HEAD"])
        dirty = sh(["git", "diff", "--quiet", "HEAD"]).returncode != 0
        version = f"git-{sha}" + ("-dirty" if dirty else "")
    else:
        version = "ts-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")

    encoded = version.encode("utf-8")
    if len(encoded) > VERSION_FIELD_SIZE:
        raise SystemExit(f"version string too long for {VERSION_FIELD_SIZE}-byte footer field: {version!r}")
    return version


def build_onedir_payload() -> Path:
    print("== Building onedir payload (terraai-onedir.spec) ==")
    run([sys.executable, "-m", "PyInstaller", "terraai-onedir.spec", "--noconfirm", "--log-level", "WARN"])
    payload_dir = DIST / "terraai"
    if not payload_dir.is_dir():
        raise SystemExit(f"expected onedir payload at {payload_dir}, not found")
    return payload_dir


def zip_payload(payload_dir: Path) -> Path:
    print("== Zipping payload ==")
    zip_path = DIST / "terraai-payload.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file in payload_dir.rglob("*"):
            if file.is_file():
                zf.write(file, file.relative_to(payload_dir))
    print(f"   {zip_path} ({zip_path.stat().st_size / 1024 / 1024:.1f} MB)")
    return zip_path


def build_launcher() -> Path:
    print("== Building Go launcher ==")
    launcher_dir = ROOT / "launcher"
    out = launcher_dir / "launcher.exe"
    run(["go", "build", "-ldflags", "-s -w", "-o", str(out), "."], cwd=launcher_dir)
    return out


def package(launcher_exe: Path, payload_zip: Path, version: str) -> Path:
    print("== Packaging final exe ==")
    DIST.mkdir(parents=True, exist_ok=True)
    payload_len = payload_zip.stat().st_size

    version_field = version.encode("utf-8").ljust(VERSION_FIELD_SIZE, b"\x00")
    length_field = payload_len.to_bytes(LENGTH_FIELD_SIZE, "big")

    with open(OUTPUT, "wb") as out:
        with open(launcher_exe, "rb") as f:
            shutil.copyfileobj(f, out)
        with open(payload_zip, "rb") as f:
            shutil.copyfileobj(f, out)
        out.write(version_field)
        out.write(length_field)

    print(f"   {OUTPUT} ({OUTPUT.stat().st_size / 1024 / 1024:.1f} MB) version={version}")
    return OUTPUT


def main() -> None:
    version = resolve_version()
    print(f"Packaging version: {version}")
    payload_dir = build_onedir_payload()
    payload_zip = zip_payload(payload_dir)
    launcher_exe = build_launcher()
    output = package(launcher_exe, payload_zip, version)
    print(f"\nDone: {output}")


if __name__ == "__main__":
    main()
