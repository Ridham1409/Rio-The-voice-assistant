"""
RIO v1 — voice/wake_word.py
Reliable wake word detector with false-trigger prevention.

Matching rules (ALL must pass to trigger):
  1. RMS energy gate   — must exceed SILENCE_THRESH
  2. Minimum length    — transcription must have >= MIN_WORDS words
  3. Position check    — wake phrase must start within first MAX_PREFIX_WORDS
  4. Confidence gate   — Whisper avg_logprob must exceed MIN_CONFIDENCE
  5. Cooldown          — no re-trigger within COOLDOWN_SECS seconds
"""

import re
import time
import logging
import threading
import numpy as np
import sounddevice as sd
from core.logger import get_logger

log = get_logger(__name__, level=logging.DEBUG)

# ── Constants ─────────────────────────────────────────────────────────────────

WAKE_WORDS      = {"hey rio", "hello rio", "hi rio"}   # "rio" alone removed — too noisy
CHUNK_SECS      = 2.5         # slightly longer window → better context
SAMPLE_RATE     = 16000
SILENCE_THRESH  = 0.003       # RMS below this = silence, skip Whisper
MIN_WORDS       = 2           # ignore single-word clips ("hmm", noise bursts)
MAX_PREFIX_WORDS = 4          # wake phrase must start within first N words
MIN_CONFIDENCE  = -0.7        # Whisper avg_logprob; -0.7 = reasonable, < -1.0 = guessing
COOLDOWN_SECS   = 5           # seconds between triggers

# Strip punctuation before matching
_PUNCT = re.compile(r"[^\w\s]")


def _clean(text: str) -> str:
    """Lowercase + strip punctuation for robust matching."""
    return _PUNCT.sub("", text).lower().strip()


def _position_ok(clean_text: str, wake_word: str) -> bool:
    """
    Return True if `wake_word` starts within the first MAX_PREFIX_WORDS words.
    Handles slight Whisper preambles like "Um, hey RIO..." gracefully.
    """
    words    = clean_text.split()
    ww_words = wake_word.split()
    ww_len   = len(ww_words)
    limit    = min(MAX_PREFIX_WORDS, max(0, len(words) - ww_len + 1))
    for start in range(limit):
        if words[start : start + ww_len] == ww_words:
            return True
    return False


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
                      in-progress TTS or voice session.
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
        threading.Thread(target=self._prewarm, daemon=True).start()
        self._running = True
        self._thread  = threading.Thread(
            target = self._loop,
            daemon = True,
            name   = "RIO-WakeWord",
        )
        self._thread.start()
        log.info(
            f"[WAKE] Detector active  thresh={SILENCE_THRESH}  "
            f"min_words={MIN_WORDS}  min_conf={MIN_CONFIDENCE}  "
            f"cooldown={COOLDOWN_SECS}s  words={sorted(WAKE_WORDS)}"
        )

    def stop(self):
        self._running = False
        log.info("[WAKE] Detector stopped.")

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _prewarm():
        try:
            from voice.stt import _get_model
            _get_model()
            log.info("[WAKE] Whisper model pre-warmed.")
        except Exception as e:
            log.warning(f"[WAKE] Pre-warm failed: {e}")

    @staticmethod
    def _transcribe_with_confidence(float_audio: np.ndarray):
        """
        Transcribe float32 audio and return (clean_text, avg_logprob).
        Bypasses stt.transcribe_float to access per-segment confidence.
        """
        from voice.stt import _get_model
        model = _get_model()
        segments, _ = model.transcribe(float_audio, beam_size=1, language="en")
        segs = list(segments)      # materialise to get logprob
        if not segs:
            return "", 0.0
        avg_logprob = sum(s.avg_logprob for s in segs) / len(segs)
        text = " ".join(s.text for s in segs).strip()
        return text, avg_logprob

    def _loop(self):
        chunk_num = 0

        while self._running:
            try:
                # ── 1. Record chunk ───────────────────────────────────────────
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

                log.debug(f"[WAKE] chunk #{chunk_num:04d}  rms={rms:.4f}  thresh={SILENCE_THRESH}")

                # ── 2. Energy gate ────────────────────────────────────────────
                if rms < SILENCE_THRESH:
                    continue

                # ── 3. Cooldown ───────────────────────────────────────────────
                now = time.monotonic()
                if now - self._last_trigger < COOLDOWN_SECS:
                    log.debug(f"[WAKE] Cooldown ({COOLDOWN_SECS - (now - self._last_trigger):.1f}s left) — skip.")
                    continue

                # ── 4. Transcribe + confidence ────────────────────────────────
                log.debug(f"[WAKE] Speech detected (rms={rms:.4f}) — transcribing...")
                raw_text, avg_logprob = self._transcribe_with_confidence(float_audio)
                clean_text = _clean(raw_text)

                if not clean_text:
                    log.debug("[WAKE] Transcription empty — skip.")
                    continue

                log.info(
                    f"[WAKE] Heard: {raw_text!r}  "
                    f"conf={avg_logprob:.3f}  words={len(clean_text.split())}"
                )

                # ── 5. Minimum word count ─────────────────────────────────────
                if len(clean_text.split()) < MIN_WORDS:
                    log.debug(f"[WAKE] Too short ({len(clean_text.split())} word(s) < {MIN_WORDS}) — skip.")
                    continue

                # ── 6. Confidence gate ────────────────────────────────────────
                if avg_logprob < MIN_CONFIDENCE:
                    log.debug(f"[WAKE] Low confidence ({avg_logprob:.3f} < {MIN_CONFIDENCE}) — skip.")
                    continue

                # ── 7. Wake word + position check ────────────────────────────
                matched = None
                for ww in WAKE_WORDS:
                    if ww in clean_text and _position_ok(clean_text, ww):
                        matched = ww
                        break

                if not matched:
                    log.debug(f"[WAKE] No wake word at start of: {clean_text!r}")
                    continue

                # ── All checks passed — TRIGGER ───────────────────────────────
                log.info(
                    f"[WAKE] >>> TRIGGERED  matched={matched!r}  "
                    f"conf={avg_logprob:.3f}  phrase={raw_text!r}"
                )
                self._last_trigger = time.monotonic()

                if self.interrupt_fn is not None:
                    try:
                        self.interrupt_fn()
                        time.sleep(0.15)
                    except Exception as e:
                        log.error(f"[WAKE] interrupt_fn raised: {e}")

                try:
                    self.on_wake()
                except Exception as e:
                    log.error(f"[WAKE] on_wake() raised: {e}")

            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error(f"[WAKE] Detection loop error: {e}")
                time.sleep(1.0)
