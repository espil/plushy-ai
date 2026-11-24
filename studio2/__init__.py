"""Plushy-AI 2.0 Studio UI wiring (Phase 6).

The 2.0 Studio is ADDITIVE: the 1.0 Studio (`static/studio.html`,
served by app.py at /studio) is untouched. Phase 6 adds:

  - `studio2.service` - a framework-free service layer wrapping the
    Phase 1-5 libraries (asset_standard, reference, generator,
    fitting, exporter) plus an in-memory job registry. It imports
    no web framework and is fully testable without FastAPI.
  - `studio2.router` - a thin FastAPI router over the service
    layer, exposing the prompt's proposed 2.0 endpoints. Importing
    THIS package does not import the router (and therefore does
    not require FastAPI); import `studio2.router` explicitly to
    serve.
  - `static/studio2.html` - the new 9-screen Studio page, served
    at /studio2 by the standalone entrypoint `studio2_server.py`,
    which mounts the router on the 1.0 app without modifying it.
"""

from .service import (
    JOB_STATUSES,
    SERVICE_SCHEMA_VERSION,
    JobRegistry,
    Studio2Error,
    Studio2Service,
)
from .webdrive import (
    ENV_VAR as WEBDRIVE_ENV_VAR,
    sync_service_root,
    webdrive_dir,
)

__all__ = [
    "JOB_STATUSES",
    "SERVICE_SCHEMA_VERSION",
    "JobRegistry",
    "Studio2Error",
    "Studio2Service",
    "WEBDRIVE_ENV_VAR",
    "sync_service_root",
    "webdrive_dir",
]
