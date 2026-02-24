"""
Vision Board Routes
===================
Wires vision-board image classification into Willow.
Kills the port conflict (vision-board was also on :8420).

Endpoints:
  GET  /api/vision/health     — check Ollama vision availability
  POST /api/vision/classify   — classify a single image
  POST /api/vision/batch      — classify multiple images
  GET  /api/vision/categories — list category map

CHECKSUM: ΔΣ=42
"""

import sys
import base64
from pathlib import Path as _Path

VISION_BOARD_PATH = _Path(__file__).parent.parent.parent / "vision-board" / "backend"
sys.path.insert(0, str(VISION_BOARD_PATH))
sys.path.insert(0, str(_Path(__file__).parent.parent))

from typing import List, Optional
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/vision", tags=["vision"])

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
}


def _load_vision():
    """Try to import vision_processor from vision-board/backend."""
    try:
        import vision_processor as vp
        return vp
    except ImportError:
        return None


class ClassifyRequest(BaseModel):
    image_base64: str
    filename: Optional[str] = "image.jpg"


class BatchRequest(BaseModel):
    images: List[ClassifyRequest]


@router.get("/health")
def vision_health():
    vp = _load_vision()
    if not vp:
        return JSONResponse({
            "status": "degraded",
            "reason": "vision_processor not importable — check vision-board/backend/",
            "vision_board_path": str(VISION_BOARD_PATH),
        }, headers=CORS_HEADERS)
    try:
        ollama_ok = vp.check_ollama_vision()
    except Exception as e:
        ollama_ok = False
    return JSONResponse({
        "status": "ok" if ollama_ok else "degraded",
        "ollama_vision": ollama_ok,
        "categories": len(vp.CATEGORY_MAP),
    }, headers=CORS_HEADERS)


@router.get("/categories")
def list_categories():
    vp = _load_vision()
    if not vp:
        raise HTTPException(503, "vision_processor not available")
    return JSONResponse({
        "categories": vp.CATEGORY_MAP,
        "colors": vp.CATEGORY_COLORS,
    }, headers=CORS_HEADERS)


@router.post("/classify")
async def classify_image(request: ClassifyRequest):
    vp = _load_vision()
    if not vp:
        raise HTTPException(503, "vision_processor not available")
    try:
        image_bytes = base64.b64decode(request.image_base64)
        result = vp.classify_image_ollama(image_bytes, request.filename)
        return JSONResponse(result, headers=CORS_HEADERS)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/classify/upload")
async def classify_upload(file: UploadFile = File(...)):
    vp = _load_vision()
    if not vp:
        raise HTTPException(503, "vision_processor not available")
    try:
        image_bytes = await file.read()
        result = vp.classify_image_ollama(image_bytes, file.filename)
        return JSONResponse(result, headers=CORS_HEADERS)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/batch")
async def batch_classify(request: BatchRequest):
    vp = _load_vision()
    if not vp:
        raise HTTPException(503, "vision_processor not available")
    try:
        images = [base64.b64decode(img.image_base64) for img in request.images]
        names = [img.filename for img in request.images]
        results = vp.classify_image_batch(images, names)
        return JSONResponse({"results": results, "count": len(results)}, headers=CORS_HEADERS)
    except Exception as e:
        raise HTTPException(500, str(e))
