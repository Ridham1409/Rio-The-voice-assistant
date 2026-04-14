"""
RIO v1 — core/logger.py
Structured, timestamped, color-coded console logger.

Format:
  HH:MM:SS  LEVEL     module — message

Colors:
  DEBUG   → cyan
  INFO    → green
  WARNING → yellow
  ERROR   → red (bold)
  CRITICAL→ red background
"""

import logging
import sys

try:
    from colorama import Fore, Back, Style, init as colorama_init
    colorama_init(autoreset=True)
    _HAS_COLOR = True
except ImportError:
    _HAS_COLOR = False
    class _Stub:
        def __getattr__(self, _): return ""
    Fore = Back = Style = _Stub()

# ── Level → (color, short label) ─────────────────────────────────────────────
_LEVEL_STYLE = {
    "DEBUG":    (Fore.CYAN,                          "DEBUG"),
    "INFO":     (Fore.GREEN,                         "INFO "),
    "WARNING":  (Fore.YELLOW,                        "WARN "),
    "ERROR":    (Fore.RED + Style.BRIGHT,            "ERROR"),
    "CRITICAL": (Back.RED + Fore.WHITE + Style.BRIGHT, "CRIT "),
}

# ── Module name → display color ───────────────────────────────────────────────
# Gives each subsystem a distinct color for faster visual scanning.
_MODULE_COLOR = {
    "voice.wake_word": Fore.MAGENTA,
    "voice.stt":       Fore.CYAN,
    "voice.tts":       Fore.BLUE,
    "agent.executor":  Fore.YELLOW,
    "brain.llm_client":Fore.CYAN,
    "brain.fast_match":Fore.GREEN,
    "actions":         Fore.YELLOW,
    "api":             Fore.WHITE,
    "rio":             Fore.WHITE,
}

_DIM = Style.DIM if _HAS_COLOR else ""
_RST = Style.RESET_ALL if _HAS_COLOR else ""


class _RIOFormatter(logging.Formatter):
    """
    Formats log records as:
      HH:MM:SS  LEVEL  module — message

    Each column is fixed-width to keep the terminal aligned.
    """

    def format(self, record: logging.LogRecord) -> str:
        # Timestamp
        ts = self.formatTime(record, "%H:%M:%S")

        # Level
        lv_color, lv_label = _LEVEL_STYLE.get(record.levelname, ("", record.levelname[:5]))
        lv_str = f"{lv_color}{lv_label}{_RST}"

        # Module name (shortened)
        mod = record.name
        mod_color = ""
        for prefix, color in _MODULE_COLOR.items():
            if mod.startswith(prefix):
                mod_color = color
                break
        # Trim long module paths: "brain.llm_client" → "llm_client"
        short_mod = mod.split(".")[-1] if "." in mod else mod
        mod_str = f"{mod_color}{short_mod:<14}{_RST}"

        # Message
        msg = record.getMessage()

        # Exception info
        exc = ""
        if record.exc_info:
            exc = "\n" + self.formatException(record.exc_info)

        return f"{_DIM}{ts}{_RST}  {lv_str}  {mod_str}  {msg}{exc}"


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """
    Return a named RIO logger. Idempotent — calling twice returns the same logger.

    Args:
        name:  Typically __name__ of the calling module.
        level: Logging level (default INFO). Use logging.DEBUG for verbose output.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_RIOFormatter())
        logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = False
    return logger
