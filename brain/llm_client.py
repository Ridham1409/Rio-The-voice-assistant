"""
RIO v1 — brain/llm_client.py
Sends a prompt to Ollama and returns the raw text response.
One retry on timeout. Raises on connection failure.
"""

import requests
from core.logger import get_logger

log = get_logger(__name__)

# FIX: updated from /api/generate (deprecated) to /api/chat (current)
OLLAMA_URL = "http://localhost:11434/api/chat"


def ask(prompt: str, cfg: dict) -> str:
    """
    Send prompt to Ollama. Returns the response string.
    Raises ConnectionError if Ollama is not running.
    Raises RuntimeError on bad response.
    """
    llm_cfg = cfg.get("llm", {})

    # FIX: /api/chat expects a messages array, not a flat prompt string
    payload = {
        "model":   llm_cfg.get("model", "mistral"),
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "stream":  False,
        "options": {
            "temperature": llm_cfg.get("temperature", 0.1),
            "num_predict": llm_cfg.get("max_tokens", 150),
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
