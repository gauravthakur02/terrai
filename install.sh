#!/usr/bin/env bash
# TerraAI installer
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv"

echo "🌍 Installing TerraAI..."

# Create venv if not exists
if [ ! -d "$VENV" ]; then
    python3 -m venv "$VENV"
fi

"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$SCRIPT_DIR/requirements.txt"

# Create wrapper script
WRAPPER="$SCRIPT_DIR/terraai"
cat > "$WRAPPER" << EOF
#!/usr/bin/env bash
exec "$VENV/bin/python" "$SCRIPT_DIR/main.py" "\$@"
EOF
chmod +x "$WRAPPER"

echo "✅ TerraAI installed!"
echo ""
echo "Run it:"
echo "  ./terraai                                    # Start interactive session"
echo "  ./terraai models                             # List AI models"
echo "  ./terraai providers                          # List cloud providers"
echo "  ./terraai configure --model gpt-4o           # Set default model"
echo "  ./terraai configure --model ollama/llama3    # Use local Ollama (free)"
echo ""
echo "Quick start with a free model (requires Groq API key at groq.com):"
echo "  export GROQ_API_KEY=your_key"
echo "  ./terraai --model groq/llama3-70b-8192 --provider azure"
echo ""
echo "Or with local Ollama (100% free, no API key):"
echo "  ollama pull codellama"
echo "  ./terraai --model ollama/codellama --api-base http://localhost:11434"
