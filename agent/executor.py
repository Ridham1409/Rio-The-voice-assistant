"""
RIO v1 — agent/executor.py
Dispatches single or multi-step intents to action functions.

Flow (single):  intent dict → execute()       → result str
Flow (multi):   intent list → execute_steps() → combined result str

Max 3 sequential steps. No retries. No complex reasoning.
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

def execute_steps(intent, cfg: dict) -> str:
    """
    Entry point for both single and multi-step commands.

    Args:
        intent: dict  → single action  {"action": str, "input": str}
                list  → multi-step     [{...}, {...}, ...]
        cfg:    loaded config dict

    Returns:
        A combined, human-readable result string.
        Each step result is on its own line for multi-step commands.
    """
    # Normalize: single dict → wrap in list
    if isinstance(intent, dict):
        steps = [intent]
    elif isinstance(intent, list):
        steps = intent[:3]      # enforce max 3 even if parser missed it
    else:
        log.warning(f"[STEPS] Unexpected intent type: {type(intent)} — falling back.")
        return "I didn't understand that command."

    if not steps:
        return "I didn't understand that command."

    log.info(f"[STEPS] Executing {len(steps)} step(s).")

    results = []
    for i, step in enumerate(steps, 1):
        log.info(f"[STEPS] Step {i}/{len(steps)}")
        result = execute(step, cfg)
        results.append(result)

    # Single step → plain result. Multi-step → numbered list.
    if len(results) == 1:
        return results[0]
    return "\n".join(f"Step {i}: {r}" for i, r in enumerate(results, 1))



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

    # ── stop / cancel / wait — interrupt control ──────────────────────────────
    # fast_match returns action="stop" for control commands.
    # The server handles TTS interrupt directly; executor just returns silently.
    elif action in ("stop", "cancel", "wait"):
        log.info(f"[CMD] Control command: {action!r} — interrupting.")
        return ""       # empty: server suppresses output for stop commands

    # ── unknown action ────────────────────────────────────────────────────────
    else:
        log.warning(f"[GUARD] Unrecognised action after parse: {action!r}")
        return "I didn't understand that command."
