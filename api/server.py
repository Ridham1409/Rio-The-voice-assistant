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
from agent       import execute_steps

log = get_logger("api")

# ── Config ────────────────────────────────────────────────────────────────────

def _load_cfg() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

CFG = _load_cfg()

# ── Global state ──────────────────────────────────────────────────────────────

_state:       str              = "idle"
_ws_clients:  set[WebSocket]   = set()
_voice_lock:  asyncio.Lock     = None      # created inside event loop
_wake_detector                 = None
_event_loop:  asyncio.AbstractEventLoop = None


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
    """Synchronous text → result (runs in thread pool via run_in_executor)."""
    intent = fast_match(text)
    if intent is not None:
        return execute_steps(intent, CFG)
    try:
        messages = build_messages(text)
        raw      = ask(messages, CFG)
        intent   = parse(raw)
        return execute_steps(intent, CFG)
    except Exception as e:
        log.error(f"[VOICE] Pipeline error: {e}")
        return "Sorry, I couldn't process that command."


async def run_voice_pipeline(loop: asyncio.AbstractEventLoop) -> str:
    """
    Full listen → process → speak cycle.
    Must be called while holding _voice_lock.
    """
    from voice.stt import listen as stt_listen
    from voice.tts import speak   as tts_speak

    # 1 — Record
    await set_state("listening")
    text = await loop.run_in_executor(None, lambda: stt_listen(duration=5.0))
    log.info(f"[VOICE] Heard: {text!r}")

    if not text.strip():
        await set_state("idle")
        return ""

    # 2 — Process
    await set_state("processing")
    result = await loop.run_in_executor(None, _process_text_sync, text)
    log.info(f"[VOICE] Result: {result!r}")

    # 3 — Speak
    await set_state("speaking")
    await loop.run_in_executor(None, tts_speak, result)

    await set_state("idle")
    return result


# ── Wake word callback (called from background thread) ────────────────────────

def _on_wake():
    """Dispatched from WakeWordDetector daemon thread → async event loop."""
    global _event_loop, _voice_lock
    if _event_loop is None or _voice_lock is None:
        return
    if _voice_lock.locked():
        log.debug("[WAKE] Voice already active — ignoring trigger.")
        return
    asyncio.run_coroutine_threadsafe(_handle_wake(), _event_loop)


async def _handle_wake():
    global _voice_lock
    if _voice_lock.locked():
        return
    async with _voice_lock:
        loop = asyncio.get_event_loop()
        await run_voice_pipeline(loop)


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _voice_lock, _event_loop, _wake_detector
    _voice_lock  = asyncio.Lock()
    _event_loop  = asyncio.get_event_loop()

    # Optionally start wake word detector
    try:
        from voice.wake_word import WakeWordDetector
        _wake_detector = WakeWordDetector(on_wake=_on_wake)
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
        raise HTTPException(status_code=400, detail="message cannot be empty")

    log.info(f"[API] /chat: {text!r}")
    await set_state("processing")

    try:
        # Fast-match path
        intent = fast_match(text)
        if intent is not None:
            result = execute_steps(intent, CFG)
            await set_state("idle")
            return ChatResponse(response=result, source="fast")

        # LLM path
        loop     = asyncio.get_event_loop()
        messages = build_messages(text)
        raw      = await loop.run_in_executor(None, lambda: ask(messages, CFG))
        intent   = parse(raw)
        result   = execute_steps(intent, CFG)
        log.info(f"[API] Result: {result!r}")
        await set_state("idle")
        return ChatResponse(response=result, source="llm")

    except ConnectionError as e:
        await set_state("idle")
        raise HTTPException(status_code=503, detail="Ollama is not running. Start with: ollama serve")
    except Exception as e:
        await set_state("idle")
        log.error(f"[API] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error. Please try again.")


@app.post("/voice/trigger")
async def voice_trigger():
    """Manually trigger voice recording from the mic button in the UI."""
    global _voice_lock
    if _voice_lock is None:
        raise HTTPException(status_code=503, detail="Voice system not initialised.")
    if _voice_lock.locked():
        return {"status": "busy", "message": "Voice session already active."}
    async with _voice_lock:
        loop   = asyncio.get_event_loop()
        result = await run_voice_pipeline(loop)
    return {"status": "ok", "response": result}


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
