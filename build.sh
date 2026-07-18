#!/usr/bin/env bash
# TerraAI — macOS / Linux build script
# Produces: dist/terraai  (single binary, no Python install needed)
#
# Usage:
#   ./build.sh              # build for current platform
#   ./build.sh --clean      # remove dist/ and build/ first
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "🌍 TerraAI — Build Script"
echo "Platform: $(uname -s) $(uname -m)"
echo

# ── Clean ──────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--clean" ]]; then
    echo "Cleaning dist/ and build/ ..."
    rm -rf dist build
    echo
fi

# ── Virtual env ────────────────────────────────────────────────────────
if [[ ! -d ".venv" ]]; then
    echo "Creating virtual environment ..."
    python3 -m venv .venv
fi
source .venv/bin/activate

# ── Dependencies ───────────────────────────────────────────────────────
echo "Installing dependencies ..."
pip install -q --upgrade pip
pip install -q -r requirements.txt
pip install -q pyinstaller

# ── Build ──────────────────────────────────────────────────────────────
echo
echo "Building executable ..."
pyinstaller terraai.spec \
    --noconfirm \
    --log-level WARN

# ── Result ─────────────────────────────────────────────────────────────
BINARY="dist/terraai"
if [[ ! -f "$BINARY" ]]; then
    echo "❌ Build failed — dist/terraai not found"
    exit 1
fi

SIZE=$(du -sh "$BINARY" | cut -f1)
echo
echo "✅ Build complete!"
echo "   Binary : $BINARY"
echo "   Size   : $SIZE"
echo
echo "Test it:"
echo "   $BINARY --help"
echo "   $BINARY models"
