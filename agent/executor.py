"""
RIO v1 — agent/executor.py
The ENTIRE agent logic in one simple function.

Flow:
  intent dict → dispatch to action function → return result string

No planning, no retries, no multi-step loops.
Uses a plain if/elif dispatch instead of a registry.
"""

from core.logger import get_logger
import actions.app_control as _app
import actions.web_search  as _web
import actions.file_ops    as _files

log = get_logger(__name__)

# Maximum allowed lengths to prevent garbage input
_MAX_INPUT_LEN = 500


def _guard(value: str, action: str) -> str | None:
    """
    Validate the input string before passing it to an action.
    Returns None if input is safe, or an error message string if invalid.
    """
    if not value or not value.strip():
        return f"Empty input for action '{action}'. Please provide a value."
    if len(value) > _MAX_INPUT_LEN:
        return f"Input too long ({len(value)} chars). Max is {_MAX_INPUT_LEN}."
    return None  # safe


def execute(intent: dict, cfg: dict) -> str:
    """
    Execute one action and return a result string.

    Args:
        intent: {"action": str, "input": str}
        cfg:    loaded config dict

    Returns:
        Human-readable result string.
    """
    action = (intent.get("action") or "none").strip()
    value  = str(intent.get("input")  or "").strip()

    log.info(f"[CMD] action={action!r}  input={value!r}")

    # ── none: LLM did not understand the command ──────────────────────────────
    if action == "none":
        msg = value or "I didn't understand that command."
        log.info(f"[SAFE] Returning none response: {msg!r}")
        return msg

    # ── open_app ──────────────────────────────────────────────────────────────
    if action == "open_app":
        err = _guard(value, action)
        if err:
            log.warning(f"[GUARD] {err}")
            return err
        try:
            return _app.open_app(value, cfg)
        except Exception as e:
            log.error(f"[ERROR] open_app failed: {e}")
            return "Action failed safely: could not open app."

    # ── search_web ────────────────────────────────────────────────────────────
    elif action == "search_web":
        err = _guard(value, action)
        if err:
            log.warning(f"[GUARD] {err}")
            return err
        try:
            return _web.search_web(value, cfg)
        except Exception as e:
            log.error(f"[ERROR] search_web failed: {e}")
            return "Action failed safely: could not open browser."

    # ── create_file ───────────────────────────────────────────────────────────
    elif action == "create_file":
        err = _guard(value, action)
        if err:
            log.warning(f"[GUARD] {err}")
            return err
        try:
            return _files.create_file(value, cfg)
        except Exception as e:
            log.error(f"[ERROR] create_file failed: {e}")
            return "Action failed safely: could not create file."

    # ── read_file ─────────────────────────────────────────────────────────────
    elif action == "read_file":
        err = _guard(value, action)
        if err:
            log.warning(f"[GUARD] {err}")
            return err
        try:
            return _files.read_file(value, cfg)
        except Exception as e:
            log.error(f"[ERROR] read_file failed: {e}")
            return "Action failed safely: could not read file."

    # ── respond (LLM text-only reply) ─────────────────────────────────────────
    elif action == "respond":
        return value or "(no response)"

    # ── unknown action ────────────────────────────────────────────────────────
    else:
        log.warning(f"[GUARD] Unrecognised action after parse: {action!r}")
        return "I didn't understand that command."
