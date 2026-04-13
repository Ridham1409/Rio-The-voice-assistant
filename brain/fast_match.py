"""
RIO v1 — brain/fast_match.py

Instant local pattern matching — NO LLM, NO network call.
Handles the most common commands in <1ms via regex.

Returns intent dict on match, None if no pattern matches
(caller then falls through to LLM for complex requests).
"""

import re
from core.logger import get_logger

log = get_logger(__name__)

# ── Control commands (highest priority — no LLM needed) ───────────────────────
STOP_COMMANDS = {
    "stop", "cancel", "wait", "enough", "quiet", "silence",
    "shut up", "be quiet", "stop talking", "that's enough",
    "pause", "halt",
}
_STOP_RE = re.compile(
    r"^(?:please\s+)?(?:stop|cancel|wait|enough|quiet|silence|halt|pause|shut up|be quiet|stop talking)[\.!]*$",
    re.IGNORECASE,
)


def is_stop_command(text: str) -> bool:
    """Return True if text is a stop/cancel control command."""
    t = text.strip().lower().rstrip(".! ")
    return t in STOP_COMMANDS or bool(_STOP_RE.match(text.strip()))

# ── Pattern table ──────────────────────────────────────────────────────────────
# (compiled_regex, action, input_group)
# input_group: int → regex capture group, str → literal value
_RAW_PATTERNS = [
    # Open / Launch / Start app
    (r"^(?:open|launch|start|run)\s+(.+)$",         "open_app",    1),
    # Web search
    (r"^(?:search|google|find|look up)\s+(.+)$",    "search_web",  1),
    (r"^(?:search for|search about)\s+(.+)$",        "search_web",  1),
    # File creation
    (r"^(?:create|make|new) file (.+)$",             "create_file", 1),
    (r"^(?:create|make) a file (?:called|named) (.+)$", "create_file", 1),
    # File reading
    (r"^(?:read|open|show|cat) (?:file )?(.+\.(?:txt|md|log|csv|json|py))$",
                                                     "read_file",   1),
]

# Precompile all patterns at import time (zero cost per call)
_PATTERNS = [
    (re.compile(raw, re.IGNORECASE), action, group)
    for raw, action, group in _RAW_PATTERNS
]

# ── Multi-step fast shortcuts ──────────────────────────────────────────────────
# Detect "X and Y" compound commands before regex matching individual parts.
_AND_SPLIT = re.compile(
    r"\s+(?:and|then|also|&)\s+", re.IGNORECASE
)


def fast_match(text: str):
    """
    Instantly match common command patterns without LLM.

    Returns:
        dict  {"action": "stop", ...}  — immediate stop/cancel command
        dict  {"action": str, ...}     — single intent
        list  [{...}, ...]             — multi-step
        None  — no match found (caller should fall through to LLM)
    """
    text = text.strip()
    if not text:
        return None

    # ── HIGHEST PRIORITY: stop / cancel commands ──────────────────────────────
    if is_stop_command(text):
        log.info(f"[FAST] Stop command: {text!r}")
        return {"action": "stop", "input": ""}

    # ── Try multi-step split first ───────────────────────────────────────────
    parts = _AND_SPLIT.split(text)
    if len(parts) >= 2:
        steps = []
        for part in parts[:3]:          # cap at 3
            intent = _match_single(part.strip())
            if intent:
                steps.append(intent)
        if len(steps) == len(parts[:3]) and steps:
            # All parts matched → return as steps list
            log.info(f"[FAST] Multi-step match: {len(steps)} step(s)")
            return steps if len(steps) > 1 else steps[0]

    # ── Try single pattern ────────────────────────────────────────────────────
    result = _match_single(text)
    if result:
        log.info(f"[FAST] Single match: action={result['action']!r}")
        return result

    return None     # no match — use LLM


def _match_single(text: str):
    """Match one command against the pattern table. Returns dict or None."""
    for pattern, action, group in _PATTERNS:
        m = pattern.match(text)
        if m:
            value = m.group(group).strip() if isinstance(group, int) else group
            return {"action": action, "input": value}
    return None
