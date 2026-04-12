"""
RIO v1 — main.py
Minimal text-mode voice assistant.

Pipeline (per command):
  User types → prompt built → LLM called → JSON parsed → action executed → result printed

Run:
    python main.py
"""

import sys
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    try:
        import yaml
        with open(Path(__file__).parent / "config.yaml", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        print("[ERROR] config.yaml not found.")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Could not load config: {e}")
        sys.exit(1)


# ── Main Loop ─────────────────────────────────────────────────────────────────

def main():
    cfg = load_config()

    from core.logger    import get_logger
    from brain          import ask, build_messages, parse
    from agent          import execute_steps

    log = get_logger("rio")

    # ── Startup check: is Ollama reachable? ───────────────────────────────
    try:
        import requests as _r
        _r.get("http://localhost:11434/api/tags", timeout=2)
        log.info("Ollama reachable ✓")
    except Exception:
        print("\n  [WARNING] Cannot reach Ollama at localhost:11434.")
        print("  Start it with:  ollama serve")
        print("  Then pull a model:  ollama pull llama3")
        print("  (Continuing anyway — commands will fail until Ollama is running)\n")

    print("\n  ╔══════════════════════════════╗")
    print("  ║   RIO v1 — Text Assistant   ║")
    print("  ║  Type a command or 'exit'   ║")
    print("  ╚══════════════════════════════╝\n")

    while True:
        # ── Get user input ────────────────────────────────────────────────────
        try:
            user_input = input("  You > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Goodbye!")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit", "bye"):
            print("  RIO > Goodbye!")
            break

        # ── Build prompt ────────────────────────────────────────────
        log.info(f"[INPUT] {user_input!r}")

        try:
            # Build messages list with system + user roles
            messages = build_messages(user_input)

            # ── Call LLM ─────────────────────────────────────────
            try:
                raw = ask(messages, cfg)
            except ConnectionError as e:
                print(f"\n  [ERROR] {e}\n")
                log.error(f"[LLM] Connection failed: {e}")
                continue
            except RuntimeError as e:
                print(f"\n  [ERROR] {e}\n")
                log.error(f"[LLM] Runtime error: {e}")
                continue

            # ── Parse JSON ─────────────────────────────────────────
            intent = parse(raw)
            log.info(f"[INTENT] {intent}")

            # ── Execute action ───────────────────────────────────────
            result = execute_steps(intent, cfg)
            log.info(f"[RESULT] {result!r}")

        except Exception as e:
            # Top-level safety net — this should never trigger if modules are correct
            log.error(f"[FATAL] Unhandled error in pipeline: {e}", exc_info=True)
            result = "Something went wrong internally. Please try again."

        # ── Print result ───────────────────────────────────────────
        print(f"  RIO > {result}\n")


if __name__ == "__main__":
    main()
