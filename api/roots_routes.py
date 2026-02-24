"""
Roots API Routes
================
Manages filesystem roots — directories Willow indexes so it can answer
questions about local file structure beyond the Drop folder.

Endpoints:
  GET  /api/roots              — list configured roots
  POST /api/roots              — add a root path
  DELETE /api/roots            — remove a root path
  POST /api/roots/scan         — trigger immediate scan into knowledge DB

CHECKSUM: ΔΣ=42
"""

import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).parent.parent / "core"))

from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from core import roots_config

router = APIRouter(prefix="/api/roots", tags=["roots"])

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
}

DB_PATH = Path(__file__).parent.parent / "artifacts" / "Sweet-Pea-Rudi19" / "willow_knowledge.db"


class AddRootRequest(BaseModel):
    path: str
    label: Optional[str] = ""
    recursive: bool = True
    username: str = "Sweet-Pea-Rudi19"


class RemoveRootRequest(BaseModel):
    path: str
    username: str = "Sweet-Pea-Rudi19"


@router.get("")
def list_roots(username: str = Query("Sweet-Pea-Rudi19")):
    """List all configured filesystem roots."""
    roots = roots_config.load_roots(username)
    return JSONResponse(
        {"roots": roots, "count": len(roots)},
        headers=CORS_HEADERS,
    )


@router.post("")
def add_root(body: AddRootRequest):
    """Add a filesystem root."""
    path = Path(body.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Path does not exist: {body.path}")
    if not path.is_dir():
        raise HTTPException(status_code=400, detail=f"Path is not a directory: {body.path}")

    entry = roots_config.add_root(body.username, body.path, body.label, body.recursive)
    return JSONResponse(
        {"ok": True, "root": entry},
        headers=CORS_HEADERS,
    )


@router.delete("")
def remove_root(body: RemoveRootRequest):
    """Remove a filesystem root."""
    removed = roots_config.remove_root(body.username, body.path)
    return JSONResponse(
        {"ok": removed, "message": "Removed" if removed else "Path not found in roots"},
        headers=CORS_HEADERS,
    )


@router.post("/scan")
def scan_roots(username: str = Query("Sweet-Pea-Rudi19")):
    """Trigger immediate scan of all roots into knowledge DB."""
    if not DB_PATH.exists():
        raise HTTPException(status_code=503, detail="Knowledge DB not found")

    result = roots_config.scan_roots(username, DB_PATH)
    return JSONResponse(
        {
            "ok": True,
            "indexed": result["indexed"],
            "skipped": result["skipped"],
            "roots_scanned": result["roots_scanned"],
        },
        headers=CORS_HEADERS,
    )
