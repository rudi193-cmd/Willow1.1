"""
Die-Namic System Routes
=======================
Read-only window into the die-namic-system databases.
Source ring + bridge ring + continuity ring state.

Endpoints:
  GET /api/die-namic/health       — check all 4 DBs
  GET /api/die-namic/state        — .index.db summary
  GET /api/die-namic/instances    — bridge_ring/.instance_registry.db
  GET /api/die-namic/sessions     — continuity_ring/.session_index.db
  GET /api/die-namic/costs        — bridge_ring/.cost_tracker.db

CHECKSUM: ΔΣ=42
"""

import sqlite3
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/die-namic", tags=["die-namic"])

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}

DIE_NAMIC = Path(__file__).parent.parent.parent / "die-namic-system"

DB_PATHS = {
    "index":     DIE_NAMIC / ".index.db",
    "instances": DIE_NAMIC / "bridge_ring" / ".instance_registry.db",
    "sessions":  DIE_NAMIC / "continuity_ring" / ".session_index.db",
    "costs":     DIE_NAMIC / "bridge_ring" / ".cost_tracker.db",
}


def _ro(db_key: str):
    """Open DB read-only. Raises 503 if not found."""
    p = DB_PATHS[db_key]
    if not p.exists():
        raise HTTPException(503, f"DB not found: {p.name}")
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _tables(conn) -> list:
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]


def _count(conn, table: str) -> int:
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except Exception:
        return 0


@router.get("/health")
def die_namic_health():
    status = {}
    for key, path in DB_PATHS.items():
        if path.exists():
            try:
                conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
                tables = [r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                conn.close()
                status[key] = {"ok": True, "tables": tables}
            except Exception as e:
                status[key] = {"ok": False, "error": str(e)}
        else:
            status[key] = {"ok": False, "error": "not found"}
    all_ok = all(v["ok"] for v in status.values())
    return JSONResponse({"status": "ok" if all_ok else "degraded", "dbs": status},
                        headers=CORS_HEADERS)


@router.get("/state")
def get_state():
    """Summary of .index.db — the source ring index."""
    conn = _ro("index")
    try:
        tables = _tables(conn)
        summary = {}
        for t in tables:
            summary[t] = _count(conn, t)
            # Sample last 3 rows from each table
            try:
                cols = [d[0] for d in conn.execute(f"SELECT * FROM {t} LIMIT 0").description]
                rows = conn.execute(f"SELECT * FROM {t} ORDER BY rowid DESC LIMIT 3").fetchall()
                summary[f"{t}_recent"] = [dict(zip(cols, r)) for r in rows]
            except Exception:
                pass
        return JSONResponse({"tables": tables, "counts": summary}, headers=CORS_HEADERS)
    finally:
        conn.close()


@router.get("/instances")
def get_instances():
    """Instance registry from bridge_ring."""
    conn = _ro("instances")
    try:
        tables = _tables(conn)
        result = {}
        for t in tables:
            try:
                cols = [d[0] for d in conn.execute(f"SELECT * FROM {t} LIMIT 0").description]
                rows = conn.execute(f"SELECT * FROM {t} ORDER BY rowid DESC LIMIT 20").fetchall()
                result[t] = [dict(zip(cols, r)) for r in rows]
            except Exception:
                result[t] = []
        return JSONResponse({"instances": result, "tables": tables}, headers=CORS_HEADERS)
    finally:
        conn.close()


@router.get("/sessions")
def get_sessions():
    """Session index from continuity_ring."""
    conn = _ro("sessions")
    try:
        tables = _tables(conn)
        result = {}
        for t in tables:
            try:
                cols = [d[0] for d in conn.execute(f"SELECT * FROM {t} LIMIT 0").description]
                rows = conn.execute(f"SELECT * FROM {t} ORDER BY rowid DESC LIMIT 20").fetchall()
                result[t] = [dict(zip(cols, r)) for r in rows]
            except Exception:
                result[t] = []
        return JSONResponse({"sessions": result, "tables": tables}, headers=CORS_HEADERS)
    finally:
        conn.close()


@router.get("/costs")
def get_costs():
    """Cost tracker from bridge_ring."""
    conn = _ro("costs")
    try:
        tables = _tables(conn)
        result = {}
        for t in tables:
            try:
                cols = [d[0] for d in conn.execute(f"SELECT * FROM {t} LIMIT 0").description]
                rows = conn.execute(f"SELECT * FROM {t} ORDER BY rowid DESC LIMIT 50").fetchall()
                result[t] = [dict(zip(cols, r)) for r in rows]
            except Exception:
                result[t] = []
        return JSONResponse({"costs": result, "tables": tables}, headers=CORS_HEADERS)
    finally:
        conn.close()
