"""
RIO v1 — voice/tts.py
Text-to-Speech using pyttsx3 (offline, Windows SAPI5).

Interruptible design:
  - speak() runs engine.runAndWait() in a daemon thread
  - A module-level threading.Event is polled every 50ms
  - Any thread can call stop_speaking() to cut speech mid-sentence
  - engine.stop() is called, which signals SAPI5 to stop immediately

Falls back silently if pyttsx3 is not available.
"""

import re
import threading
from core.logger import get_logger

log = get_logger(__name__)

# ── Module-level interrupt signal ─────────────────────────────────────────────
# Set this from any thread to stop TTS immediately.
_stop_event = threading.Event()

# ── Persistent engine (lazy, thread-safe init) ────────────────────────────────
_engine = None
_engine_lock = threading.Lock()


def _get_engine():
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                try:
                    import pyttsx3
                    _engine = pyttsx3.init()
                    _engine.setProperty("rate",   185)
                    _engine.setProperty("volume", 0.95)
                    # Prefer Zira (Windows female voice) if available
                    for v in _engine.getProperty("voices"):
                        if "zira" in v.name.lower() or "female" in v.name.lower():
                            _engine.setProperty("voice", v.id)
                            break
                    log.info("[TTS] Engine initialised.")
                except Exception as e:
                    log.error(f"[TTS] Could not init pyttsx3: {e}")
                    _engine = None
    return _engine


# ── Public API ────────────────────────────────────────────────────────────────

def stop_speaking() -> None:
    """
    Interrupt any in-progress TTS immediately.
    Safe to call from any thread at any time.
    """
    engine = _engine     # read without lock (safe — worst case we just set the flag)
    _stop_event.set()
    if engine is not None:
        try:
            engine.stop()
        except Exception:
            pass
    log.info("[TTS] Stop signal sent.")


def speak(text: str, extra_stop: threading.Event = None) -> None:
    """
    Speak `text` aloud. Returns only when speech finishes OR is interrupted.

    Args:
        text:       Text to speak.
        extra_stop: Optional additional threading.Event — if set, also stops TTS.
                    Used by the API server to wire voice-session interrupts.
    """
    if not text or not text.strip():
        return

    engine = _get_engine()
    if engine is None:
        log.warning("[TTS] Engine unavailable — skipping.")
        return

    # Clean for speech
    clean = re.sub(r"^Step \d+:\s*", "", text, flags=re.MULTILINE)
    clean = clean.replace("⚠️", "Warning.").strip()
    if not clean:
        return

    # Clear any stale stop signal before we start
    _stop_event.clear()

    log.info(f"[TTS] Speaking: {clean[:60]}...")

    # ── Run engine in a daemon thread so we can interrupt it ─────────────────
    _done = threading.Event()

    def _run():
        try:
            engine.say(clean)
            engine.runAndWait()
        except RuntimeError:
            pass        # already stopped
        except Exception as e:
            log.error(f"[TTS] Speech error: {e}")
        finally:
            _done.set()

    t = threading.Thread(target=_run, daemon=True, name="RIO-TTS")
    t.start()

    # ── Poll for interrupt every 50ms ─────────────────────────────────────────
    while not _done.wait(timeout=0.05):
        if _stop_event.is_set():
            log.info("[TTS] Interrupted by _stop_event.")
            try:
                engine.stop()
            except Exception:
                pass
            _stop_event.clear()
            break
        if extra_stop is not None and extra_stop.is_set():
            log.info("[TTS] Interrupted by extra_stop event.")
            try:
                engine.stop()
            except Exception:
                pass
            break

    t.join(timeout=1.0)     # wait for thread to finish (brief)
