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
        dict  — single intent   {"action": str, "input": str}
        list  — multi-step      [{"action": ...}, ...]
        None  — no match found (caller should fall through to LLM)
    """
    text = text.strip()
    if not text:
        return None

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
