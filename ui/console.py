from rich.console import Console
from rich.theme import Theme

THEME = Theme({
    "info": "bold cyan",
    "success": "bold green",
    "warning": "bold yellow",
    "error": "bold red",
    "muted": "dim white",
    "hcl": "bold blue",
    "provider.azure": "bold #0078D4",
    "provider.aws": "bold #FF9900",
    "provider.gcp": "bold #4285F4",
    "ai": "bold magenta",
    "action.create": "bold green",
    "action.modify": "bold yellow",
    "action.delete": "bold red",
    "action.read": "bold cyan",
})

console = Console(theme=THEME, highlight=True)
err_console = Console(stderr=True, theme=THEME)
