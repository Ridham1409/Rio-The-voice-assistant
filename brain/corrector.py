"""
RIO v1 — brain/corrector.py
STT (Speech-to-Text) command correction layer.

Problem: Whisper often mishears commands phonetically.
  "go on ground"  → intended: "open chrome"
  "surge the web" → intended: "search the web"
  "greet a file"  → intended: "create a file"

Two-layer correction (no extra dependencies — stdlib only):

  Layer 1 — Alias table
    Deterministic phonetic/variant mapping for known verbs and known targets.
    When both verb AND target correct → highest confidence, always applied.

  Layer 2 — Full-phrase difflib fuzzy match
    Fallback: compare full transcript against all known template phrases.
    Applied only when similarity >= FUZZY_THRESHOLD.

Integration:
    from brain.corrector import correct_text
    corrected, changed = correct_text(raw_stt_text)
"""

import difflib
from core.logger import get_logger

log = get_logger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

FUZZY_THRESHOLD = 0.55      # difflib ratio required for full-phrase correction
ALIAS_MIN_CHARS = 2         # ignore 1-char words in alias matching

# ── Action verb alias map ─────────────────────────────────────────────────────
# Maps mishearings/variants → canonical action verb.
# Key = what Whisper might say, Value = what we want.
# Supports 1-word AND 2-word prefixes (checked longest-first).

_RAW_ACTION_ALIASES = {
    # "open" variants
    "go on":    "open",
    "go in":    "open",
    "get on":   "open",
    "upon":     "open",
    "up on":    "open",
    "goon":     "open",
    "opnum":    "open",
    "opening":  "open",
    # "search" variants
    "surge":    "search",
    "surge the":"search the",
    "serge":    "search",
    "sir":      "search",
    "such":     "search",
    "switch":   "search",
    "search for":"search",
    # "create" variants
    "great":    "create",
    "greet":    "create",
    "grate":    "create",
    "crate":    "create",
    "crater":   "create",
    # "close" variants
    "clothes":  "close",
    "cloves":   "close",
    "clause":   "close",
    # "read" variants
    "red":      "read",
    "reed":     "read",
    "lead":     "read",
}

# ── Target (app/object) alias map ─────────────────────────────────────────────
# Maps mishearings of known targets → canonical name.

_RAW_TARGET_ALIASES = {
    # Chrome
    "ground":   "chrome",
    "groom":    "chrome",
    "groan":    "chrome",
    "croan":    "chrome",
    "crome":    "chrome",
    "grown":    "chrome",
    "chrome.":  "chrome",
    # Brave
    "grave":    "brave",
    "braid":    "brave",
    "breed":    "brave",
    "bravo":    "brave",
    # Edge
    "hedge":    "edge",
    "age":      "edge",
    # Notepad
    "note pad": "notepad",
    "no pad":   "notepad",
    "note pet": "notepad",
    "not pad":  "notepad",
    # YouTube
    "you tube":  "youtube",
    "you tooth": "youtube",
    "u-tube":    "youtube",
    # Spotify
    "sport if i":"spotify",
    "spot if i": "spotify",
    # VS Code
    "vs code":   "vscode",
    "be as code":"vscode",
    "vs cold":   "vscode",
    # File/folder
    "file.":     "file",
    "fail":      "file",
}

# ── Known full-phrase templates (for difflib fallback) ────────────────────────
# These are all the phrases fast_match already handles, plus common LLM ones.
# Ordered from most to least common = doesn't matter (difflib is exhaustive).

_KNOWN_PHRASES = [
    "open chrome",
    "open brave",
    "open edge",
    "open notepad",
    "open spotify",
    "open vscode",
    "open youtube",
    "open discord",
    "open terminal",
    "open file manager",
    "search web",
    "search youtube",
    "search google",
    "create file",
    "read file",
    "close chrome",
    "open settings",
    "open calculator",
    "open paint",
    "open word",
    "open excel",
    "open powerpoint",
    "open whatsapp",
    "open telegram",
    "what time is it",
    "tell me a joke",
    "stop",
    "cancel",
]

# ── Normalise alias dicts (lowercase keys) ────────────────────────────────────

ACTION_ALIAS_MAP = {k.lower(): v for k, v in _RAW_ACTION_ALIASES.items()}
TARGET_ALIAS_MAP = {k.lower(): v for k, v in _RAW_TARGET_ALIASES.items()}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _correct_target(target_text: str) -> str:
    """
    Apply target alias corrections to the non-verb part of a command.
    Tries full match first, then word-by-word.
    """
    t = target_text.lower().strip()
    if not t:
        return target_text

    # Full target match (e.g. "note pad" → "notepad")
    if t in TARGET_ALIAS_MAP:
        return TARGET_ALIAS_MAP[t]

    # Word-by-word — correct individual words
    words = t.split()
    corrected = [TARGET_ALIAS_MAP.get(w, w) for w in words]
    return " ".join(corrected)


def _alias_correct(text: str):
    """
    Layer 1: alias table correction.
    Returns (corrected_text, was_corrected) or (text, False).

    Tries:
      a) 2-word action prefix then corrects the target
      b) 1-word action prefix then corrects the target
    """
    words = text.strip().lower().split()
    if not words:
        return text, False

    for prefix_len in (2, 1):
        if len(words) < prefix_len:
            continue
        prefix = " ".join(words[:prefix_len])
        if prefix in ACTION_ALIAS_MAP:
            canonical_verb = ACTION_ALIAS_MAP[prefix]
            remainder      = words[prefix_len:]
            corrected_tail = _correct_target(" ".join(remainder))
            result = (canonical_verb + " " + corrected_tail).strip()
            return result, result != text
    return text, False


def _fuzzy_correct(text: str):
    """
    Layer 2: difflib full-phrase fuzzy match against _KNOWN_PHRASES.
    Returns (best_match, was_corrected) or (text, False).
    """
    matches = difflib.get_close_matches(
        text.lower(),
        _KNOWN_PHRASES,
        n=1,
        cutoff=FUZZY_THRESHOLD,
    )
    if matches:
        best = matches[0]
        ratio = difflib.SequenceMatcher(None, text.lower(), best).ratio()
        log.debug(f"[CORRECT] difflib match: {text!r} → {best!r}  ratio={ratio:.2f}")
        return best, True
    return text, False


# ── Public API ────────────────────────────────────────────────────────────────

def correct_text(text: str) -> tuple:
    """
    Apply STT correction to raw transcript text.

    Returns:
        (corrected_text: str, was_corrected: bool)

    Correction only applied when confidence is high (alias table = certain;
    difflib = above FUZZY_THRESHOLD). If nothing matches, original text returned.
    """
    if not text or not text.strip():
        return text, False

    original = text.strip()

    # Layer 1 — alias table (deterministic)
    result, changed = _alias_correct(original)
    if changed:
        log.info(f"[CORRECT] Alias: {original!r} -> {result!r}")
        return result, True

    # Layer 2 — difflib fuzzy fallback
    result, changed = _fuzzy_correct(original)
    if changed:
        log.info(f"[CORRECT] Fuzzy: {original!r} -> {result!r}")
        return result, True

    return original, False
