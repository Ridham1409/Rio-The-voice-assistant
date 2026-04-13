"""
RIO v1 — voice/tts.py
Text-to-Speech using pyttsx3 (offline, Windows SAPI5).

Uses a persistent engine instance to avoid re-init overhead.
Falls back silently if pyttsx3 is not available.
"""

import threading
from core.logger import get_logger

log = get_logger(__name__)

# ── Lazy-init engine (only created when first used) ───────────────────────────
_engine = None
_lock   = threading.Lock()


def _get_engine():
    global _engine
    if _engine is None:
        with _lock:
            if _engine is None:           # double-checked locking
                try:
                    import pyttsx3
                    _engine = pyttsx3.init()
                    # Voice settings — tweak as needed
                    _engine.setProperty("rate",   185)   # words per minute
                    _engine.setProperty("volume", 0.95)  # 0.0 – 1.0
                    # Prefer a female voice if available
                    voices = _engine.getProperty("voices")
                    for v in voices:
                        if "zira" in v.name.lower() or "female" in v.name.lower():
                            _engine.setProperty("voice", v.id)
                            break
                    log.info("[TTS] Engine initialised.")
                except Exception as e:
                    log.error(f"[TTS] Could not init pyttsx3: {e}")
                    _engine = None
    return _engine


def speak(text: str) -> None:
    """
    Speak text aloud using pyttsx3.
    Non-blocking guard: skips gracefully if engine unavailable.
    Strips markup/symbols that TTS would read literally.
    """
    if not text or not text.strip():
        return

    engine = _get_engine()
    if engine is None:
        log.warning("[TTS] Engine unavailable — skipping speech.")
        return

    # Strip step-result prefixes like "Step 1: " for cleaner speech
    import re
    clean = re.sub(r"^Step \d+:\s*", "", text, flags=re.MULTILINE)
    clean = clean.replace("⚠️", "Warning.").strip()

    try:
        log.info(f"[TTS] Speaking: {clean[:60]}...")
        engine.say(clean)
        engine.runAndWait()
    except RuntimeError:
        # runAndWait called while already running — safe to ignore
        pass
    except Exception as e:
        log.error(f"[TTS] Speech failed: {e}")
