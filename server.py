#!/usr/bin/env python3
"""
Willow UI Server — FastAPI wrapper around local_api.py

GOVERNANCE: Localhost-only. No external network binding.
"""

import sys
import hashlib
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles

# Wire imports
sys.path.insert(0, str(Path(__file__).parent))

import local_api
from core import knowledge
from core.coherence import get_coherence_report, check_intervention

app = FastAPI(title="Willow", docs_url=None, redoc_url=None)

# CORS for Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

USERNAME = local_api.DEFAULT_USER


# --- API Endpoints ---

@app.get("/api/status")
def status():
    ollama_up = local_api.check_ollama()
    models = local_api.list_models() if ollama_up else []
    gemini = local_api.check_gemini_available()
    claude = local_api.check_claude_available()

    # Knowledge stats
    stats = {"atoms": 0, "conversations": 0, "entities": 0, "gaps": 0}
    try:
        import sqlite3
        db_path = knowledge._db_path(USERNAME)
        if Path(db_path).exists():
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            for table, key in [("knowledge", "atoms"), ("conversation_memory", "conversations"),
                               ("entities", "entities"), ("knowledge_gaps", "gaps")]:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    stats[key] = cur.fetchone()[0]
                except:
                    pass
            conn.close()
    except:
        pass

    return {
        "ollama": ollama_up,
        "models": models,
        "gemini": gemini,
        "claude": claude,
        "knowledge": stats,
    }


@app.get("/api/personas")
def personas():
    result = {}
    for name, prompt in local_api.PERSONAS.items():
        result[name] = {
            "name": name,
            "folder": local_api.PERSONA_FOLDERS.get(name, name.lower()),
            "prompt_preview": prompt[:100] + "..." if len(prompt) > 100 else prompt,
        }
    return result


@app.post("/api/chat")
async def chat(request: Request):
    body = await request.json()
    prompt = body.get("prompt", "")
    persona = body.get("persona", "Willow")

    if not prompt:
        return {"error": "No prompt provided"}

    def generate():
        full_response = []
        for chunk in local_api.process_smart_stream(prompt, persona=persona, user=USERNAME):
            full_response.append(chunk)
            yield f"data: {chunk}\n\n"

        # Send coherence metrics as final SSE event
        try:
            coherence = local_api.log_conversation(
                persona=persona,
                user_input=prompt,
                assistant_response="".join(full_response),
                model="streamed",
                tier=0,
            )
            import json
            yield f"event: coherence\ndata: {json.dumps(coherence)}\n\n"
        except Exception:
            pass

        yield "event: done\ndata: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/knowledge/search")
def knowledge_search(q: str = "", limit: int = 5):
    if not q:
        return {"results": [], "query": q}
    results = knowledge.search(USERNAME, q, max_results=limit)
    return {"results": results, "query": q}


@app.get("/api/knowledge/gaps")
def knowledge_gaps(limit: int = 10):
    gaps = knowledge.get_top_gaps(USERNAME, limit=limit)
    return {"gaps": gaps}


@app.get("/api/knowledge/stats")
def knowledge_stats():
    import sqlite3
    stats = {}
    try:
        db_path = knowledge._db_path(USERNAME)
        if Path(db_path).exists():
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            for table in ["knowledge", "conversation_memory", "entities", "knowledge_gaps"]:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    stats[table] = cur.fetchone()[0]
                except:
                    stats[table] = 0
            conn.close()
    except:
        pass
    return stats


@app.get("/api/coherence")
def coherence():
    report = get_coherence_report()
    needs_intervention, reason = check_intervention()
    return {**report, "needs_intervention": needs_intervention, "intervention_reason": reason}


@app.post("/api/ingest")
async def ingest(file: UploadFile = File(...)):
    """Ingest a dropped file into the knowledge DB."""
    allowed_ext = {".txt", ".md", ".pdf", ".docx", ".json", ".csv", ".html", ".htm"}
    suffix = Path(file.filename).suffix.lower()

    if suffix not in allowed_ext:
        return {"error": f"Unsupported file type: {suffix}", "accepted": list(allowed_ext)}

    content_bytes = await file.read()
    file_hash = hashlib.md5(content_bytes).hexdigest()

    # Extract text content
    try:
        text = content_bytes.decode("utf-8", errors="ignore")
    except:
        return {"error": "Could not decode file as text"}

    if len(text) < 10:
        return {"error": "File too small or empty"}

    # Truncate for ingestion (same as unified_watcher)
    text_for_ingest = text[:4000]

    knowledge.ingest_file_knowledge(
        username=USERNAME,
        filename=file.filename,
        file_hash=file_hash,
        category="ui_drop",
        content_text=text_for_ingest,
        provider="willow_ui",
    )

    return {"status": "ingested", "filename": file.filename, "hash": file_hash, "chars": len(text_for_ingest)}


# --- Static file serving (production) ---

UI_DIST = Path(__file__).parent / "ui" / "dist"

if UI_DIST.exists():
    @app.get("/")
    def serve_index():
        return FileResponse(UI_DIST / "index.html")

    app.mount("/", StaticFiles(directory=str(UI_DIST)), name="static")


if __name__ == "__main__":
    import uvicorn
    print("Willow UI: http://127.0.0.1:8420")
    uvicorn.run(app, host="127.0.0.1", port=8420, log_level="info")
