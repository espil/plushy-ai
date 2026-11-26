"""
tools/prefetch_quality_3d.py - download the QUALITY backend's assets
up front, in the open (the prefetch_3d.py discipline, for Hunyuan).

The quality backend needs three downloads on first use: the
Hunyuan3D-2mini shape weights (only the dit-v2-mini + vae-v2-mini
subfolders), the Hunyuan3D-2.0 paint subfolder of tencent/Hunyuan3D-2
(the full repo is ~62 GB and is NOT fetched), and facebook/
dinov2-large, the image encoder named in the DiT config. This tool
fetches them with progress shown and verifies each cache entry -
afterwards the pipeline runs Hunyuan fully offline, so a missing
file fails instantly and names itself instead of stalling.

Run inside the Docker image (run-quality-sample.bat does that on
Windows as one step of the unattended quality sample run):
    python tools/prefetch_quality_3d.py

Exit code 0 = PREFETCH PASS (everything cached and verified).
Neither model repo is gated, so no HF_TOKEN is needed for these.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    from pipeline_3d import MOCK, ensure_hunyuan_assets_cached, \
        hunyuan_cache_complete

    if MOCK:
        print("[prefetch-quality] PLUSHY_MOCK=1 is set - nothing to "
              "prefetch for mock mode.")
        return 1
    try:
        ensure_hunyuan_assets_cached(
            lambda p, m: print(f"[prefetch-quality] {m}"))
    except Exception as e:
        print(f"[prefetch-quality] FAIL: {type(e).__name__}: {e}")
        return 1
    if not hunyuan_cache_complete():
        print("[prefetch-quality] FAIL: cache verification failed "
              "after download")
        return 1
    print("[prefetch-quality] PREFETCH PASS - all quality-backend "
          "assets are cached and verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
