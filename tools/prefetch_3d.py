"""
tools/prefetch_3d.py - download every 3D asset up front, in the open.

SF3D needs three downloads on first use: its own weights, the
facebook/dinov2-large image tokenizer named in its config, and rembg's
u2net.onnx. Inside the conversion subprocess those downloads are
invisible and can crawl or stall silently (2026-10-25: ~50 minutes at
"10%" with the GPU idle). This tool fetches them with progress shown,
verifies each cache is complete, and afterwards the pipeline runs
SF3D fully offline - a missing file fails instantly and names itself.

Run inside the Docker image (prefetch-3d.bat does that on Windows):
    python tools/prefetch_3d.py

Exit code 0 = PREFETCH PASS (everything cached and verified).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    from pipeline_3d import MOCK, ensure_assets_cached

    if MOCK:
        print("[prefetch] PLUSHY_MOCK=1 is set - nothing to prefetch for mock mode.")
        return 1
    try:
        ensure_assets_cached(lambda p, m: print(f"[prefetch] {m}"))
    except Exception as e:
        print(f"[prefetch] FAIL: {type(e).__name__}: {e}")
        return 1
    print("[prefetch] PREFETCH PASS - all 3D assets are cached and verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
