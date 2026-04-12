"""
RIO v1 — brain/prompt_engine.py

Forces the LLM to return ONLY strict JSON.
The system prompt is sent as a dedicated 'system' role message
so the model treats it as hard instructions, not user text.
"""

# ── System Prompt ──────────────────────────────────────────────────────────────
# Keep it short and authoritative. Long prompts get "forgotten" mid-response.

SYSTEM_PROMPT = """\
JSON-only response. No text. No explanation. Output ONLY raw JSON.

FORMAT: {"action":"...","input":"..."}
MULTI (max 3 tasks): {"steps":[{"action":"...","input":"..."},{"action":"...","input":"..."}]}

ACTIONS: open_app | search_web | create_file | read_file | respond | none
FALLBACK: {"action":"none","input":""}

EXAMPLES:
open chrome → {"action":"open_app","input":"chrome"}
search AI news → {"action":"search_web","input":"AI news"}
create file x.txt with hello → {"action":"create_file","input":"x.txt|hello"}
read notes.txt → {"action":"read_file","input":"notes.txt"}
open chrome and search AI → {"steps":[{"action":"open_app","input":"chrome"},{"action":"search_web","input":"AI"}]}
what is 2+2 → {"action":"respond","input":"4"}
"""


def build_messages(user_message: str) -> list:
    """
    Return a proper Ollama /api/chat messages array.

    Using a dedicated 'system' role ensures the model treats
    the instructions as hard constraints, not user dialogue.
    """
    return [
        {"role": "system",    "content": SYSTEM_PROMPT},
        {"role": "assistant", "content": "{"},                # prime the model to start with {
        {"role": "user",      "content": user_message},
    ]


def build_prompt(user_message: str) -> str:
    """
    Legacy shim — kept for backward compatibility.
    Returns the system prompt + user message as a plain string.
    Prefer build_messages() for /api/chat calls.
    """
    return f"{SYSTEM_PROMPT}\nUser: {user_message}\n"
