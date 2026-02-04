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
from core import topology
from core.awareness import on_scan_complete, on_organize_complete, on_coherence_update, on_topology_update, say as willow_say
from apps.pa import drive_scan, drive_organize

app = FastAPI(title="Willow", docs_url=None, redoc_url=None)

# CORS for Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # LAN + Neocities + tunnel all need access
    allow_methods=["*"],
    allow_headers=["*"],
)

USERNAME = local_api.DEFAULT_USER


# --- API Endpoints ---

@app.get("/api/health")
def health():
    """Fast health check — no Ollama ping, no DB queries."""
    return {"status": "ok"}


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
            on_coherence_update(coherence)
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


# --- Topology Endpoints ---

@app.get("/api/topology/rings")
def topology_rings():
    """Atom counts by ring."""
    return topology.get_ring_distribution(USERNAME)


@app.get("/api/topology/zoom/{node_id}")
def topology_zoom(node_id: int, depth: int = 1):
    """Traverse from an atom. ?depth=2 for recursive."""
    depth = min(depth, 3)  # Cap recursion
    return topology.zoom(USERNAME, node_id, depth)


@app.get("/api/topology/continuity")
def topology_continuity():
    """Strip continuity check — find gaps in the Möbius strip."""
    return topology.check_strip_continuity(USERNAME)


@app.get("/api/topology/flow")
def topology_flow():
    """Sankey-style ring flow graph."""
    return topology.get_ring_flow_graph(USERNAME)


@app.post("/api/topology/build_edges")
def topology_build_edges(batch_size: int = 50):
    """Compute edges between atoms. Incremental."""
    created = topology.build_edges(USERNAME, batch_size=batch_size)
    if created:
        on_topology_update(edges_created=created)
    return {"edges_created": created}


@app.post("/api/topology/cluster")
def topology_cluster(n_clusters: int = 10):
    """Cluster atoms via KMeans over embeddings."""
    cluster_ids = topology.cluster_atoms(USERNAME, n_clusters=n_clusters)
    if cluster_ids:
        on_topology_update(clusters_created=len(cluster_ids))
    return {"clusters_created": len(cluster_ids), "cluster_ids": cluster_ids}


# --- PA (Personal Assistant) Endpoints ---

DRIVE_ROOT = str(Path.home() / "My Drive")
_pa_catalog = []  # Module-level state for scan results
_pa_plan = {}     # Module-level state for current plan
_pa_near_dupes = []  # Near-duplicate pairs


@app.post("/api/pa/scan")
async def pa_scan():
    """Scan the entire Drive, classify everything, detect duplicates."""
    global _pa_catalog, _pa_plan, _pa_near_dupes
    if not Path(DRIVE_ROOT).exists():
        return {"error": f"Drive not mounted at {DRIVE_ROOT}"}

    _pa_catalog = drive_scan.scan(DRIVE_ROOT)
    drive_scan.find_duplicates(_pa_catalog, DRIVE_ROOT)
    _pa_near_dupes = drive_scan.find_near_duplicates(_pa_catalog, DRIVE_ROOT)
    _pa_plan = drive_organize.generate_plan(_pa_catalog)
    summary = drive_scan.catalog_summary(_pa_catalog)
    summary["near_duplicate_pairs"] = len(_pa_near_dupes)
    on_scan_complete(summary)
    return {"status": "scanned", "summary": summary}


@app.get("/api/pa/plan")
def pa_plan():
    """Get the current move plan."""
    if not _pa_plan:
        return {"error": "No scan performed yet. POST /api/pa/scan first."}
    return {
        "summary": _pa_plan.get("summary", {}),
        "folders_to_create": _pa_plan.get("folders_to_create", []),
        "review": drive_organize.review(_pa_plan),
        "move_count": len(_pa_plan.get("moves", [])),
        "delete_count": len(_pa_plan.get("deletes", [])),
    }


@app.post("/api/pa/execute")
async def pa_execute(request: Request):
    """Execute approved moves. Body: {scope: "organize"|"dedupe"|"cleanup"}"""
    if not _pa_plan:
        return {"error": "No plan generated. POST /api/pa/scan first."}

    body = await request.json()
    scope = body.get("scope", "organize")

    if scope == "organize":
        result = drive_organize.execute_moves(_pa_plan, DRIVE_ROOT, USERNAME)
    elif scope == "dedupe":
        result = drive_organize.execute_deletes(_pa_plan, DRIVE_ROOT, scope="dedupe")
    elif scope == "cleanup":
        result = drive_organize.execute_deletes(_pa_plan, DRIVE_ROOT, scope="cleanup")
        # Also remove empty dirs
        removed = drive_organize.cleanup_empty_dirs(DRIVE_ROOT)
        result["empty_dirs_removed"] = removed
    else:
        return {"error": f"Unknown scope: {scope}. Use organize|dedupe|cleanup"}

    on_organize_complete(result)
    return {"status": "executed", "scope": scope, "result": result}


@app.get("/api/pa/status")
def pa_status():
    """Get current PA progress."""
    return drive_organize.get_progress()


@app.post("/api/pa/correct")
async def pa_correct(request: Request):
    """
    Correct a misrouted file or mis-transcribed content.
    Body: {
        path: "current/relative/path.md",        (required)
        destination: "Creative/",                 (optional — move here)
        text: "corrected transcription content",  (optional — re-ingest)
        category: "creative"                      (optional — new category)
    }
    """
    body = await request.json()
    path = body.get("path")
    if not path:
        return {"error": "path is required"}
    result = drive_organize.correct_file(
        drive_root=DRIVE_ROOT,
        current_path=path,
        new_destination=body.get("destination"),
        corrected_text=body.get("text"),
        new_category=body.get("category"),
        username=USERNAME,
    )
    return {"status": "corrected", "result": result}


# --- Neocities Deploy ---

@app.post("/api/neocities/deploy")
def neocities_deploy():
    """Push pocket Willow to seancampbell.neocities.org."""
    try:
        from apps.neocities import deploy_pocket_willow
        result = deploy_pocket_willow()
        return {"status": "deployed", "result": result}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/neocities/info")
def neocities_info():
    """Get Neocities site info."""
    try:
        from apps.neocities import info
        return info()
    except Exception as e:
        return {"error": str(e)}


# --- Pocket Willow (mobile-friendly, served same-origin) ---

POCKET_HTML = Path(__file__).parent / "neocities" / "index.html"

@app.get("/pocket")
def serve_pocket():
    """Serve pocket Willow from same origin — no CORS / mixed-content issues."""
    if not POCKET_HTML.exists():
        return {"error": "neocities/index.html not found"}
    return FileResponse(POCKET_HTML, media_type="text/html")


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
    uvicorn.run(app, host="0.0.0.0", port=8420, log_level="info")
