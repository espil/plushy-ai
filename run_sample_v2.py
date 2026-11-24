"""Plushy-AI 2.0 first sample run + real-GPU verification (one shot).

Han's rules baked in: ONE unattended runner, ONE log file to send
back (sample-v2-log.txt, next to this script), every path relative
to this script's own folder. Double-click run-sample-v2.bat, wait,
send back the log.

What it does:
  STEP 0  environment report (python, platform, torch/CUDA if any)
  STEP 1  mock selftest - the full 2.0 service path (generate ->
          export -> web-drive sync) on the procedural mock, so a
          code/dependency problem is separated from a GPU problem
  STEP 2  web-drive detection - PLUSHY_WEBDRIVE_DIR if set, else
          the first existing common sync folder (Google Drive /
          OneDrive), else honestly DISABLED in the log
  STEP 3  REAL sample generation through Studio2Service (no mock):
          four part jobs for the standing sample look (hair, top,
          bottom, shoes), short comma-phrase prompts, 512px,
          2 variations each; every job exported (exports also
          sync to the web drive via the 2.0 hook)
  STEP 4  final web-drive sync + summary

Set PLUSHY_SAMPLE_DRYRUN=1 to keep the mock in STEP 3 as well
(the log says DRYRUN loudly) - used to test this runner itself.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import tempfile
import time
import traceback
from pathlib import Path

BASE = Path(__file__).resolve().parent
LOG = BASE / "sample-v2-log.txt"
DRYRUN = os.environ.get("PLUSHY_SAMPLE_DRYRUN") == "1"

SAMPLE_JOBS = [
    ("Hair", "big messy dark navy hair, 2.5d chibi game sprite part, "
             "flat cel shading, transparent background"),
    ("Top", "dark oversized t-shirt over long sleeves, 2.5d chibi "
            "game sprite part, flat cel shading, transparent background"),
    ("Bottom", "gray baggy pants, 2.5d chibi game sprite part, "
               "flat cel shading, transparent background"),
    ("Shoes", "dark chunky sneakers, 2.5d chibi game sprite part, "
              "flat cel shading, transparent background"),
]

_log_file = None


def log(msg: str = "") -> None:
    line = str(msg)
    print(line, flush=True)
    if _log_file is not None and _log_file is not sys.stdout:
        _log_file.write(line + "\n")
        _log_file.flush()


def step(title: str) -> None:
    log("")
    log(f"===== {title} =====")


def detect_webdrive() -> str | None:
    """Return the web-drive target folder for this run, or None."""
    configured = os.environ.get("PLUSHY_WEBDRIVE_DIR", "").strip()
    if configured:
        log(f"webdrive: PLUSHY_WEBDRIVE_DIR set -> {configured}")
        return configured
    home = Path.home()
    # OneDrive first: it is Han's chosen web drive (2026-11-24).
    candidates = [
        home / "OneDrive",
        home / "Google Drive",
        home / "My Drive",
        Path("G:/My Drive"),
        Path("G:/Google Drive"),
    ]
    for cand in candidates:
        if cand.is_dir():
            target = str(cand / "PlushyAI-Outputs")
            log(f"webdrive: detected sync folder {cand} "
                f"-> target {target}")
            return target
    log("webdrive: NO sync folder detected (looked for Google "
        "Drive / My Drive / OneDrive) - saving DISABLED this run; "
        "outputs stay in the local studio2_data folder")
    return None


def run_jobs(svc, label: str) -> dict:
    """Run the sample jobs on a service; return a summary dict."""
    ok, failed, exports = 0, [], []
    for i, (category, prompt) in enumerate(SAMPLE_JOBS):
        try:
            job = svc.submit_generation({
                "prompt": prompt, "category": category,
                "seed": 11 + i, "variations": 2, "size": 512,
            })
            status = job.get("status")
            backend = (job.get("result") or {}).get("backend")
            log(f"[{label}] {category}: status={status} "
                f"backend={backend}")
            if status != "completed":
                failed.append(category)
                continue
            exp = svc.export_generation(job["job_id"])
            wd = (exp.get("webdrive") or {}).get("status")
            log(f"[{label}] {category}: export ok, webdrive={wd}")
            exports.append(exp["export_id"])
            ok += 1
        except Exception:
            failed.append(category)
            log(f"[{label}] {category}: FAILED")
            log(traceback.format_exc())
    return {"ok": ok, "failed": failed, "exports": exports}


def main() -> int:
    global _log_file
    _log_file = LOG.open("w", encoding="utf-8")
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    log(f"PLUSHY-AI 2.0 SAMPLE RUN - started {started}")
    log(f"script folder: {BASE}")
    if DRYRUN:
        log("*** DRYRUN: PLUSHY_SAMPLE_DRYRUN=1 - STEP 3 uses the "
            "MOCK backend too; this log proves the runner, not the "
            "GPU ***")

    step("STEP 0 - environment")
    log(f"python: {sys.version.split()[0]} ({sys.executable})")
    log(f"platform: {platform.platform()}")
    try:
        import torch
        log(f"torch: {torch.__version__}, "
            f"cuda_available={torch.cuda.is_available()}"
            + (f", device={torch.cuda.get_device_name(0)}"
               if torch.cuda.is_available() else ""))
    except Exception as e:
        log(f"torch: NOT importable ({type(e).__name__}: {e}) - the "
            "real backend will fail in STEP 3; STEP 1 separates "
            "that from code problems")

    step("STEP 1 - mock selftest (code path, no GPU)")
    os.environ["PLUSHY_MOCK"] = "1"
    mock_summary = None
    try:
        from studio2 import Studio2Service
        with tempfile.TemporaryDirectory() as tmp:
            svc = Studio2Service(Path(tmp) / "data")
            job = svc.submit_generation({
                "prompt": "selftest red top, flat cel shading",
                "category": "Top", "seed": 1, "variations": 1,
                "size": 32})
            exp = svc.export_generation(job["job_id"])
            mock_summary = job.get("status")
            log(f"mock job status={mock_summary}, "
                f"export manifest={exp['manifest'].get('status')}, "
                f"webdrive={exp['webdrive'].get('status')}")
        log("STEP 1 PASS" if mock_summary == "completed"
            else "STEP 1 FAIL - see above")
    except Exception:
        log("STEP 1 FAIL - exception:")
        log(traceback.format_exc())

    step("STEP 2 - web-drive detection")
    target = detect_webdrive()
    if target:
        os.environ["PLUSHY_WEBDRIVE_DIR"] = target

    step("STEP 3 - REAL sample generation (2.0 service path)")
    if not DRYRUN:
        os.environ.pop("PLUSHY_MOCK", None)
        # The pipeline modules read PLUSHY_MOCK at import time and
        # may already be imported by STEP 1 in this process; run
        # the real step in a child process for a clean import.
        import subprocess
        child = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()),
             "--real-step"],
            cwd=str(BASE), capture_output=True, text=True)
        log(child.stdout)
        if child.stderr:
            log("[child stderr]")
            log(child.stderr)
        summary = {"ok": None, "failed": [],
                   "child_rc": child.returncode}
        real_ok = child.returncode == 0
    else:
        from studio2 import Studio2Service
        svc = Studio2Service(BASE / "studio2_data")
        summary = run_jobs(svc, "dryrun")
        log(f"final sync: {json.dumps(svc.sync_to_webdrive())}")
        real_ok = summary["ok"] == len(SAMPLE_JOBS)

    step("STEP 4 - summary")
    log(f"summary: {json.dumps(summary)}")
    log(f"SAMPLE_V2_DONE ok={real_ok}")
    log("Send back this file: sample-v2-log.txt")
    _log_file.close()
    return 0 if real_ok else 1


def real_step() -> int:
    """Child-process entry: imports are fresh, PLUSHY_MOCK unset,
    so the REAL backend is exercised exactly as production runs.
    Output goes to stdout only; the parent captures it into the
    log file."""
    from studio2 import Studio2Service
    svc = Studio2Service(BASE / "studio2_data")
    summary = run_jobs(svc, "real")
    log(f"final sync: {json.dumps(svc.sync_to_webdrive())}")
    return 0 if summary["ok"] == len(SAMPLE_JOBS) else 1


if __name__ == "__main__":
    if "--real-step" in sys.argv:
        raise SystemExit(real_step())
    raise SystemExit(main())
