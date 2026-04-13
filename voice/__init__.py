"""
RIO v1 — voice/__init__.py
"""
from .stt import listen
from .tts import speak

__all__ = ["listen", "speak"]
