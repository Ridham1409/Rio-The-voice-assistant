"""
RIO v1 — voice/wake_word.py
Lightweight wake word detector.

Strategy:
  - Record 2-second audio chunks in a background daemon thread
  - Skip silent chunks via RMS energy gate (near-zero CPU on silence)
  - Run faster-whisper tiny.en on speech chunks (shared model from stt.py)
  - Fire on_wake() callback when "hey rio" / "hello rio" detected

CPU usage: zero on silence, brief burst on speech only.
"""

import time
import threading
import numpy as np
import sounddevice as sd
from core.logger import get_logger

log = get_logger(__name__)

WAKE_WORDS     = {"hey rio", "hello rio", "hi rio", "okay rio", "ok rio"}
CHUNK_SECS     = 2          # detection window size
SAMPLE_RATE    = 16000
SILENCE_THRESH = 0.008      # RMS below this = silence, skip Whisper entirely
COOLDOWN_SECS  = 4          # seconds before re-triggering allowed


class WakeWordDetector:
    """
    Runs continuously in a background daemon thread.
    Calls on_wake() (synchronous) when wake word detected.
    on_wake must NOT block — use asyncio.run_coroutine_threadsafe if needed.
    """

    def __init__(self, on_wake):
        self.on_wake       = on_wake
        self._running      = False
        self._thread       = None
        self._last_trigger = 0.0

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        # Pre-warm the shared Whisper model in a thread so startup is non-blocking
        threading.Thread(target=self._prewarm, daemon=True).start()
        self._running = True
        self._thread  = threading.Thread(
            target   = self._loop,
            daemon   = True,
            name     = "RIO-WakeWord",
        )
        self._thread.start()
        log.info("[WAKE] Detector started — say 'Hey RIO' to activate.")

    def stop(self):
        self._running = False
        log.info("[WAKE] Detector stopped.")

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _prewarm():
        """Load the Whisper model now so first detection isn't slow."""
        try:
            from voice.stt import _get_model
            _get_model()
            log.info("[WAKE] Whisper model pre-warmed.")
        except Exception as e:
            log.warning(f"[WAKE] Pre-warm failed: {e}")

    def _loop(self):
        while self._running:
            try:
                # Record a 2-second chunk
                audio = sd.rec(
                    int(SAMPLE_RATE * CHUNK_SECS),
                    samplerate = SAMPLE_RATE,
                    channels   = 1,
                    dtype      = "int16",
                )
                sd.wait()

                if not self._running:
                    break

                # Energy gate — skip completely silent audio (no Whisper call)
                float_audio = audio.astype(np.float32).flatten() / 32768.0
                rms = float(np.sqrt(np.mean(float_audio ** 2)))
                if rms < SILENCE_THRESH:
                    continue

                # Cooldown — don't re-trigger during active session
                now = time.monotonic()
                if now - self._last_trigger < COOLDOWN_SECS:
                    continue

                # Transcribe the chunk
                from voice.stt import transcribe_float
                text = transcribe_float(float_audio)

                if not text:
                    continue

                log.debug(f"[WAKE] Heard: {text!r}")

                # Wake word match
                for ww in WAKE_WORDS:
                    if ww in text:
                        log.info(f"[WAKE] Triggered! Phrase: {text!r}")
                        self._last_trigger = time.monotonic()
                        try:
                            self.on_wake()
                        except Exception as e:
                            log.error(f"[WAKE] on_wake() raised: {e}")
                        break

            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error(f"[WAKE] Detection loop error: {e}")
                time.sleep(1.0)     # brief back-off on error
