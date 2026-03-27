"""
Banner display for Atulya API startup.

Shows the logo and tagline with gradient colors.
"""

from .utils import mask_network_location

# Gradient colors: #0074d9 -> #009296
GRADIENT_START = (0, 116, 217)  # #0074d9
GRADIENT_END = (0, 146, 150)  # #009296
RED = (239, 68, 68)  # #ef4444

# ATULYA wordmark in block style (single-color red)
LOGO = """\
 █████╗ ████████╗██╗   ██╗██╗     ██╗   ██╗ █████╗
██╔══██╗╚══██╔══╝██║   ██║██║     ╚██╗ ██╔╝██╔══██╗
███████║   ██║   ██║   ██║██║      ╚████╔╝ ███████║
██╔══██║   ██║   ██║   ██║██║       ╚██╔╝  ██╔══██║
██║  ██║   ██║   ╚██████╔╝███████╗   ██║   ██║  ██║
╚═╝  ╚═╝   ╚═╝    ╚═════╝ ╚══════╝   ╚═╝   ╚═╝  ╚═╝"""


def _interpolate_color(start: tuple, end: tuple, t: float) -> tuple:
    """Interpolate between two RGB colors."""
    return (
        int(start[0] + (end[0] - start[0]) * t),
        int(start[1] + (end[1] - start[1]) * t),
        int(start[2] + (end[2] - start[2]) * t),
    )


def gradient_text(text: str, start: tuple = GRADIENT_START, end: tuple = GRADIENT_END) -> str:
    """Render text with a gradient color effect."""
    result = []
    length = len(text)
    for i, char in enumerate(text):
        if char == " ":
            result.append(" ")
        else:
            t = i / max(length - 1, 1)
            r, g, b = _interpolate_color(start, end, t)
            result.append(f"\033[38;2;{r};{g};{b}m{char}")
    result.append("\033[0m")
    return "".join(result)


def print_banner():
    """Print the Atulya startup banner."""
    print(red(LOGO))
    tagline = gradient_text("A living algorithm for machine intelligence (MI)")
    print(f"\n  {tagline}\n")


def color(text: str, t: float = 0.0) -> str:
    """Color text using gradient position (0.0 = start, 1.0 = end)."""
    r, g, b = _interpolate_color(GRADIENT_START, GRADIENT_END, t)
    return f"\033[38;2;{r};{g};{b}m{text}\033[0m"


def color_start(text: str) -> str:
    """Color text with gradient start color (#0074d9)."""
    return color(text, 0.0)


def red(text: str) -> str:
    """Color text with brand red."""
    return f"\033[38;2;{RED[0]};{RED[1]};{RED[2]}m{text}\033[0m"


def color_end(text: str) -> str:
    """Color text with gradient end color (#009296)."""
    return color(text, 1.0)


def color_mid(text: str) -> str:
    """Color text with gradient middle color."""
    return color(text, 0.5)


def dim(text: str) -> str:
    """Dim/gray text."""
    return f"\033[38;2;128;128;128m{text}\033[0m"


def print_startup_info(
    host: str,
    port: int,
    database_url: str,
    llm_provider: str,
    llm_model: str,
    embeddings_provider: str,
    reranker_provider: str,
    mcp_enabled: bool = False,
    version: str | None = None,
    vector_extension: str | None = None,
    text_search_extension: str | None = None,
):
    """Print styled startup information."""
    print(color_start("Starting Atulya API..."))
    if version:
        print(f"  {dim('Version:')} {color(f'v{version}', 0.1)}")
    print(f"  {dim('URL:')} {color(f'http://{host}:{port}', 0.2)}")
    print(f"  {dim('Database:')} {color(mask_network_location(database_url), 0.4)}")
    print(f"  {dim('LLM:')} {color(f'{llm_provider} / {llm_model}', 0.6)}")
    print(f"  {dim('Embeddings:')} {color(embeddings_provider, 0.8)}")
    print(f"  {dim('Reranker:')} {color(reranker_provider, 1.0)}")
    extensions = f"{vector_extension or 'default'} (vector) / {text_search_extension or 'default'} (text)"
    print(f"  {dim('Extensions:')} {color(extensions, 0.4)}")
    if mcp_enabled:
        print(f"  {dim('MCP:')} {color_end('enabled at /mcp')}")
    print()
