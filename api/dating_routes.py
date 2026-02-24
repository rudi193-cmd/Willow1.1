"""
Dating Wellbeing Routes
=======================
Wires safe-app-dating-wellbeing into Willow.
Red flag detection + pattern analysis for dating profiles.

Endpoints:
  POST /api/dating/analyze    — analyze a profile or message for red flags
  GET  /api/dating/patterns   — list learned personal patterns
  POST /api/dating/session/start  — start SAFE session
  GET  /api/dating/health     — health check

CHECKSUM: ΔΣ=42
"""

import sys
from pathlib import Path as _Path

DATING_APP_PATH = _Path(__file__).parent.parent.parent / "safe-app-dating-wellbeing"
sys.path.insert(0, str(DATING_APP_PATH))
sys.path.insert(0, str(_Path(__file__).parent.parent))

import uuid
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/dating", tags=["dating"])

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
}

_sessions: dict = {}


class AnalyzeRequest(BaseModel):
    content: str
    content_type: str = "message"  # message | profile | bio
    session_id: Optional[str] = None
    save_patterns: bool = False


class SessionStartRequest(BaseModel):
    allow_pattern_save: bool = False


@router.post("/session/start")
def start_session(body: SessionStartRequest):
    session_id = str(uuid.uuid4())
    _sessions[session_id] = {
        "session_id": session_id,
        "started_at": datetime.now().isoformat(),
        "allow_pattern_save": body.allow_pattern_save,
        "analyses": [],
    }
    return JSONResponse({
        "session_id": session_id,
        "authorization_requests": [
            {
                "stream_id": "profiles",
                "purpose": "Analyze dating profiles and messages for red flags",
                "retention": "session",
                "required": True,
                "prompt": "May I analyze dating content this session?"
            },
            {
                "stream_id": "patterns",
                "purpose": "Learn your personal red flag patterns over time",
                "retention": "permanent",
                "required": False,
                "prompt": "May I save patterns to improve future analyses?"
            }
        ]
    }, headers=CORS_HEADERS)


@router.post("/analyze")
def analyze_profile(body: AnalyzeRequest):
    """Analyze a dating profile or message for red flags using the free fleet."""
    if not body.content.strip():
        raise HTTPException(400, "content required")

    system_prompt = """You are a compassionate dating safety analyst. Analyze the provided content for:
1. Red flags (manipulation, love bombing, inconsistencies, pressure tactics)
2. Green flags (respect, honesty, clear communication)
3. Patterns worth noting

Be direct but kind. Format as:
RED FLAGS: [list or "None identified"]
GREEN FLAGS: [list or "None identified"]  
NOTES: [brief observation]
OVERALL: [1 sentence summary]"""

    content_label = {"message": "dating message", "profile": "dating profile", "bio": "bio"}.get(body.content_type, "content")
    prompt = f"{system_prompt}\n\nAnalyze this {content_label}:\n\n{body.content}"

    try:
        from core import llm_router
        llm_router.load_keys_from_json()
        result = llm_router.ask(prompt, preferred_tier="free")
        if not result:
            raise HTTPException(503, "fleet_unavailable")

        analysis = {
            "analysis": result.content,
            "content_type": body.content_type,
            "provider": result.provider,
            "analyzed_at": datetime.now().isoformat(),
        }

        if body.session_id and body.session_id in _sessions:
            _sessions[body.session_id]["analyses"].append({
                "at": analysis["analyzed_at"],
                "type": body.content_type,
                "snippet": body.content[:100],
            })

        return JSONResponse(analysis, headers=CORS_HEADERS)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/patterns")
def get_patterns(session_id: Optional[str] = None):
    """Return pattern summary for a session."""
    if session_id and session_id in _sessions:
        session = _sessions[session_id]
        return JSONResponse({
            "session_id": session_id,
            "analyses_this_session": len(session["analyses"]),
            "recent": session["analyses"][-5:],
        }, headers=CORS_HEADERS)
    return JSONResponse({"patterns": [], "note": "No session or session expired"}, headers=CORS_HEADERS)


@router.get("/health")
def dating_health():
    app_path_ok = DATING_APP_PATH.exists()
    safe_integration_ok = (DATING_APP_PATH / "safe_integration.py").exists()
    return JSONResponse({
        "status": "ok",
        "active_sessions": len(_sessions),
        "app_path": str(DATING_APP_PATH),
        "app_path_exists": app_path_ok,
        "safe_integration": safe_integration_ok,
    }, headers=CORS_HEADERS)
