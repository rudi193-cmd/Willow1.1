"""
UTETY Routes
============
Full UTETY chat app wired into Willow.
Replaces the standalone safe-app-utety-chat/server.py.

Endpoints:
  POST /api/utety/session/start       — start SAFE session
  POST /api/utety/session/{id}/consent — grant/deny consent
  GET  /api/utety/professors          — list professor roster
  POST /api/utety/chat                — chat with professor (existing stub enhanced)
  GET  /api/utety/health              — health check

CHECKSUM: ΔΣ=42
"""

import sys
import uuid
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).parent.parent))
sys.path.insert(0, str(_Path(__file__).parent.parent.parent / "safe-app-utety-chat"))

from datetime import datetime
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/utety", tags=["utety"])

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
}

# In-memory session store (matches safe-app-utety-chat pattern)
_sessions: Dict[str, dict] = {}
_chat_histories: Dict[str, Dict[str, list]] = {}

UTETY_APP_PATH = _Path(__file__).parent.parent.parent / "safe-app-utety-chat"


# ── Models ─────────────────────────────────────────────────────────────────

class ConsentRequest(BaseModel):
    stream_id: str
    granted: bool


class ChatRequest(BaseModel):
    message: str
    persona: str = ""
    professor: str = ""
    history: List[dict] = []
    session_id: Optional[str] = None


# ── Session endpoints ───────────────────────────────────────────────────────

@router.post("/session/start")
def start_session():
    """Start a new SAFE session for UTETY."""
    session_id = str(uuid.uuid4())
    _sessions[session_id] = {
        "session_id": session_id,
        "started_at": datetime.now().isoformat(),
        "consents": {},
        "active": True,
    }
    _chat_histories[session_id] = {}
    return JSONResponse({
        "session_id": session_id,
        "authorization_requests": [
            {
                "stream_id": "chat",
                "purpose": "Enable conversation with UTETY professors",
                "retention": "session",
                "required": True,
                "prompt": "May I enable chat with UTETY faculty this session?"
            },
            {
                "stream_id": "history",
                "purpose": "Maintain conversation history across turns",
                "retention": "session",
                "required": False,
                "prompt": "May I keep conversation history during this session?"
            }
        ]
    }, headers=CORS_HEADERS)


@router.post("/session/{session_id}/consent")
def grant_consent(session_id: str, request: ConsentRequest):
    """Grant or deny consent for a data stream."""
    if session_id not in _sessions:
        raise HTTPException(404, "Session not found")
    _sessions[session_id]["consents"][request.stream_id] = {
        "granted": request.granted,
        "at": datetime.now().isoformat(),
    }
    return JSONResponse({"ok": True, "stream_id": request.stream_id, "granted": request.granted},
                        headers=CORS_HEADERS)


# ── Professors ──────────────────────────────────────────────────────────────

@router.get("/professors")
def list_professors():
    """List the UTETY professor roster."""
    try:
        sys.path.insert(0, str(UTETY_APP_PATH))
        from personas import PROFESSORS
        roster = [
            {"name": name, "title": p.get("title", ""), "dept": p.get("dept", ""),
             "specialty": p.get("specialty", "")}
            for name, p in PROFESSORS.items()
        ]
        return JSONResponse({"professors": roster, "count": len(roster)}, headers=CORS_HEADERS)
    except ImportError:
        # Fallback: return known professors from lore
        roster = [
            {"name": "Oakenscroll", "title": "Professor", "dept": "Physics & Metaphysics", "specialty": "Theoretical physics, time"},
            {"name": "Riggs", "title": "Professor Penny Riggs", "dept": "Applied Reality", "specialty": "K.I.S.S. theory, pragmatics"},
            {"name": "Alexis", "title": "Professor Alexis, Ph.D.", "dept": "Biological Sciences", "specialty": "Living systems, precausal studies"},
            {"name": "Gerald", "title": "Gerald", "dept": "Philosophy", "specialty": "Ethics, narrative, the absurd"},
        ]
        return JSONResponse({"professors": roster, "count": len(roster), "source": "fallback"},
                            headers=CORS_HEADERS)


# ── Chat ────────────────────────────────────────────────────────────────────

@router.post("/chat")
def utety_chat(body: ChatRequest):
    """Chat with a UTETY professor. Routes through free fleet."""
    message = body.message.strip()
    if not message:
        raise HTTPException(400, "message required")

    # Load professor persona
    persona_text = body.persona
    if not persona_text and body.professor:
        try:
            sys.path.insert(0, str(UTETY_APP_PATH))
            from personas import PROFESSORS
            prof = PROFESSORS.get(body.professor, {})
            persona_text = prof.get("system_prompt", f"You are Professor {body.professor} at UTETY.")
        except ImportError:
            persona_text = f"You are Professor {body.professor} at UTETY University."

    if not persona_text:
        raise HTTPException(400, "persona or professor required")

    # Build history context
    history = body.history or []
    if body.session_id and body.professor:
        session_hist = _chat_histories.get(body.session_id, {}).get(body.professor, [])
        if not history:
            history = session_hist

    history_text = ""
    for turn in history[-8:]:
        role = "User" if turn.get("role") == "user" else "Assistant"
        history_text += f"{role}: {turn.get('content', '')}\n"

    full_prompt = f"{persona_text}\n\n{history_text}User: {message}" if history_text \
        else f"{persona_text}\n\nUser: {message}"

    # Route through free fleet
    try:
        sys.path.insert(0, str(_Path(__file__).parent.parent / "core"))
        import llm_router
        llm_router.load_keys_from_json()
        result = llm_router.ask(full_prompt, preferred_tier="free")
        if not result:
            raise HTTPException(503, "fleet_unavailable")

        # Store in session history
        if body.session_id and body.professor:
            if body.session_id not in _chat_histories:
                _chat_histories[body.session_id] = {}
            hist = _chat_histories[body.session_id].get(body.professor, [])
            hist.append({"role": "user", "content": message})
            hist.append({"role": "assistant", "content": result.content})
            _chat_histories[body.session_id][body.professor] = hist[-20:]

        return JSONResponse({
            "response": result.content,
            "professor": body.professor,
            "provider": result.provider,
        }, headers=CORS_HEADERS)

    except Exception as e:
        raise HTTPException(500, str(e))


# ── Health ──────────────────────────────────────────────────────────────────

@router.get("/health")
def utety_health():
    professors_ok = (UTETY_APP_PATH / "personas.py").exists()
    return JSONResponse({
        "status": "ok",
        "active_sessions": len(_sessions),
        "professors_loaded": professors_ok,
        "utety_app_path": str(UTETY_APP_PATH),
    }, headers=CORS_HEADERS)
