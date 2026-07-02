"""
src/api/app.py
===============

FastAPI application factory for Phase 6.

USAGE
-----
Run the API server:
    uvicorn src.api.app:app --reload --host 0.0.0.0 --port 8000

Or using the project helper:
    python -m src.api.app

Then open:
    API:  http://localhost:8000
    Docs: http://localhost:8000/docs      (Swagger UI)
    Alt:  http://localhost:8000/redoc     (ReDoc)

DESIGN
------
- Root endpoint (GET /) is defined here since it doesn't belong to any router group
- All other endpoints are mounted from routers/
- Exception handler translates unexpected DB errors to HTTP 500
- CORS is open for local development (restrict in production)
"""

import sys
from pathlib import Path

# Azure Oryx may run from /tmp/<id>; keep project root importable (config/, src/).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import sqlite3

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import config.settings as cfg
from src.api.database import get_db
from src.api.routers import countries, stress, summary, trends

# ── Application factory ───────────────────────────────────────────────────────

app = FastAPI(
    title="Global Economic Stress Monitoring Platform",
    description=(
        "REST API that exposes economic stress scores, country profiles, "
        "and global risk rankings computed from World Bank, IMF, and FRED data.\n\n"
        "**Data source**: `data/economic_stress.db` (read-only)\n\n"
        "**Run the ETL pipeline first** (`python main.py`) to populate the database."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS (set CORS_ORIGINS env on Azure to your dashboard URL) ────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.CORS_ORIGINS,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ── Global exception handler ───────────────────────────────────────────────────

@app.exception_handler(sqlite3.Error)
async def sqlite_error_handler(request: Request, exc: sqlite3.Error):
    """Catch unexpected SQLite errors and return HTTP 500 with a clean message."""
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Database error. Ensure the ETL pipeline has run and "
                      "data/economic_stress.db exists.",
            "error":  str(exc),
        },
    )

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(countries.router)
app.include_router(stress.router)
app.include_router(summary.router)
app.include_router(trends.router)

# ── Root endpoint ─────────────────────────────────────────────────────────────

@app.get(
    "/",
    tags=["Health"],
    summary="Platform health check",
    response_model=dict,
)
def root() -> dict:
    """Return platform name and running status."""
    return {
        "project": "Global Economic Stress Monitoring Platform",
        "status":  "running",
    }


@app.get(
    "/health",
    tags=["Health"],
    summary="Health check with database status",
    response_model=dict,
)
def health(db: sqlite3.Connection = Depends(get_db)) -> dict:
    """Azure-friendly health probe — verifies SQLite is reachable."""
    db_path = cfg.DATABASE_PATH
    if not db_path.exists():
        return {
            "status":   "degraded",
            "database": "missing",
            "detail":   "Run ETL: python main.py",
        }
    try:
        db.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        return {"status": "healthy", "database": "connected"}
    except sqlite3.Error as exc:
        return {"status": "degraded", "database": "error", "detail": str(exc)}


# ── Dev server entry point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api.app:app", host="0.0.0.0", port=8000, reload=True)
