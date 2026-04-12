"""
RIO v1 — brain/parser.py
Parses the LLM's JSON response with multiple fallback strategies.
Always returns a safe dict — NEVER raises — NEVER crashes.
"""

import json
import re
from core.logger import get_logger

log = get_logger(__name__)

VALID_ACTIONS = {"open_app", "search_web", "create_file", "read_file", "respond", "none"}


def parse(text: str) -> dict:
    """
    Extract {"action": str, "input": str} from LLM output.

    Strategies tried in order:
      1. Direct json.loads
      2. Extract first {...} block with regex
      3. Fix common issues (trailing comma, single quotes) and retry
      4. Hardcoded fallback to "respond"

    Returns: {"action": str, "input": str}
    """
    # Guard: None or non-string input
    if text is None:
        log.warning("parse() received None — returning none fallback.")
        return _none_fallback()
    if not isinstance(text, str):
        text = str(text)
    text = text.strip()
    if not text:
        log.warning("parse() received empty string — returning none fallback.")
        return _none_fallback()

    # Strategy 1: direct parse
    result = _try_parse(text)
    if result:
        return _validate(result)

    # Strategy 2: grab first {...} block
    match = re.search(r"\{[^{}]+\}", text, re.DOTALL)
    if match:
        result = _try_parse(match.group())
        if result:
            return _validate(result)

    # Strategy 3: light fixes
    fixed = re.sub(r",\s*}", "}", text)        # trailing comma
    fixed = fixed.replace("'", '"')             # single → double quotes
    match = re.search(r"\{[^{}]+\}", fixed, re.DOTALL)
    if match:
        result = _try_parse(match.group())
        if result:
            return _validate(result)

    # Strategy 4: none fallback
    log.warning(f"Could not parse JSON from: '{text[:80]}' — using none fallback.")
    return _none_fallback()


def _try_parse(text: str):
    try:
        result = json.loads(text)
        # Must be a dict — lists/ints/strings are rejected
        if not isinstance(result, dict):
            log.debug(f"JSON parsed but is {type(result).__name__}, not dict — rejecting.")
            return None
        return result
    except (json.JSONDecodeError, ValueError):
        return None
    except Exception as e:
        log.debug(f"_try_parse unexpected error: {e}")
        return None


def _validate(data: dict) -> dict:
    """Ensure both required keys exist and action is valid."""
    try:
        action = str(data.get("action") or "none").strip().lower()
        inp    = str(data.get("input")  or "").strip()

        if action not in VALID_ACTIONS:
            log.warning(f"Unknown action '{action}' from LLM — falling back to none.")
            return _none_fallback()

        # "none" action: use "response" key if present, else generic message
        if action == "none":
            msg = str(data.get("response") or inp or "I didn't understand that command.")
            return {"action": "none", "input": msg}

        return {"action": action, "input": inp}
    except Exception as e:
        log.error(f"_validate crashed ({e}) — returning none fallback.")
        return _none_fallback()


def _none_fallback() -> dict:
    """Standard 'did not understand' response — always safe."""
    return {"action": "none", "input": "I didn't understand that command."}
