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

import re
import time
import logging
import threading
import numpy as np
import sounddevice as sd
from core.logger import get_logger

log = get_logger(__name__, level=logging.DEBUG)   # DEBUG so RMS values show

# ── Tunable constants ─────────────────────────────────────────────────────────

WAKE_WORDS     = {"hey rio", "hello rio", "hi rio", "okay rio", "ok rio", "rio"}
CHUNK_SECS     = 2          # detection window size
SAMPLE_RATE    = 16000
SILENCE_THRESH = 0.003      # ↓ was 0.008 — typical speech RMS is 0.01–0.05
COOLDOWN_SECS  = 4          # seconds before re-triggering allowed

# Punctuation stripper — Whisper often adds commas/periods
_PUNCT = re.compile(r"[^\w\s]")


def _clean(text: str) -> str:
    """Lowercase + strip punctuation for robust matching."""
    return _PUNCT.sub("", text).lower().strip()


def _print_mic_info() -> None:
    """Log the default input device so developer can verify the right mic."""
    try:
        dev = sd.query_devices(kind="input")
        log.info(f"[WAKE] Mic: {dev['name']!r}  (SR={int(dev['default_samplerate'])}Hz, ch={dev['max_input_channels']})")
    except Exception as e:
        log.warning(f"[WAKE] Could not query default mic: {e}")


class WakeWordDetector:
    """
    Runs continuously in a background daemon thread.
    Calls on_wake() (synchronous) when wake word detected.

    Args:
        on_wake:      Callable fired on wake word detection.
        interrupt_fn: Optional callable — called BEFORE on_wake to stop any
                      in-progress TTS or active voice session.
    """

    def __init__(self, on_wake, interrupt_fn=None):
        self.on_wake       = on_wake
        self.interrupt_fn  = interrupt_fn
        self._running      = False
        self._thread       = None
        self._last_trigger = 0.0

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        _print_mic_info()
        # Pre-warm the shared Whisper model in a thread so startup is non-blocking
        threading.Thread(target=self._prewarm, daemon=True).start()
        self._running = True
        self._thread  = threading.Thread(
            target = self._loop,
            daemon = True,
            name   = "RIO-WakeWord",
        )
        self._thread.start()
        log.info(f"[WAKE] Detector active (threshold={SILENCE_THRESH}) — say 'Hey RIO'.")

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
        chunk_num = 0

        while self._running:
            try:
                # ── Record a chunk ────────────────────────────────────────────
                audio = sd.rec(
                    int(SAMPLE_RATE * CHUNK_SECS),
                    samplerate = SAMPLE_RATE,
                    channels   = 1,
                    dtype      = "int16",
                )
                sd.wait()

                if not self._running:
                    break

                chunk_num += 1
                float_audio = audio.astype(np.float32).flatten() / 32768.0
                rms = float(np.sqrt(np.mean(float_audio ** 2)))

                # ── RMS debug log (every chunk, dimmed via DEBUG level) ────────
                log.debug(f"[WAKE] chunk #{chunk_num:04d}  rms={rms:.4f}  thresh={SILENCE_THRESH}")

                # ── Energy gate ───────────────────────────────────────────────
                if rms < SILENCE_THRESH:
                    continue    # silent — skip Whisper completely

                # ── Cooldown ──────────────────────────────────────────────────
                now = time.monotonic()
                if now - self._last_trigger < COOLDOWN_SECS:
                    log.debug("[WAKE] In cooldown — skipping.")
                    continue

                # ── Transcribe ────────────────────────────────────────────────
                log.debug(f"[WAKE] chunk #{chunk_num:04d} has speech (rms={rms:.4f}) — transcribing...")
                from voice.stt import transcribe_float
                raw_text   = transcribe_float(float_audio)
                clean_text = _clean(raw_text)

                if not clean_text:
                    log.debug("[WAKE] Transcription empty.")
                    continue

                log.info(f"[WAKE] Heard: {raw_text!r}  (cleaned: {clean_text!r})")

                # ── Wake word match ────────────────────────────────────────────
                matched = next(
                    (ww for ww in WAKE_WORDS if ww in clean_text),
                    None,
                )

                if matched:
                    log.info(f"[WAKE] >>> Triggered! matched={matched!r} in {raw_text!r}")
                    self._last_trigger = time.monotonic()

                    # 1. Interrupt any ongoing TTS / session FIRST
                    if self.interrupt_fn is not None:
                        try:
                            self.interrupt_fn()
                            time.sleep(0.15)   # brief pause for SAPI5 to stop
                        except Exception as e:
                            log.error(f"[WAKE] interrupt_fn raised: {e}")

                    # 2. Fire the new session
                    try:
                        self.on_wake()
                    except Exception as e:
                        log.error(f"[WAKE] on_wake() raised: {e}")
                else:
                    log.debug(f"[WAKE] No wake word in: {clean_text!r}")

            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error(f"[WAKE] Detection loop error: {e}")
                time.sleep(1.0)     # brief back-off on error
