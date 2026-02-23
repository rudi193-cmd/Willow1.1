"""
SAFE API Routes
================
Consent management + knowledge query endpoints for SAFE OS web clients.

Endpoints:
  POST /api/safe/consent/grant    — grant session consent (4h TTL)
  POST /api/safe/consent/revoke   — revoke consent
  GET  /api/safe/consent/status   — check consent status
  GET  /api/safe/query            — query willow_knowledge.db
  GET  /api/safe/health           — system health

Consent is in-memory (sessions lost on server restart — intentional).
Knowledge queries hit willow_knowledge.db with optional FTS.

CHECKSUM: ΔΣ=42
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/safe", tags=["safe"])

# ── In-memory consent sessions ─────────────────────────────────────────────
# {session_id: {"scope": str, "granted_at": datetime, "expires": datetime}}
_sessions: dict = {}

DB_PATH = Path(__file__).parent.parent / "artifacts" / "Sweet-Pea-Rudi19" / "willow_knowledge.db"

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
}


def _db():
    """Open a read-only connection to willow_knowledge.db."""
    if not DB_PATH.exists():
        raise HTTPException(status_code=503, detail=f"Knowledge DB not found: {DB_PATH}")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _prune_expired():
    """Remove expired sessions from memory."""
    now = datetime.now()
    expired = [sid for sid, s in _sessions.items() if s["expires"] < now]
    for sid in expired:
        del _sessions[sid]


# ── Models ─────────────────────────────────────────────────────────────────

class ConsentGrantRequest(BaseModel):
    session_id: str
    scope: str = "web"

class ConsentRevokeRequest(BaseModel):
    session_id: str


# ── Consent endpoints ──────────────────────────────────────────────────────

@router.post("/consent/grant")
def grant_consent(body: ConsentGrantRequest):
    _prune_expired()
    expires = datetime.now() + timedelta(hours=4)
    _sessions[body.session_id] = {
        "scope": body.scope,
        "granted_at": datetime.now().isoformat(),
        "expires": expires,
    }
    return JSONResponse(
        {"ok": True, "token": body.session_id, "expires": expires.isoformat()},
        headers=CORS_HEADERS,
    )


@router.post("/consent/revoke")
def revoke_consent(body: ConsentRevokeRequest):
    _sessions.pop(body.session_id, None)
    return JSONResponse({"ok": True}, headers=CORS_HEADERS)


@router.get("/consent/status")
def consent_status(session_id: str = Query(...)):
    _prune_expired()
    s = _sessions.get(session_id)
    if s and s["expires"] > datetime.now():
        return JSONResponse(
            {"active": True, "expires": s["expires"].isoformat()},
            headers=CORS_HEADERS,
        )
    return JSONResponse({"active": False, "expires": None}, headers=CORS_HEADERS)


# ── Knowledge query ────────────────────────────────────────────────────────

@router.get("/query")
def query_knowledge(
    q: Optional[str] = Query(None, description="Full-text search query"),
    category: Optional[str] = Query(None),
    ring: str = Query("bridge"),
    lattice_domain: Optional[str] = Query(None, description="23³ domain axis (e.g. archive, docs, personas)"),
    lattice_type: Optional[str] = Query(None, description="23³ type axis (e.g. snapshot, grounding, ledger)"),
    lattice_status: Optional[str] = Query(None, description="23³ status axis (e.g. live, archived, draft)"),
    limit: int = Query(20, le=100),
):
    try:
        conn = _db()
    except HTTPException:
        raise

    try:
        if q:
            # Full-text search via FTS5 virtual table, with optional lattice post-filters
            conditions = ["knowledge_fts MATCH ?"]
            params: list = [q]
            if lattice_domain:
                conditions.append("k.lattice_domain = ?")
                params.append(lattice_domain)
            if lattice_type:
                conditions.append("k.lattice_type = ?")
                params.append(lattice_type)
            if lattice_status:
                conditions.append("k.lattice_status = ?")
                params.append(lattice_status)
            sql = f"""
                SELECT k.id, k.title, k.summary, k.content_snippet,
                       k.category, k.source_type, k.created_at,
                       k.lattice_domain, k.lattice_type, k.lattice_status
                FROM knowledge k
                JOIN knowledge_fts fts ON k.rowid = fts.rowid
                WHERE {' AND '.join(conditions)}
                ORDER BY rank
                LIMIT ?
            """
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
        else:
            # Filter by category / ring / lattice axes
            conditions = ["1=1"]
            params = []
            if category:
                conditions.append("category = ?")
                params.append(category)
            if ring:
                conditions.append("ring = ?")
                params.append(ring)
            if lattice_domain:
                conditions.append("lattice_domain = ?")
                params.append(lattice_domain)
            if lattice_type:
                conditions.append("lattice_type = ?")
                params.append(lattice_type)
            if lattice_status:
                conditions.append("lattice_status = ?")
                params.append(lattice_status)
            sql = f"""
                SELECT id, title, summary, content_snippet,
                       category, source_type, created_at,
                       lattice_domain, lattice_type, lattice_status
                FROM knowledge
                WHERE {' AND '.join(conditions)}
                ORDER BY created_at DESC
                LIMIT ?
            """
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()

        results = [dict(r) for r in rows]
        return JSONResponse(
            {"results": results, "count": len(results)},
            headers=CORS_HEADERS,
        )

    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")
    finally:
        conn.close()


# ── Health ─────────────────────────────────────────────────────────────────

@router.get("/health")
def safe_health():
    _prune_expired()
    db_ok = DB_PATH.exists()
    db_count = 0
    if db_ok:
        try:
            conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
            db_count = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
            conn.close()
        except Exception:
            db_ok = False

    lattice_domains = {}
    if db_ok:
        try:
            conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
            for row in conn.execute(
                "SELECT lattice_domain, COUNT(*) FROM knowledge WHERE lattice_domain IS NOT NULL GROUP BY lattice_domain ORDER BY 2 DESC"
            ):
                lattice_domains[row[0]] = row[1]
            conn.close()
        except Exception:
            pass

    return JSONResponse(
        {
            "status": "ok",
            "consent_sessions": len(_sessions),
            "db_reachable": db_ok,
            "knowledge_count": db_count,
            "lattice_domains": lattice_domains,
        },
        headers=CORS_HEADERS,
    )
