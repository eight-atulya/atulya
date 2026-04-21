from __future__ import annotations

TOKENS: dict[str, str] = {
    "bg": "#0B0B0B",
    "surface": "#111111",
    "surface_alt": "#1A1A1A",
    "text": "#FFFFFF",
    "muted": "#CFCFCF",
    "primary": "#D00000",
    "accent_blue": "#1E90FF",
    "accent_green": "#39FF14",
    "accent_yellow": "#FFD400",
    "error": "#FF3B30",
}


APP_CSS = """
Screen {
    background: #0B0B0B;
    color: #FFFFFF;
}

#main {
    height: 1fr;
}

#leftPane {
    width: 3fr;
    padding: 0 1;
    background: #0F0F0F;
}

#rightPane {
    width: 1fr;
    min-width: 28;
    padding: 0 1;
    background: #141414;
    border-left: solid #2A2A2A;
}

#titleBar {
    dock: top;
    height: 1;
    background: #D00000;
    color: #FFFFFF;
    content-align: left middle;
    padding: 0 1;
}

#statusBar {
    height: 1;
    color: #FFD400;
    padding: 0 1;
    background: #0B0B0B;
}

#chatLog {
    height: 1fr;
    border: solid #262626;
    background: #0C0C0C;
    scrollbar-size: 1 1;
}

#commandPopup {
    display: none;
    max-height: 8;
    border: solid #1E90FF;
    background: #0B0B0B;
    margin-top: 0;
}

#composer {
    margin-top: 0;
    border: solid #1E90FF;
    background: #0B0B0B;
}

#promptPane {
    height: 1fr;
    border: solid #262626;
    background: #0C0C0C;
    scrollbar-size: 1 1;
}

#telemetryPane {
    margin-top: 0;
    height: 3;
    border: solid #262626;
    color: #39FF14;
    padding: 0 1;
    content-align: left middle;
    background: #0C0C0C;
}
"""
