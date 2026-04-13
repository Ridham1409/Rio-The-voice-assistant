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
SAMPLE_RATE   = 16000    # Hz — Whisper requires 16kHz
CHANNELS      = 1        # Mono
DTYPE         = "int16"  # PCM 16-bit
WHISPER_MODEL = "tiny.en"  # tiny.en = fastest; swap for "base.en" for accuracy


def _record(duration: float) -> np.ndarray:
    """Record audio from the default mic for `duration` seconds."""
    import sounddevice as sd
    log.info(f"[STT] Recording for {duration}s...")
    audio = sd.rec(
        int(SAMPLE_RATE * duration),
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype=DTYPE,
    )
    sd.wait()                       # block until recording finishes
    log.info("[STT] Recording complete.")
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
    """Run faster-whisper on the WAV file. Returns plain text."""
    from faster_whisper import WhisperModel
    model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(wav_path, beam_size=1)
    text = " ".join(seg.text for seg in segments).strip()
    log.info(f"[STT] Transcribed: {text!r}")
    return text


def listen(duration: float = 5.0) -> str:
    """
    Record mic for `duration` seconds, transcribe with Whisper.

    Returns:
        Transcribed text string, or "" on any failure.
    """
    wav_path = None
    try:
        audio    = _record(duration)
        wav_path = _save_wav(audio)
        text     = _transcribe(wav_path)
        return text
    except ImportError as e:
        log.error(f"[STT] Missing dependency: {e}. Run: py -3 -m pip install faster-whisper sounddevice")
        return ""
    except Exception as e:
        log.error(f"[STT] Error during speech recognition: {e}")
        return ""
    finally:
        if wav_path and os.path.exists(wav_path):
            try:
                os.remove(wav_path)
            except Exception:
                pass
