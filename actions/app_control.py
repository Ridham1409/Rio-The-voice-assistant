"""
RIO v1 — actions/app_control.py
Opens named applications on Windows using a 3-tier strategy:
  1. APP_MAP  — exact known path (fastest, most reliable)
  2. 'start'  — Windows shell start command (handles PATH apps + registered names)
  3. os.startfile() — last resort for anything Windows knows about
"""

import os
import subprocess
from pathlib import Path
from core.logger import get_logger

log = get_logger(__name__)

# ── APP_MAP: friendly name → full path (or short executable name) ─────────────
# Full paths are preferred for reliability.
# Short names (e.g. "notepad.exe") work if the app is on PATH or is a system app.
APP_MAP = {
    # ── Browsers ──────────────────────────────────────────────────────────────
    "chrome":           r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "google chrome":    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "brave":            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    "brave browser":    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    "edge":             r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "microsoft edge":   r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "firefox":          r"C:\Program Files\Mozilla Firefox\firefox.exe",
    "opera":            r"C:\Users\Ridham Bhavnagariya\AppData\Local\Programs\Opera\opera.exe",
    # ── Windows built-ins (always available) ──────────────────────────────────
    "notepad":          "notepad.exe",
    "calculator":       "calc.exe",
    "calc":             "calc.exe",
    "paint":            "mspaint.exe",
    "mspaint":          "mspaint.exe",
    "explorer":         "explorer.exe",
    "file explorer":    "explorer.exe",
    "task manager":     "taskmgr.exe",
    "taskmgr":          "taskmgr.exe",
    "cmd":              "cmd.exe",
    "command prompt":   "cmd.exe",
    "powershell":       "powershell.exe",
    "control panel":    "control.exe",
    "settings":         "ms-settings:",          # uses startfile
    "snipping tool":    "snippingtool.exe",
    "wordpad":          "wordpad.exe",
    "clock":            "ms-clock:",             # uses startfile
    # ── Development tools ─────────────────────────────────────────────────────
    "vscode":           "code",
    "vs code":          "code",
    "visual studio code": "code",
    "git bash":         r"C:\Program Files\Git\git-bash.exe",
    # ── Office (requires Microsoft Office installed) ───────────────────────────
    "word":             "winword",
    "excel":            "excel",
    "powerpoint":       "powerpnt",
    "outlook":          "outlook",
    # ── Media & Communication ─────────────────────────────────────────────────
    "spotify":          r"C:\Users\Ridham Bhavnagariya\AppData\Roaming\Spotify\Spotify.exe",
    "discord":          r"C:\Users\Ridham Bhavnagariya\AppData\Local\Discord\Update.exe",
    "vlc":              r"C:\Program Files\VideoLAN\VLC\vlc.exe",
    "zoom":             r"C:\Users\Ridham Bhavnagariya\AppData\Roaming\Zoom\bin\Zoom.exe",
    "telegram":         r"C:\Users\Ridham Bhavnagariya\AppData\Roaming\Telegram Desktop\Telegram.exe",
    "whatsapp":         r"C:\Users\Ridham Bhavnagariya\AppData\Local\WhatsApp\WhatsApp.exe",
    # ── System utilities ──────────────────────────────────────────────────────
    "steam":            r"C:\Program Files (x86)\Steam\Steam.exe",
    "obs":              r"C:\Program Files\obs-studio\bin\64bit\obs64.exe",
    "obs studio":       r"C:\Program Files\obs-studio\bin\64bit\obs64.exe",
}

# Shell metacharacter guard — prevents injection via shell=True
_SHELL_CHARS = set(';&|<>`$(){}[]\r\n')


def open_app(name: str, cfg: dict) -> str:
    """
    Open an application by friendly name. Never raises.
    Uses a 3-tier fallback strategy with full logging at each tier.
    """
    # ── Input validation ──────────────────────────────────────────────────────
    if not name or not name.strip():
        log.warning("[GUARD] open_app: empty name.")
        return "Please specify an application name."
    if len(name) > 100:
        log.warning(f"[GUARD] open_app: name too long ({len(name)} chars).")
        return "Application name is too long."
    if any(c in _SHELL_CHARS for c in name):
        log.warning(f"[GUARD] open_app: illegal chars in {name!r}")
        return "Invalid application name — contains illegal characters."

    name_lower = name.lower().strip()

    # ── Tier 1: APP_MAP exact match ───────────────────────────────────────────
    exe = APP_MAP.get(name_lower)

    # Partial match (e.g. "brave" matches "brave browser")
    if exe is None:
        for key, path in APP_MAP.items():
            if key in name_lower or name_lower in key:
                exe = path
                log.info(f"[MAP] Partial match: {name!r} -> key={key!r}")
                break

    if exe is not None:
        # Check if it's a ms- URI scheme (use startfile)
        if exe.startswith("ms-"):
            return _try_startfile(exe, name)

        # Check path exists (skip if it's a short name like notepad.exe)
        is_full_path = "\\" in exe or "/" in exe
        if is_full_path and not Path(exe).exists():
            log.warning(f"[MAP] Path not found: {exe} — falling through to 'start'")
        else:
            return _try_popen(exe, name, method="MAP")

    # ── Tier 2: Windows 'start' command ──────────────────────────────────────
    # 'start' can open anything registered in Windows (installed apps, UWP, etc.)
    result = _try_start(name, name_lower)
    if result is not None:
        return result

    # ── Tier 3: os.startfile() ───────────────────────────────────────────────
    return _try_startfile(name_lower, name)


# ── Tier helpers ──────────────────────────────────────────────────────────────

def _try_popen(exe: str, friendly_name: str, method: str) -> str:
    """Launch exe with subprocess.Popen (non-blocking)."""
    try:
        log.info(f"[{method}] Launching: {exe}")
        subprocess.Popen(exe, shell=True)
        return f"Opened {friendly_name}."
    except Exception as e:
        log.error(f"[{method}] Popen failed for {exe!r}: {e}")
        return None     # caller will cascade to next tier


def _try_start(friendly_name: str, name_lower: str) -> str:
    """Use Windows 'start' shell command — handles PATH apps + registered names."""
    try:
        log.info(f"[START] Trying: start {name_lower!r}")
        # start "" <name> — empty title prevents issues with paths containing spaces
        result = subprocess.run(
            f'start "" "{name_lower}"',
            shell=True,
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return f"Opened {friendly_name}."
        log.warning(f"[START] Returned code {result.returncode} for {name_lower!r}")
        return None
    except subprocess.TimeoutExpired:
        # start sometimes hangs on invalid names — treat as failure
        log.warning(f"[START] Timed out for {name_lower!r}")
        return None
    except Exception as e:
        log.error(f"[START] Error: {e}")
        return None


def _try_startfile(target: str, friendly_name: str) -> str:
    """os.startfile() — Windows ShellExecute, last resort."""
    try:
        log.info(f"[STARTFILE] Trying: os.startfile({target!r})")
        os.startfile(target)
        return f"Opened {friendly_name}."
    except FileNotFoundError:
        log.error(f"[STARTFILE] Not found: {target!r}")
        return (
            f"Could not find '{friendly_name}'. "
            "Make sure it is installed, or add its path to APP_MAP in actions/app_control.py."
        )
    except Exception as e:
        log.error(f"[STARTFILE] Failed for {target!r}: {e}")
        return f"Could not open '{friendly_name}'. Error: {e}"
