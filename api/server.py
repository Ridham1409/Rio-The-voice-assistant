"""
RIO v1 — api/server.py
FastAPI bridge between the browser frontend and the Python assistant core.

Endpoint:
  POST /chat  { "message": "text" } → { "response": "text" }

Run with:
  python api/server.py
  — or via main.py using the --api flag (future)
"""

import sys
from pathlib import Path

# Ensure project root is importable
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core.logger      import get_logger
from brain            import ask, build_messages, parse, fast_match
from agent            import execute_steps

log = get_logger("api")

# ── Load config ───────────────────────────────────────────────────────────────

def _load_cfg() -> dict:
    cfg_path = ROOT / "config.yaml"
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

CFG = _load_cfg()

# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="RIO Assistant API",
    description="Responsive Intelligent Operator — local AI assistant",
    version="1.0.0",
)

# Allow browsers to call this API (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # fine for local use
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the frontend from /  (so browser can open http://localhost:8000)
frontend_dir = ROOT / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


# ── Models ────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    response: str
    source: str = "llm"        # "fast" | "llm" — for debugging


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def serve_ui():
    """Serve the frontend index.html at root."""
    html = frontend_dir / "index.html"
    if html.exists():
        return FileResponse(str(html))
    return {"status": "RIO API is running. No frontend found at /frontend/index.html"}


@app.get("/health")
async def health():
    """Quick liveness check."""
    return {"status": "ok", "model": CFG.get("llm", {}).get("model", "unknown")}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """
    Main chat endpoint.
    1. Try fast local pattern match (instant, no LLM).
    2. Fall back to LLM if no pattern matched.
    Returns the assistant's plain-text response.
    """
    text = req.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="message cannot be empty")

    log.info(f"[API] Received: {text!r}")

    # ── Fast path ──────────────────────────────────────────────────────────────
    intent = fast_match(text)
    if intent is not None:
        log.info("[API] Fast-match hit — skipping LLM")
        result = execute_steps(intent, CFG)
        return ChatResponse(response=result, source="fast")

    # ── LLM path ───────────────────────────────────────────────────────────────
    try:
        messages = build_messages(text)
        raw      = ask(messages, CFG)
        intent   = parse(raw)
        result   = execute_steps(intent, CFG)
        log.info(f"[API] Result: {result!r}")
        return ChatResponse(response=result, source="llm")

    except ConnectionError as e:
        log.error(f"[API] Ollama not reachable: {e}")
        raise HTTPException(status_code=503, detail="Ollama is not running. Start it with: ollama serve")
    except Exception as e:
        log.error(f"[API] Unexpected error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error. Please try again.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    api_cfg = CFG.get("api", {})
    host = api_cfg.get("host", "127.0.0.1")
    port = api_cfg.get("port", 8000)

    print(f"\n  RIO API Server starting...")
    print(f"  -> UI:      http://{host}:{port}/")
    print(f"  -> API:     http://{host}:{port}/chat")
    print(f"  -> Docs:    http://{host}:{port}/docs")
    print(f"  -> Model:   {CFG.get('llm', {}).get('model', 'unknown')}\n")

    uvicorn.run(app, host=host, port=port, log_level="warning")
