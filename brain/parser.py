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


def parse(text: str):
    """
    Extract intent(s) from LLM output. Always safe — never raises.

    Returns EITHER:
      - dict  {"action": str, "input": str}          — single action
      - list  [{"action": str, "input": str}, ...]   — multi-step (from {"steps": [...]})

    Strategies tried in order:
      1. Direct json.loads
      2. Extract first {...} block with regex
      3. Fix common issues (trailing comma, single quotes) and retry
      4. Hardcoded none fallback
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
    """Try to parse text as JSON dict. Returns dict or None."""
    try:
        result = json.loads(text)
        # Accept dict — lists top-level are rejected (steps must be inside {})
        if not isinstance(result, dict):
            log.debug(f"JSON parsed but is {type(result).__name__}, not dict — rejecting.")
            return None
        return result
    except (json.JSONDecodeError, ValueError):
        return None
    except Exception as e:
        log.debug(f"_try_parse unexpected error: {e}")
        return None


def _validate(data: dict):
    """
    Validate parsed JSON. Returns:
      - list  if data has a 'steps' key  (multi-step command)
      - dict  otherwise                  (single-step command)
    """
    try:
        # ── Multi-step: {"steps": [...]} ────────────────────────────────
        if "steps" in data:
            return _validate_steps(data["steps"])

        # ── Single-step ─────────────────────────────────────────────
        action = str(data.get("action") or "none").strip().lower()
        inp    = str(data.get("input")  or "").strip()

        if action not in VALID_ACTIONS:
            log.warning(f"Unknown action '{action}' from LLM — falling back to none.")
            return _none_fallback()

        if action == "none":
            msg = str(data.get("response") or inp or "I didn't understand that command.")
            return {"action": "none", "input": msg}

        return {"action": action, "input": inp}
    except Exception as e:
        log.error(f"_validate crashed ({e}) — returning none fallback.")
        return _none_fallback()


def _validate_steps(raw_steps) -> list:
    """
    Validate a steps array from multi-step LLM output.
    - Must be a list of dicts
    - Max 3 steps enforced
    - Invalid individual steps are skipped (not crashed on)
    - If all steps invalid, falls back to none
    """
    if not isinstance(raw_steps, list) or not raw_steps:
        log.warning("[STEPS] 'steps' key exists but is not a non-empty list — fallback.")
        return [_none_fallback()]

    validated = []
    for i, step in enumerate(raw_steps[:3]):   # hard cap at 3
        if not isinstance(step, dict):
            log.warning(f"[STEPS] Step {i} is not a dict — skipping.")
            continue
        action = str(step.get("action") or "none").strip().lower()
        inp    = str(step.get("input")  or "").strip()
        if action not in VALID_ACTIONS:
            log.warning(f"[STEPS] Step {i} has unknown action '{action}' — skipping.")
            continue
        validated.append({"action": action, "input": inp})

    if not validated:
        log.warning("[STEPS] No valid steps found — fallback.")
        return [_none_fallback()]

    log.info(f"[STEPS] Validated {len(validated)} step(s).")
    return validated


def _none_fallback() -> dict:
    """Standard 'did not understand' response — always safe."""
    return {"action": "none", "input": "I didn't understand that command."}
