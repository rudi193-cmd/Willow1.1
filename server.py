#!/usr/bin/env python3
"""
Willow UI Server — FastAPI wrapper around local_api.py

GOVERNANCE: Localhost-only. No external network binding.
"""

import sys
import hashlib
import httpx
import psutil
import queue
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

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

# Track server start time for uptime
SERVER_START_TIME = datetime.now()

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


@app.get("/api/system/status")
async def system_status():
    """
    Comprehensive system status for Willow health monitoring.
    Checks: Ollama, server uptime, governance queue, intake pipeline, engine, tunnel.
    """
    status = {
        "ollama": {"running": False, "models": []},
        "server": {"uptime_seconds": 0, "port": 8420},
        "governance": {"pending_commits": 0, "last_ratification": None},
        "intake": {"dump": 0, "hold": 0, "process": 0, "route": 0, "clear": 0},
        "engine": {"running": False},
        "tunnel": {"url": None, "reachable": False}
    }

    # --- Ollama Check ---
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get("http://127.0.0.1:11434/api/tags")
            r.raise_for_status()
            data = r.json()
            status["ollama"]["running"] = True
            status["ollama"]["models"] = [m["name"] for m in data.get("models", [])]
    except:
        pass

    # --- Server Uptime ---
    status["server"]["uptime_seconds"] = int((datetime.now() - SERVER_START_TIME).total_seconds())

    # --- Governance Check ---
    try:
        gov_dir = Path("governance/commits")
        if gov_dir.is_dir():
            pending = list(gov_dir.glob("*.pending"))
            status["governance"]["pending_commits"] = len(pending)

            # Last ratification = most recent non-pending file
            all_files = [f for f in gov_dir.iterdir() if f.is_file() and not f.name.endswith(".pending")]
            if all_files:
                latest = max(all_files, key=lambda f: f.stat().st_mtime)
                status["governance"]["last_ratification"] = datetime.fromtimestamp(latest.stat().st_mtime).isoformat()
    except:
        pass

    # --- Intake Check ---
    try:
        intake_dir = Path("intake")
        for stage in ["dump", "hold", "process", "route", "clear"]:
            stage_path = intake_dir / stage
            if stage_path.is_dir():
                status["intake"][stage] = len(list(stage_path.iterdir()))
    except:
        pass

    # --- Engine Check (kart process) ---
    try:
        for proc in psutil.process_iter(['name']):
            if 'kart' in proc.info['name'].lower() or 'python' in proc.info['name'].lower():
                # Check if it's running kart.py (basic heuristic)
                try:
                    if any('kart' in arg.lower() for arg in proc.cmdline()):
                        status["engine"]["running"] = True
                        break
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    pass
    except:
        pass

    # --- Tunnel Check ---
    try:
        tunnel_file = Path(".tunnel_url")
        if tunnel_file.is_file():
            tunnel_url = tunnel_file.read_text().strip()
            if tunnel_url:
                status["tunnel"]["url"] = tunnel_url
                try:
                    async with httpx.AsyncClient(timeout=5) as client:
                        r = await client.head(tunnel_url + "/api/health")
                        status["tunnel"]["reachable"] = r.is_success
                except:
                    pass
    except:
        pass

    return status


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


@app.post("/api/chat/multi")
async def chat_multi(request: Request):
    """
    Parallel multi-persona chat.

    Body: {"tasks": [{"persona": "Kart", "prompt": "..."}, ...]}

    Spawns threads for each persona, streams all responses tagged by persona.
    """
    body = await request.json()
    tasks = body.get("tasks", [])

    if not tasks:
        return {"error": "No tasks provided"}

    # Validate tasks
    for task in tasks:
        if "persona" not in task or "prompt" not in task:
            return {"error": "Each task must have 'persona' and 'prompt'"}

    def generate():
        # Queue for collecting chunks from all threads
        chunk_queue = queue.Queue()
        active_personas = set(task["persona"] for task in tasks)

        def worker(persona: str, prompt: str):
            """Worker thread that streams from one persona."""
            try:
                full_response = []
                for chunk in local_api.process_smart_stream(prompt, persona=persona, user=USERNAME):
                    full_response.append(chunk)
                    # Tag chunk with persona and put in queue
                    chunk_queue.put((persona, "chunk", chunk))

                # Log conversation for this persona
                try:
                    coherence = local_api.log_conversation(
                        persona=persona,
                        user_input=prompt,
                        assistant_response="".join(full_response),
                        model="streamed",
                        tier=0,
                    )
                    chunk_queue.put((persona, "coherence", coherence))
                except:
                    pass

                # Signal this persona is done
                chunk_queue.put((persona, "done", None))
            except Exception as e:
                chunk_queue.put((persona, "error", str(e)))

        # Start all threads
        with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
            futures = []
            for task in tasks:
                future = executor.submit(worker, task["persona"], task["prompt"])
                futures.append(future)

            # Stream events as they arrive
            while active_personas:
                try:
                    persona, event_type, data = chunk_queue.get(timeout=0.1)

                    if event_type == "chunk":
                        yield f"event: {persona}\ndata: {data}\n\n"

                    elif event_type == "coherence":
                        import json
                        yield f"event: coherence_{persona}\ndata: {json.dumps(data)}\n\n"

                    elif event_type == "done":
                        yield f"event: done_{persona}\ndata: [DONE]\n\n"
                        active_personas.discard(persona)

                    elif event_type == "error":
                        yield f"event: error_{persona}\ndata: {data}\n\n"
                        active_personas.discard(persona)

                except queue.Empty:
                    continue

            # All personas finished
            yield "event: complete\ndata: [COMPLETE]\n\n"

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


# --- Governance (Dual Commit) ---

GOV_COMMITS_DIR = Path("governance/commits")
GOV_COMMITS_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/api/governance/pending")
def governance_pending():
    """List all pending governance commits awaiting ratification."""
    try:
        pending = []
        for f in GOV_COMMITS_DIR.glob("*.pending"):
            stat = f.stat()
            pending.append({
                "id": f.stem,
                "filename": f.name,
                "timestamp": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "size": stat.st_size,
            })
        # Sort by timestamp descending (newest first)
        pending.sort(key=lambda x: x["timestamp"], reverse=True)
        return {"pending": pending}
    except Exception as e:
        return {"error": str(e), "pending": []}


@app.get("/api/governance/history")
def governance_history(limit: int = 50):
    """List ratified and rejected commits (history)."""
    try:
        history = []
        for f in list(GOV_COMMITS_DIR.glob("*.commit")) + list(GOV_COMMITS_DIR.glob("*.reject")):
            stat = f.stat()
            action = "approved" if f.suffix == ".commit" else "rejected"
            history.append({
                "id": f.stem,
                "filename": f.name,
                "action": action,
                "timestamp": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
        # Sort by timestamp descending
        history.sort(key=lambda x: x["timestamp"], reverse=True)
        return {"history": history[:limit]}
    except Exception as e:
        return {"error": str(e), "history": []}


@app.get("/api/governance/diff/{commit_id}")
def governance_diff(commit_id: str):
    """Get the contents of a pending commit for review."""
    try:
        filepath = GOV_COMMITS_DIR / f"{commit_id}.pending"
        if not filepath.exists():
            return {"error": "Commit not found"}
        content = filepath.read_text(encoding="utf-8")
        return {"id": commit_id, "content": content}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/governance/approve")
async def governance_approve(request: Request):
    """Approve (ratify) a pending commit. Moves .pending → .commit."""
    try:
        body = await request.json()
        commit_id = body.get("commit_id")
        if not commit_id:
            return {"error": "Missing commit_id"}

        pending_file = GOV_COMMITS_DIR / f"{commit_id}.pending"
        if not pending_file.exists():
            return {"error": "Commit not found"}

        # Move to .commit
        approved_file = GOV_COMMITS_DIR / f"{commit_id}.commit"
        pending_file.rename(approved_file)

        return {"success": True, "action": "approved", "commit_id": commit_id}
    except Exception as e:
        return {"error": str(e), "success": False}


@app.post("/api/governance/reject")
async def governance_reject(request: Request):
    """Reject a pending commit. Moves .pending → .reject and appends reason."""
    try:
        body = await request.json()
        commit_id = body.get("commit_id")
        reason = body.get("reason", "No reason provided")

        if not commit_id:
            return {"error": "Missing commit_id"}

        pending_file = GOV_COMMITS_DIR / f"{commit_id}.pending"
        if not pending_file.exists():
            return {"error": "Commit not found"}

        # Move to .reject
        rejected_file = GOV_COMMITS_DIR / f"{commit_id}.reject"
        content = pending_file.read_text(encoding="utf-8")

        # Append rejection reason
        new_content = f"{content}\n\n---\nREJECTED: {datetime.now().isoformat()}\nReason: {reason}\n"
        rejected_file.write_text(new_content, encoding="utf-8")
        pending_file.unlink()

        return {"success": True, "action": "rejected", "commit_id": commit_id}
    except Exception as e:
        return {"error": str(e), "success": False}


# --- Pattern Recognition & Health Monitoring ---

@app.get("/api/patterns/stats")
def patterns_stats():
    """Get routing pattern statistics."""
    try:
        from core import patterns
        stats = patterns.get_routing_stats(days=30)
        return stats
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/patterns/preferences")
def patterns_preferences():
    """Get learned routing preferences."""
    try:
        from core import patterns
        prefs = patterns.get_learned_preferences(min_confidence=0.3)
        return {"preferences": prefs}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/patterns/suggestions")
def patterns_suggestions():
    """Get suggested automatic routing rules."""
    try:
        from core import patterns
        suggestions = patterns.suggest_rules()
        return {"suggestions": suggestions}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/patterns/confirm_rule")
async def patterns_confirm_rule(request: Request):
    """User confirms a suggested routing rule."""
    try:
        from core import patterns
        body = await request.json()
        pattern_type = body.get("pattern_type")
        pattern_value = body.get("pattern_value")
        destination = body.get("destination")

        if not all([pattern_type, pattern_value, destination]):
            return {"error": "Missing required fields"}

        patterns.confirm_rule(pattern_type, pattern_value, destination)
        return {"success": True}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/patterns/reject_rule")
async def patterns_reject_rule(request: Request):
    """User rejects a suggested routing rule."""
    try:
        from core import patterns
        import sqlite3
        body = await request.json()
        pattern_type = body.get("pattern_type")
        pattern_value = body.get("pattern_value")
        destination = body.get("destination")

        if not all([pattern_type, pattern_value, destination]):
            return {"error": "Missing required fields"}

        # Delete the suggestion from learned_preferences
        conn = patterns._connect()
        conn.execute("""
            DELETE FROM learned_preferences
            WHERE pattern_type = ? AND pattern_value = ? AND destination = ?
        """, (pattern_type, pattern_value, destination))
        conn.commit()
        conn.close()

        return {"success": True, "message": "Rule rejected and removed from suggestions"}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/patterns/anomalies")
def patterns_anomalies():
    """Detect routing and entity anomalies."""
    try:
        from core import patterns
        anomalies = patterns.detect_anomalies(lookback_days=7)
        return {"anomalies": anomalies}
    except Exception as e:
        return {"error": str(e)}


# --- Fleet Feedback Endpoints ---

@app.get("/api/feedback/stats")
def feedback_stats():
    """Get feedback statistics by provider and task type."""
    try:
        from core import fleet_feedback
        stats = fleet_feedback.get_feedback_stats()
        return stats
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/feedback/tasks/{task_type}")
def feedback_for_task(task_type: str, min_quality: Optional[int] = None, limit: int = 10):
    """Get feedback for a specific task type."""
    try:
        from core import fleet_feedback
        feedback = fleet_feedback.get_feedback_for_task(task_type, min_quality, limit)
        return {"task_type": task_type, "feedback": feedback, "count": len(feedback)}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/feedback/provide")
async def provide_feedback(request: Request):
    """
    Submit feedback about a fleet output.

    Body: {
        "provider": "Groq",
        "task_type": "html_generation",
        "prompt": "original prompt",
        "output": "what the fleet generated",
        "quality": 2,  // 1-5 stars
        "issues": ["wrong_tech_stack", "syntax_errors"],
        "notes": "Generated React code instead of vanilla JS",
        "corrected": "optional corrected version"
    }
    """
    try:
        from core import fleet_feedback
        body = await request.json()

        # Validate required fields
        required = ["provider", "task_type", "prompt", "output", "quality", "issues", "notes"]
        missing = [f for f in required if f not in body]
        if missing:
            return {"error": f"Missing required fields: {missing}"}

        # Validate quality rating
        quality = body["quality"]
        if not isinstance(quality, int) or quality < 1 or quality > 5:
            return {"error": "quality must be an integer between 1 and 5"}

        # Store feedback
        fleet_feedback.provide_feedback(
            provider=body["provider"],
            task_type=body["task_type"],
            prompt=body["prompt"],
            output=body["output"],
            quality=quality,
            issues_list=body["issues"],
            notes=body["notes"],
            corrected=body.get("corrected")
        )

        return {
            "success": True,
            "message": f"Feedback recorded for {body['provider']} - {body['task_type']}"
        }
    except Exception as e:
        return {"error": str(e)}


# --- File Annotation Endpoints ---

@app.get("/api/annotations/unannotated")
def get_unannotated_routings(limit: int = 20):
    """Get routing decisions that haven't been annotated yet."""
    try:
        from core import file_annotations
        routings = file_annotations.get_unannotated_routings(limit=limit)
        return {"routings": routings, "count": len(routings)}
    except Exception as e:
        return {"error": str(e), "routings": []}


@app.post("/api/annotations/provide")
async def provide_annotation(request: Request):
    """
    Submit an annotation for a routing decision.

    Body: {
        "routing_id": 123,
        "filename": "test.py",
        "routed_to": ["node1", "node2"],
        "is_correct": false,
        "notes": "Should have gone to code_review because...",
        "corrected_destination": ["code_review"]
    }
    """
    try:
        from core import file_annotations
        body = await request.json()

        # Validate required fields
        required = ["routing_id", "filename", "routed_to", "is_correct", "notes"]
        missing = [f for f in required if f not in body]
        if missing:
            return {"error": f"Missing required fields: {missing}"}

        # Store annotation
        file_annotations.provide_annotation(
            routing_id=body["routing_id"],
            filename=body["filename"],
            routed_to=body["routed_to"],
            is_correct=body["is_correct"],
            notes=body["notes"],
            corrected_destination=body.get("corrected_destination"),
            annotated_by=body.get("annotated_by", "user")
        )

        return {
            "success": True,
            "message": f"Annotation recorded for routing {body['routing_id']}"
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/annotations/stats")
def get_annotation_stats():
    """Get file annotation statistics."""
    try:
        from core import file_annotations
        stats = file_annotations.get_annotation_stats()
        by_type = file_annotations.get_annotations_by_file_type()
        recent = file_annotations.get_recent_annotations(limit=10)
        return {
            "overall": stats,
            "by_file_type": by_type,
            "recent_annotations": recent
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/health/report")
def health_report():
    """Comprehensive system health report."""
    try:
        from core import health
        report = health.get_health_report()
        return report
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/health/nodes")
def health_nodes():
    """Check health of all nodes' knowledge databases."""
    try:
        from core import health
        nodes = health.check_node_health(stale_threshold_hours=24)
        return {"nodes": nodes}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/nodes/create_db")
async def create_node_db(request: Request):
    """
    Create knowledge database for a node.

    Body: {"node_name": "some_node"}
    """
    try:
        from core import knowledge
        body = await request.json()
        node_name = body.get("node_name")

        if not node_name:
            return {"error": "Missing node_name"}

        # Validate node name (alphanumeric, underscore, hyphen only)
        import re
        if not re.match(r'^[a-zA-Z0-9_-]+$', node_name):
            return {"error": "Invalid node_name. Use only letters, numbers, underscores, and hyphens."}

        # Create database
        knowledge.init_db(node_name)

        return {
            "success": True,
            "message": f"Knowledge database created for node: {node_name}",
            "node_name": node_name
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/health/queues")
def health_queues():
    """Check pending queue backlogs."""
    try:
        from core import health
        queues = health.check_queue_health(backlog_threshold=50)
        return {"queues": queues}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/health/apis")
def health_apis():
    """Check API health (Ollama, Gemini, Groq, etc.)."""
    try:
        from core import health
        apis = health.check_api_health()
        return {"apis": apis}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/health/issues")
def health_issues():
    """Get unresolved health issues."""
    try:
        from core import health
        issues = health.get_unresolved_issues()
        return {"issues": issues}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/health/heal")
async def health_heal(request: Request):
    """Attempt to self-heal a specific issue."""
    try:
        from core import health
        body = await request.json()
        issue_id = body.get("issue_id")

        if not issue_id:
            return {"error": "Missing issue_id"}

        success = health.attempt_self_heal(issue_id)
        return {"success": success, "issue_id": issue_id}
    except Exception as e:
        return {"error": str(e)}


# --- Provider Health Endpoints ---

@app.get("/api/health/providers")
def get_provider_health():
    """Get health status for all LLM providers."""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent / "core"))
        import provider_health

        health_data = provider_health.get_all_health_status()

        # Convert ProviderHealth objects to dicts
        providers = {}
        for name, h in health_data.items():
            providers[name] = {
                "provider": h.provider,
                "status": h.status,
                "consecutive_failures": h.consecutive_failures,
                "last_success": h.last_success,
                "last_failure": h.last_failure,
                "blacklisted_until": h.blacklisted_until,
                "total_requests": h.total_requests,
                "total_successes": h.total_successes,
                "total_failures": h.total_failures,
                "success_rate": (h.total_successes / h.total_requests * 100) if h.total_requests > 0 else 0
            }

        return {"providers": providers}
    except Exception as e:
        return {"error": str(e), "providers": {}}


@app.post("/api/health/providers/unblacklist")
async def unblacklist_provider(request: Request):
    """Manually unblacklist a provider."""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent / "core"))
        import provider_health
        import sqlite3

        body = await request.json()
        provider_name = body.get("provider")

        if not provider_name:
            return {"error": "Missing provider name"}

        # Manually unblacklist by updating database
        conn = provider_health._connect()
        conn.execute("""
            UPDATE provider_health
            SET status = 'healthy', blacklisted_until = NULL, consecutive_failures = 0
            WHERE provider = ?
        """, (provider_name,))
        conn.commit()
        conn.close()

        return {"success": True, "provider": provider_name, "message": f"{provider_name} unblacklisted"}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/health/providers/reset")
async def reset_provider_health(request: Request):
    """Reset health counters for a provider."""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent / "core"))
        import provider_health

        body = await request.json()
        provider_name = body.get("provider")

        if not provider_name:
            return {"error": "Missing provider name"}

        # Reset health counters
        conn = provider_health._connect()
        conn.execute("""
            UPDATE provider_health
            SET status = 'healthy',
                consecutive_failures = 0,
                blacklisted_until = NULL
            WHERE provider = ?
        """, (provider_name,))
        conn.commit()
        conn.close()

        return {"success": True, "provider": provider_name, "message": f"{provider_name} health reset"}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/queues/files")
async def get_queue_files(queue: str = None):
    """List files in a specific user's pending queue."""
    try:
        if not queue:
            return {"error": "Missing queue parameter"}

        artifacts_path = Path(__file__).parent / "artifacts"
        pending_dir = artifacts_path / queue / "pending"

        if not pending_dir.exists():
            return {"files": [], "message": "Queue does not exist"}

        files = []
        for file_path in pending_dir.iterdir():
            if file_path.is_file():
                stat = file_path.stat()
                files.append({
                    "name": file_path.name,
                    "size": stat.st_size,
                    "modified": stat.st_mtime
                })

        # Sort by modified time (newest first)
        files.sort(key=lambda x: x["modified"], reverse=True)

        return {"files": files, "queue": queue, "count": len(files)}
    except Exception as e:
        return {"error": str(e), "files": []}


@app.post("/api/queues/clear")
async def clear_queue(request: Request):
    """Clear all files from a user's pending queue."""
    try:
        import shutil

        body = await request.json()
        queue = body.get("queue")

        if not queue:
            return {"error": "Missing queue parameter"}

        # Security: validate queue name (no path traversal)
        import re
        if not re.match(r'^[a-zA-Z0-9_-]+$', queue):
            return {"error": "Invalid queue name"}

        artifacts_path = Path(__file__).parent / "artifacts"
        pending_dir = artifacts_path / queue / "pending"

        if not pending_dir.exists():
            return {"error": "Queue does not exist"}

        # Count files before deletion
        file_count = len([f for f in pending_dir.iterdir() if f.is_file()])

        # Delete all files in the pending directory
        for file_path in pending_dir.iterdir():
            if file_path.is_file():
                file_path.unlink()

        return {
            "success": True,
            "queue": queue,
            "files_deleted": file_count,
            "message": f"Cleared {file_count} files from {queue} queue"
        }
    except Exception as e:
        return {"error": str(e)}


# --- Intake Queue Management ---

@app.post("/api/intake/retry/{stage}")
async def retry_intake_stage(stage: str):
    """Retry all files in an intake stage by moving them back to dump."""
    try:
        intake_base = Path("intake")
        stage_path = intake_base / stage
        dump_path = intake_base / "dump"

        if not stage_path.exists():
            return {"error": f"Stage '{stage}' not found"}

        if not dump_path.exists():
            dump_path.mkdir(parents=True, exist_ok=True)

        # Move all files from stage back to dump
        moved_count = 0
        for file_path in stage_path.iterdir():
            if file_path.is_file():
                dest = dump_path / file_path.name
                file_path.rename(dest)
                moved_count += 1

        return {
            "success": True,
            "stage": stage,
            "files_retried": moved_count,
            "message": f"Moved {moved_count} files from {stage} back to dump for retry"
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/intake/clear/{stage}")
async def clear_intake_stage(stage: str):
    """Clear all files from an intake stage (moves to clear)."""
    try:
        intake_base = Path("intake")
        stage_path = intake_base / stage
        clear_path = intake_base / "clear"

        if not stage_path.exists():
            return {"error": f"Stage '{stage}' not found"}

        if not clear_path.exists():
            clear_path.mkdir(parents=True, exist_ok=True)

        # Move all files from stage to clear
        cleared_count = 0
        for file_path in stage_path.iterdir():
            if file_path.is_file():
                dest = clear_path / file_path.name
                file_path.rename(dest)
                cleared_count += 1

        return {
            "success": True,
            "stage": stage,
            "files_cleared": cleared_count,
            "message": f"Cleared {cleared_count} files from {stage}"
        }
    except Exception as e:
        return {"error": str(e)}


# --- Issue Management ---

@app.post("/api/health/issues/dismiss")
async def dismiss_issue(request: Request):
    """Dismiss a health issue by ID."""
    try:
        from core import health
        body = await request.json()
        issue_id = body.get("issue_id")

        if not issue_id:
            return {"error": "Missing issue_id"}

        # Mark issue as dismissed
        success = health.dismiss_issue(issue_id)

        return {
            "success": success,
            "issue_id": issue_id,
            "message": f"Issue {issue_id} dismissed" if success else "Failed to dismiss issue"
        }
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


# --- Governance Dashboard ---

GOVERNANCE_DASHBOARD = Path(__file__).parent / "governance" / "dashboard.html"

@app.get("/governance")
def serve_governance_dashboard():
    """Serve governance dashboard for dual commit review (admin only)."""
    if not GOVERNANCE_DASHBOARD.exists():
        return {"error": "governance/dashboard.html not found"}
    return FileResponse(GOVERNANCE_DASHBOARD, media_type="text/html")


# --- System Dashboard ---

SYSTEM_DASHBOARD = Path(__file__).parent / "system" / "dashboard.html"

@app.get("/system")
def serve_system_dashboard():
    """Serve system dashboard for pattern recognition and health monitoring."""
    if not SYSTEM_DASHBOARD.exists():
        return {"error": "system/dashboard.html not found"}
    return FileResponse(SYSTEM_DASHBOARD, media_type="text/html")


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
