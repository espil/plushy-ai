"""Standalone entrypoint for the Plushy-AI 2.0 Studio (Phase 6).

Runs the UNMODIFIED 1.0 FastAPI app (`app.py`) with the Phase 6
2.0 router mounted on it, plus the new Studio page at /studio2:

    PLUSHY_MOCK=1 python3 studio2_server.py
    # then open http://localhost:8000/studio2

Nothing in 1.0 is edited: this file only imports `app.app`,
includes `studio2.router`'s router, and registers one extra GET
route for the new page. The 1.0 Studio stays at /studio and all
1.0 endpoints keep their exact behaviour.

Environment:
  PLUSHY_MOCK=1        procedural placeholder generation (no GPU)
  PLUSHY_STUDIO2_DIR   where the 2.0 service stores its files
                       (default: <repo>/studio2_data)
  PLUSHY_STUDIO2_PORT  port to serve on (default: 8000)

VERIFICATION STATUS: this entrypoint requires FastAPI + uvicorn.
FastAPI is not installed in the development VM used for Phase 6,
so the live server run is UNVERIFIED there - the framework-free
service layer underneath it is fully tested instead
(tests/test_studio2.py). Run it on the GPU PC / in Docker, where
the 1.0 app already runs, to verify the serving path.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def build_app():
    """Return the 1.0 app with the 2.0 router and /studio2 mounted."""
    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    from app import app
    from studio2.router import create_router

    app.include_router(create_router())

    @app.get("/studio2")
    async def studio2_page():
        page = BASE_DIR / "static" / "studio2.html"
        if not page.exists():
            raise HTTPException(404, "studio2 UI not installed")
        return FileResponse(page, media_type="text/html")

    return app


app = None  # built lazily in main() so importing this file is cheap


def main() -> None:
    import uvicorn

    port = int(os.getenv("PLUSHY_STUDIO2_PORT", "8000"))
    uvicorn.run(build_app(), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
