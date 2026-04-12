"""
RIO v1 — core/logger.py
Simple colored console logger. No file rotation, no config complexity.
"""

import logging
import sys
from colorama import Fore, Style, init as colorama_init

colorama_init(autoreset=True)

_COLORS = {
    "DEBUG":   Fore.CYAN,
    "INFO":    Fore.GREEN,
    "WARNING": Fore.YELLOW,
    "ERROR":   Fore.RED,
}

class _ColorFormatter(logging.Formatter):
    def format(self, record):
        color = _COLORS.get(record.levelname, "")
        record.levelname = f"{color}{record.levelname}{Style.RESET_ALL}"
        return super().format(record)

def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_ColorFormatter("%(levelname)-18s %(name)s — %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger
