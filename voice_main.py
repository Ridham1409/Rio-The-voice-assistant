"""
RIO v1 — voice_main.py
Voice-mode entry point.

Usage:
    py -3 voice_main.py

Controls:
    Press ENTER  → speak for up to RECORD_SECONDS seconds
    Press CTRL+C → exit

Pipeline:
    [ENTER] → mic → faster-whisper → text → fast_match / LLM → pyttsx3 → voice
"""

import sys
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

RECORD_SECONDS = 5      # max recording window per command

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


# ── Voice Main Loop ────────────────────────────────────────────────────────────

def main():
    cfg = load_config()

    from core.logger import get_logger
    from brain       import ask, build_messages, parse, fast_match
    from agent       import execute_steps
    from voice       import listen, speak

    log = get_logger("rio.voice")

    # ── Startup check ──────────────────────────────────────────────────────────
    try:
        import requests as _r
        _r.get("http://localhost:11434/api/tags", timeout=2)
        log.info("Ollama reachable.")
    except Exception:
        print("\n  [WARNING] Ollama not reachable. Text commands with LLM will fail.")
        print("  Run: ollama serve\n")

    print("\n  ╔══════════════════════════════════════╗")
    print("  ║   RIO v1 — Voice Mode               ║")
    print("  ║   Press ENTER to speak (5 seconds)  ║")
    print("  ║   Press CTRL+C to exit              ║")
    print("  ╚══════════════════════════════════════╝\n")

    speak("RIO voice mode active. Press Enter to speak a command.")

    while True:
        try:
            input("  [Press ENTER to speak] ")
        except (EOFError, KeyboardInterrupt):
            print("\n  RIO > Goodbye!")
            speak("Goodbye.")
            break

        print(f"  [Listening for {RECORD_SECONDS} seconds...] Speak now!")

        # ── Step 1: Record + transcribe ───────────────────────────────────────
        user_text = listen(duration=RECORD_SECONDS)

        if not user_text.strip():
            msg = "Sorry, I didn't catch that. Please try again."
            print(f"  RIO > {msg}")
            speak(msg)
            continue

        print(f"  You  > {user_text}")
        log.info(f"[VOICE INPUT] {user_text!r}")

        if user_text.lower().strip() in ("exit", "quit", "bye", "stop"):
            print("  RIO > Goodbye!")
            speak("Goodbye!")
            break

        # ── Step 2: Fast-match or LLM ─────────────────────────────────────────
        try:
            intent = fast_match(user_text)

            if intent is not None:
                log.info("[FAST] Pattern match — skipping LLM.")
                result = execute_steps(intent, cfg)
            else:
                messages = build_messages(user_text)
                try:
                    raw    = ask(messages, cfg)
                    intent = parse(raw)
                    result = execute_steps(intent, cfg)
                except ConnectionError as e:
                    result = f"I can't reach the AI engine. {e}"
                except RuntimeError as e:
                    result = f"Processing error: {e}"

        except Exception as e:
            log.error(f"[VOICE] Unhandled error: {e}", exc_info=True)
            result = "Something went wrong. Please try again."

        # ── Step 3: Print + Speak result ──────────────────────────────────────
        print(f"  RIO  > {result}\n")
        log.info(f"[RESULT] {result!r}")
        speak(result)


if __name__ == "__main__":
    main()
