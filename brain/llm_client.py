"""
RIO v1 — brain/llm_client.py
Sends messages to Ollama /api/chat and returns the raw text response.
Accepts either a pre-built messages list (preferred) or a plain string.
One retry on timeout. Raises on connection failure.
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
    llm_cfg = cfg.get("llm", {})

    # Accept pre-built messages list OR legacy plain string
    if isinstance(prompt, list):
        messages = prompt          # already has system + user roles
    else:
        messages = [{"role": "user", "content": str(prompt)}]

    payload = {
        "model":   llm_cfg.get("model", "mistral"),
        "messages": messages,
        "stream":  False,
        "options": {
            "temperature": llm_cfg.get("temperature", 0.1),
            "num_predict": llm_cfg.get("max_tokens", 200),
        },
    }
    timeout = llm_cfg.get("timeout", 30)

    for attempt in (1, 2):          # 1 retry only
        try:
            log.info(f"Asking LLM (attempt {attempt})...")
            resp = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
            resp.raise_for_status()
            # FIX: /api/chat response path is message.content, not top-level response
            data = resp.json()
            text = (
                data.get("message", {}).get("content", "")
                or data.get("response", "")   # fallback for older Ollama builds
            ).strip()
            log.info(f"LLM replied: {text[:80]}")
            return text
        except requests.exceptions.ConnectionError:
            raise ConnectionError(
                "Cannot reach Ollama. Is it running?\n"
                "  → Start it with:  ollama serve"
            )
        except requests.exceptions.Timeout:
            if attempt == 2:
                raise RuntimeError("Ollama timed out twice. Try a smaller model.")
            log.warning("Timeout — retrying once...")
        except Exception as e:
            raise RuntimeError(f"LLM error: {e}")

    return ""
