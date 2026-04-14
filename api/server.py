"""
RIO v1 — api/server.py
FastAPI bridge: browser UI ↔ Python assistant core.

Endpoints:
  GET  /              → serves frontend index.html
  GET  /health        → liveness check
  POST /chat          → text command { "message" } → { "response" }
  POST /voice/trigger → starts a server-side listen → process → speak cycle
  WS   /ws/state      → real-time state push to connected UIs

State machine:
  idle → listening → processing → speaking → idle
"""

import asyncio
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml
import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core.logger import get_logger
from brain       import ask, build_messages, parse, fast_match
from brain.fast_match import is_stop_command
from brain.corrector  import correct_text

from agent       import execute_steps

log = get_logger("api")

# ── Config ────────────────────────────────────────────────────────────────────

def _load_cfg() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

CFG = _load_cfg()

# ── Global state ──────────────────────────────────────────────────────────────

_state:           str              = "idle"
_ws_clients:      set[WebSocket]   = set()
_voice_lock:      asyncio.Lock     = None      # created inside event loop
_interrupt_event: threading.Event  = threading.Event()  # stops TTS + voice session
_wake_detector                     = None
_event_loop:      asyncio.AbstractEventLoop = None


# ── State broadcast ───────────────────────────────────────────────────────────

async def set_state(state: str) -> None:
    """Update _state and push to all connected WebSocket clients."""
    global _state
    _state = state
    dead = set()
    for ws in _ws_clients.copy():
        try:
            await ws.send_json({"state": state})
        except Exception:
            dead.add(ws)
    _ws_clients -= dead


# ── Voice pipeline (async, runs on event loop) ────────────────────────────────

def _process_text_sync(text: str) -> str:
    """Synchronous text → result. Runs in thread pool — must never raise."""
    try:
        # Layer 0: STT correction (phonetic mishearing fix)
        corrected, was_fixed = correct_text(text)
        if was_fixed:
            log.info(f"[CORRECT] {text!r} → {corrected!r}")
            text = corrected

        # Layer 1: fast regex match (< 1ms, no LLM)
        intent = fast_match(text)
        if intent is not None:
            log.info("[FLOW] fast_match hit — skipping LLM")
            return execute_steps(intent, CFG)

        # Layer 2: LLM
        log.info(f"[FLOW] Sending to LLM: {text!r}")
        messages = build_messages(text)
        raw      = ask(messages, CFG)
        intent   = parse(raw)
        return execute_steps(intent, CFG)

    except ConnectionError:
        log.error("[FLOW] Ollama not reachable — is 'ollama serve' running?")
        return "I can't reach the AI model right now. Please start Ollama and try again."
    except Exception as e:
        log.error(f"[FLOW] Pipeline error: {e}", exc_info=True)
        return "Something went wrong while processing your command. Please try again."


async def run_voice_pipeline(
    loop:          asyncio.AbstractEventLoop,
    pre_listening: bool = False,
) -> str:
    """
    Full listen → process → speak cycle.
    Must be called while holding _voice_lock.
    GUARANTEED to return and reset state to idle, even if a component crashes.
    """
    from voice.stt import listen as stt_listen
    from voice.tts import speak   as tts_speak

    _interrupt_event.clear()
    log.info("[FLOW] ---- Voice session started ----")

    try:
        # 1 — Record
        if not pre_listening:
            await set_state("listening")
        try:
            text = await loop.run_in_executor(None, lambda: stt_listen(duration=5.0))
        except Exception as e:
            log.error(f"[VOICE] STT failed: {e}", exc_info=True)
            await set_state("idle")
            return ""

        if not text.strip():
            log.info("[FLOW] No speech — session ended.")
            await set_state("idle")
            return ""

        log.info(f"[FLOW] Heard: {text!r}")

        # 2 — Stop command check
        if is_stop_command(text):
            log.info("[FLOW] Stop command — aborting session.")
            _interrupt_event.set()
            await set_state("idle")
            return ""

        # 3 — Process
        await set_state("processing")
        if _interrupt_event.is_set():
            log.info("[FLOW] Interrupted before processing.")
            await set_state("idle")
            return ""
        try:
            result = await loop.run_in_executor(None, _process_text_sync, text)
        except Exception as e:
            log.error(f"[VOICE] Processing failed: {e}", exc_info=True)
            result = "Sorry, something went wrong while processing your command."

        # 4 — Speak
        if not _interrupt_event.is_set() and result:
            await set_state("speaking")
            try:
                await loop.run_in_executor(
                    None,
                    lambda: tts_speak(result, extra_stop=_interrupt_event),
                )
            except Exception as e:
                log.error(f"[VOICE] TTS failed: {e}", exc_info=True)
        elif _interrupt_event.is_set():
            log.info("[FLOW] Interrupted before speaking.")

        return result

    except Exception as e:
        # Outer safety net — should never reach here, but guarantees state reset
        log.error(f"[VOICE] Unexpected pipeline crash: {e}", exc_info=True)
        return ""
    finally:
        # ALWAYS reset state, even if an exception escaped all inner handlers
        await set_state("idle")
        log.info("[FLOW] ---- Voice session ended ----")


# ── Wake word callback (called from background thread) ────────────────────────

def _interrupt_fn():
    """
    Stop any ongoing TTS and signal the voice session to abort.
    Called by WakeWordDetector just before firing on_wake(),
    allowing wake word to interrupt speaking.
    """
    from voice.tts import stop_speaking
    _interrupt_event.set()
    stop_speaking()
    log.info("[WAKE] Interrupt sent before new session.")


def _on_wake():
    """Dispatched from WakeWordDetector daemon thread → async event loop."""
    global _event_loop, _voice_lock
    if _event_loop is None or _voice_lock is None:
        return
    if _voice_lock.locked():
        log.debug("[WAKE] Voice already active — ignoring trigger.")
        return

    # ── IMMEDIATE UI feedback — fires before pipeline even starts ──────────────
    # set_state pushes {"state": "listening"} to every WebSocket client right
    # now, so the UI animation starts at wake-word detection, not after the
    # lock is acquired and listen() begins.
    asyncio.run_coroutine_threadsafe(set_state("listening"), _event_loop)
    log.info("[WAKE] UI notified: listening (pre-pipeline)")

    # Now schedule the full pipeline (will re-use the listening state)
    asyncio.run_coroutine_threadsafe(_handle_wake(), _event_loop)


async def _handle_wake():
    global _voice_lock
    if _voice_lock.locked():
        return
    async with _voice_lock:
        loop = asyncio.get_event_loop()
        await run_voice_pipeline(loop, pre_listening=True)  # state already emitted


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _voice_lock, _event_loop, _wake_detector
    _voice_lock  = asyncio.Lock()
    _event_loop  = asyncio.get_event_loop()

    # Optionally start wake word detector
    try:
        from voice.wake_word import WakeWordDetector
        _wake_detector = WakeWordDetector(on_wake=_on_wake, interrupt_fn=_interrupt_fn)
        _wake_detector.start()
    except Exception as e:
        log.warning(f"[WAKE] Wake word disabled (mic/deps issue): {e}")

    yield   # ← server runs here

    if _wake_detector:
        _wake_detector.stop()


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title       = "RIO Assistant API",
    description = "Responsive Intelligent Operator — local AI assistant",
    version     = "1.1.0",
    lifespan    = lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins  = ["*"],
    allow_methods  = ["*"],
    allow_headers  = ["*"],
)

frontend_dir = ROOT / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


# ── Pydantic models ───────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    response: str
    source:   str = "llm"


# ── HTTP Routes ───────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def serve_ui():
    html = frontend_dir / "index.html"
    if html.exists():
        return FileResponse(str(html))
    return {"status": "RIO API running — no frontend at /frontend/index.html"}


@app.get("/health")
async def health():
    return {"status": "ok", "model": CFG.get("llm", {}).get("model", "unknown"), "state": _state}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    text = req.message.strip()
    if not text:
        # Return safe response instead of HTTP 400
        return ChatResponse(response="Please type a command.", source="error")

    log.info(f"[API] /chat: {text!r}")

    # ── Instant stop command ─────────────────────────────────────────────────────────
    if is_stop_command(text):
        from voice.tts import stop_speaking
        _interrupt_event.set()
        stop_speaking()
        await set_state("idle")
        return ChatResponse(response="Okay, stopping.", source="fast")

    await set_state("processing")

    try:
        # STT correction (also helps typed typos against known commands)
        corrected, was_fixed = correct_text(text)
        if was_fixed:
            log.info(f"[CORRECT] {text!r} → {corrected!r}")
            text = corrected

        # Fast-match path
        intent = fast_match(text)
        if intent is not None:
            result = execute_steps(intent, CFG)
            await set_state("idle")
            return ChatResponse(response=result, source="fast")

        # LLM path
        loop     = asyncio.get_event_loop()
        messages = build_messages(text)
        try:
            raw = await loop.run_in_executor(None, lambda: ask(messages, CFG))
        except ConnectionError:
            log.error("[API] Ollama not reachable.")
            await set_state("idle")
            return ChatResponse(
                response="I can't reach the AI model. Is Ollama running? Start with: ollama serve",
                source="error",
            )

        try:
            intent = parse(raw)
        except Exception as e:
            log.error(f"[API] Parse failed: {e}  raw={raw!r}")
            await set_state("idle")
            return ChatResponse(response="I received an unexpected response. Please try again.", source="error")

        result = execute_steps(intent, CFG)
        log.info(f"[API] Result: {result!r}")
        await set_state("idle")
        return ChatResponse(response=result, source="llm")

    except Exception as e:
        # Catch-all: log full traceback, return safe message, never raise 500
        log.error(f"[API] Unhandled error in /chat: {e}", exc_info=True)
        await set_state("idle")
        return ChatResponse(response="Something went wrong. Please try again.", source="error")


@app.post("/voice/trigger")
async def voice_trigger():
    """Manually trigger voice recording from the mic button in the UI."""
    global _voice_lock
    if _voice_lock is None:
        log.error("[API] /voice/trigger called before voice system initialised.")
        return {"status": "error", "response": "Voice system not yet ready. Try again in a moment."}

    if _voice_lock.locked():
        return {"status": "busy", "response": "A voice session is already active."}

    try:
        async with _voice_lock:
            loop   = asyncio.get_event_loop()
            result = await run_voice_pipeline(loop)
        return {"status": "ok", "response": result}
    except Exception as e:
        log.error(f"[API] /voice/trigger crashed: {e}", exc_info=True)
        await set_state("idle")   # guarantee state reset
        return {"status": "error", "response": "Voice processing failed. Please try again."}


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws/state")
async def ws_state(websocket: WebSocket):
    """Push real-time state updates to connected browser clients."""
    await websocket.accept()
    _ws_clients.add(websocket)
    # Send current state immediately on connect
    await websocket.send_json({"state": _state})
    try:
        while True:
            # Keep-alive ping every 20 seconds; receive any client message
            await asyncio.wait_for(websocket.receive_text(), timeout=20.0)
    except asyncio.TimeoutError:
        await websocket.send_json({"ping": True})   # keep-alive
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(websocket)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    api_cfg = CFG.get("api", {})
    host    = api_cfg.get("host", "127.0.0.1")
    port    = api_cfg.get("port", 8000)

    print(f"\n  RIO API Server v1.1 starting...")
    print(f"  -> UI:      http://{host}:{port}/")
    print(f"  -> Chat:    http://{host}:{port}/chat")
    print(f"  -> Voice:   http://{host}:{port}/voice/trigger")
    print(f"  -> WS:      ws://{host}:{port}/ws/state")
    print(f"  -> Docs:    http://{host}:{port}/docs")
    print(f"  -> Model:   {CFG.get('llm', {}).get('model', 'unknown')}\n")

    uvicorn.run(app, host=host, port=port, log_level="warning")
