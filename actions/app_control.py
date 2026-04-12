"""
RIO v1 — actions/app_control.py
Opens named applications on Windows.
"""

import subprocess
from pathlib import Path
from core.logger import get_logger

log = get_logger(__name__)

# Known app → executable mapping
APP_MAP = {
    "chrome":      r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "google chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "firefox":     r"C:\Program Files\Mozilla Firefox\firefox.exe",
    "notepad":     "notepad.exe",
    "calculator":  "calc.exe",
    "vscode":      "code",
    "vs code":     "code",
    "explorer":    "explorer.exe",
    "discord":     "discord",
    "spotify":     "spotify",
    "word":        "winword",
    "excel":       "excel",
    "paint":       "mspaint.exe",
}


def open_app(name: str, cfg: dict) -> str:
    """
    Open an application by friendly name.
    Returns a status string. Never raises.
    """
    # ─ Input validation ───────────────────────────────────────────────
    if not name or not name.strip():
        log.warning("[GUARD] open_app called with empty name.")
        return "Please specify an application name."
    if len(name) > 100:
        log.warning(f"[GUARD] open_app: name too long ({len(name)} chars).")
        return "Application name is too long."
    # Block shell metacharacters to prevent injection
    _SHELL_CHARS = set(';&#|><`$(){}[]\r\n')
    if any(c in _SHELL_CHARS for c in name):
        log.warning(f"[GUARD] open_app: dangerous characters in name: {name!r}")
        return "Invalid application name — contains illegal characters."
    # ─ Resolve path ───────────────────────────────────────────────
    name_lower = name.lower().strip()
    exe = APP_MAP.get(name_lower)

    # Partial match fallback
    if exe is None:
        for key, path in APP_MAP.items():
            if key in name_lower or name_lower in key:
                exe = path
                break

    # Last resort: try the name directly
    if exe is None:
        exe = name_lower
        log.warning(f"'{name}' not in APP_MAP — trying directly: {exe}")

    # Check config override
    cfg_path = cfg.get("actions", {}).get("chrome_path")
    if "chrome" in name_lower and cfg_path:
        exe = cfg_path

    log.info(f"Opening: {exe}")
    try:
        subprocess.Popen(exe, shell=True)
        return f"Opened {name}."
    except Exception as e:
        log.error(f"Failed to open '{exe}': {e}")
        return f"Could not open {name}. Error: {e}"
