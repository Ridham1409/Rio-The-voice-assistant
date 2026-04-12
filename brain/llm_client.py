"""
RIO v1 — brain/llm_client.py
Sends messages to Ollama /api/chat.

Timeout strategy (tiered for speed):
  Attempt 1: fast_timeout (20s) — returns instant fallback if exceeded
  Attempt 2: full timeout  (90s) — raises RuntimeError if exceeded
"""

import requests
from core.logger import get_logger

log = get_logger(__name__)

# FIX: updated from /api/generate (deprecated) to /api/chat (current)
OLLAMA_URL = "http://localhost:11434/api/chat"


def ask(prompt, cfg: dict) -> str:
    """
    Send a message to Ollama /api/chat. Returns the response text.

    Args:
        prompt: Either a list of message dicts (preferred, uses system role)
                or a plain str (wrapped as a single user message).
        cfg:    Loaded config dict.

    Raises:
        ConnectionError: Ollama is not running.
        RuntimeError:    Bad/timeout response.
    """
    llm_cfg      = cfg.get("llm", {})
    fast_timeout = llm_cfg.get("fast_timeout", 20)  # snappy first attempt
    full_timeout = llm_cfg.get("timeout", 90)        # patient retry

    # Accept pre-built messages list OR legacy plain string
    if isinstance(prompt, list):
        messages = prompt
    else:
        messages = [{"role": "user", "content": str(prompt)}]

    payload = {
        "model":    llm_cfg.get("model", "mistral"),
        "messages": messages,
        "stream":   False,
        "options": {
            "temperature": llm_cfg.get("temperature", 0.0),
            "num_predict": llm_cfg.get("max_tokens", 60),
        },
    }

    for attempt in (1, 2):
        # Tiered timeout: fast on first attempt, full on retry
        timeout = fast_timeout if attempt == 1 else full_timeout
        try:
            log.info(f"[LLM] Asking (attempt {attempt}, timeout={timeout}s)...")
            resp = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            text = (
                data.get("message", {}).get("content", "")
                or data.get("response", "")
            ).strip()
            log.info(f"[LLM] Reply: {text[:80]}")
            return text

        except requests.exceptions.ConnectionError:
            raise ConnectionError(
                "Cannot reach Ollama. Is it running?\n"
                "  → Start it with:  ollama serve"
            )

        except requests.exceptions.Timeout:
            if attempt == 1:
                # First attempt timed out — return an instant fallback
                # The user sees a response immediately; they can retry the command.
                log.warning(f"[LLM] Fast timeout ({fast_timeout}s) hit — returning quick fallback.")
                return '{"action":"respond","input":"Still processing — model is busy. Please try again."}'
            raise RuntimeError("Ollama timed out twice. Try a smaller model or increase timeout.")

        except Exception as e:
            raise RuntimeError(f"LLM error: {e}")

    return ""
