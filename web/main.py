"""Entry point for the terraai-web binary."""
from __future__ import annotations
import typer

app = typer.Typer(add_completion=False)


@app.command()
def main(
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind (use 0.0.0.0 for LAN)"),
    port: int = typer.Option(7820, "--port", help="Port to listen on"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Don't auto-open browser"),
    workspace: str = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
):
    """
    [bold cyan]🌍 TerraAI Web Dashboard[/bold cyan]

    Starts the local web UI at http://<host>:<port> and opens it in your browser.

    [dim]Examples:[/dim]

      [bold]# Default: localhost:7820, opens browser[/bold]
      terraai-web

      [bold]# Custom port[/bold]
      terraai-web --port 8080

      [bold]# Expose on LAN (e.g. for team)[/bold]
      terraai-web --host 0.0.0.0 --port 7820 --no-browser

      [bold]# Point at a specific workspace[/bold]
      terraai-web --workspace ~/terraai-workspaces/prod
    """
    from pathlib import Path
    from config import TerraAIConfig
    from web.server import launch

    config = TerraAIConfig.load()
    if workspace:
        config.workspace_dir = str(Path(workspace).expanduser().resolve())

    url = f"http://{host}:{port}"
    typer.echo(f"\n  TerraAI Web UI  →  {url}\n  Press Ctrl+C to stop.\n")
    launch(config, host=host, port=port, open_browser=not no_browser)


if __name__ == "__main__":
    app()
