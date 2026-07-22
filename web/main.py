"""Entry point for the terraai-web binary."""
from __future__ import annotations
import sys
import typer

# Force UTF-8 on Windows so Rich can render unicode to the console.
# Must run before any Rich/typer imports.
if sys.platform == 'win32':
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

app = typer.Typer(add_completion=False)


@app.command()
def main(
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind (use 0.0.0.0 for LAN)"),
    port: int = typer.Option(7820, "--port", help="Port to listen on"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Don't auto-open browser"),
    workspace: str = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
):
    """
    TerraAI Web Dashboard

    Starts the local web UI at http://<host>:<port> and opens it in your browser.

    Examples:

      # Default: localhost:7820, opens browser
      terraai-web

      # Custom port
      terraai-web --port 8080

      # Expose on LAN (e.g. for team)
      terraai-web --host 0.0.0.0 --port 7820 --no-browser

      # Point at a specific workspace
      terraai-web --workspace ~/terraai-workspaces/prod
    """
    from pathlib import Path
    from config import TerraAIConfig
    from web.server import launch

    config = TerraAIConfig.load()
    if workspace:
        config.workspace_dir = str(Path(workspace).expanduser().resolve())

    url = f"http://{host}:{port}"
    typer.echo(f"\n  TerraAI Web UI  ->  {url}\n  Press Ctrl+C to stop.\n")
    launch(config, host=host, port=port, open_browser=not no_browser)


if __name__ == "__main__":
    app()