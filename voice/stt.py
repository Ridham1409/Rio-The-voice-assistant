"""
RIO v1 — voice/stt.py
Speech-to-Text using faster-whisper (local, offline, no API key).

Model: tiny.en  — fastest, English-only, ~70MB download on first use.
Recording: sounddevice → numpy array → writes temp WAV → whisper transcribes.

Falls back to empty string on any error so the caller never crashes.
"""

import os
import tempfile
import wave
import numpy as np
from core.logger import get_logger

log = get_logger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
SAMPLE_RATE   = 16000
CHANNELS      = 1
DTYPE         = "int16"
WHISPER_MODEL = "tiny.en"   # swap for "base.en" if accuracy is more important

# ── Cached model (lazy-loaded once, reused forever) ───────────────────────────
_model = None

def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        log.info("[STT] Loading Whisper model (first use)...")
        _model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
        log.info("[STT] Model ready.")
    return _model


def _record(duration: float) -> np.ndarray:
    """Record audio from the default mic for `duration` seconds."""
    import sounddevice as sd
    log.info(f"[LISTEN] Recording started ({duration:.1f}s) — speak now...")
    audio = sd.rec(
        int(SAMPLE_RATE * duration),
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype=DTYPE,
    )
    sd.wait()
    log.info("[LISTEN] Recording stopped.")
    return audio


def _save_wav(audio: np.ndarray) -> str:
    """Save a numpy audio array to a temp WAV file. Returns the file path."""
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    with wave.open(tmp.name, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)          # 16-bit = 2 bytes
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())
    return tmp.name


def _transcribe(wav_path: str) -> str:
    """Transcribe a WAV file path."""
    model = _get_model()
    log.info("[STT] Transcribing audio...")
    import time
    t0 = time.monotonic()
    segments, _ = model.transcribe(wav_path, beam_size=1)
    # Collect all segments — don't iterate lazily (prevents mid-generator interrupts)
    texts = [seg.text for seg in segments]
    text  = " ".join(texts).strip()
    elapsed = time.monotonic() - t0
    if text:
        log.info(f"[STT] Result: {text!r}  ({elapsed:.2f}s)")
    else:
        log.info(f"[STT] No speech detected. ({elapsed:.2f}s)")
    return text


def transcribe_float(audio_f32: np.ndarray) -> str:
    """
    Transcribe a float32 numpy array directly (no temp file).
    Used by the wake word detector for speed.
    """
    model = _get_model()
    segments, _ = model.transcribe(audio_f32, beam_size=1, language="en")
    texts = [seg.text for seg in segments]
    return " ".join(texts).strip().lower()


def listen(duration: float = 5.0) -> str:
    """
    Record mic for `duration` seconds, transcribe with Whisper.
    Returns transcribed text or "" on any failure (including Ctrl+C).
    """
    wav_path = None
    try:
        audio    = _record(duration)
        wav_path = _save_wav(audio)
        text     = _transcribe(wav_path)
        return text
    except KeyboardInterrupt:
        log.warning("[LISTEN] Interrupted — returning empty string.")
        return ""
    except ImportError as e:
        log.error(f"[LISTEN] Missing dep: {e}")
        return ""
    except Exception as e:
        log.error(f"[LISTEN] Error: {e}")
        return ""
    finally:
        if wav_path and os.path.exists(wav_path):
            try:
                os.remove(wav_path)
            except Exception:
                pass
