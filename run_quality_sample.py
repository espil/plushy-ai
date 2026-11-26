"""Plushy-AI quality-mode (Hunyuan3D) verification run (one shot).

Han's rules baked in: ONE unattended runner, ONE log file to send
back (quality-sample-log.txt, next to this script), every path
relative to this script's own folder. Double-click
run-quality-sample.bat, wait, send back the log.

What it does:
  STEP 0  environment report (python, platform, GPU/VRAM via
          nvidia-smi, system RAM, free disk, docker presence)
  STEP 1  mock selftest - the Studio 2.0 model3d path on the
          procedural mock with the QUALITY backend selected, so a
          code/wiring problem is separated from a GPU problem; the
          mock output must be honestly labelled (mock=true,
          backend="hunyuan", *_MOCK.glb)
  STEP 2  engine + weights - if the Docker image lacks the
          Hunyuan engine venv, build the image (long, one-time,
          streamed into the log); then prefetch + verify the
          quality weights into the plushy-hf volume, in the open
  STEP 3  REAL quality generation inside the container (GPU):
          three bundled building images converted through
          Studio2Service.submit_model3d(backend="hunyuan") and
          checked with the production GLB gate
  STEP 4  summary

No silent mock substitution anywhere: STEP 3 runs with mock off,
and if the engine or the weights are missing the run FAILS loudly
in the log (QUALITY_SAMPLE_DONE ok=False) instead of producing
placeholders.

Set PLUSHY_QUALITY_DRYRUN=1 to validate this runner itself without
Docker/GPU (STEP 2-3 are skipped and the log says DRYRUN loudly).
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

BASE = Path(__file__).resolve().parent
LOG = BASE / "quality-sample-log.txt"
DRYRUN = os.environ.get("PLUSHY_QUALITY_DRYRUN") == "1"
DOCKER_IMAGE = "plushy-ai"
HF_VOLUME = "plushy-hf"

_log_file = None


def log(msg: str = "") -> None:
    line = str(msg)
    print(line, flush=True)
    if _log_file is not None:
        _log_file.write(line + "\n")
        _log_file.flush()


def step(title: str) -> None:
    log("")
    log(f"===== {title} =====")


def run_streamed(cmd: list[str], timeout: int, cwd: Path = BASE) -> int:
    """Run a command with its output streamed into the log."""
    log(f"$ {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd, cwd=str(cwd), stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, errors="replace",
        bufsize=1)
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            log(line.rstrip("\n"))
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        log(f"TIMEOUT after {timeout}s - command killed")
        return -1


def system_ram_gb():
    try:
        if sys.platform.startswith("win"):
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual",
                             ctypes.c_ulonglong)]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(
                ctypes.byref(stat))
            return stat.ullTotalPhys / 2**30
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) / 2**20
    except Exception:
        return None
    return None


def env_report() -> None:
    log(f"python: {sys.version.split()[0]} ({sys.executable})")
    log(f"platform: {platform.platform()}")
    smi = shutil.which("nvidia-smi")
    if smi:
        out = subprocess.run(
            [smi, "--query-gpu=name,memory.total",
             "--format=csv,noheader"],
            capture_output=True, text=True)
        gpu = (out.stdout or "").strip().splitlines()
        log(f"GPU (nvidia-smi): {gpu[0] if gpu else 'none reported'}")
    else:
        log("GPU: nvidia-smi not found on PATH - the container step "
            "will report the engine's own view")
    ram = system_ram_gb()
    log(f"system RAM: {ram:.1f} GiB" if ram else "system RAM: unknown")
    free = shutil.disk_usage(BASE).free / 2**30
    log(f"free disk (this folder's drive): {free:.1f} GiB")
    docker = shutil.which("docker")
    log(f"docker: {docker or 'NOT FOUND on PATH'}")


def mock_selftest() -> int:
    """Child-process entry (PLUSHY_MOCK=1 set by the parent, so the
    pipeline modules import in mock mode): the 2.0 model3d wiring
    with the quality backend, verified honestly labelled."""
    import tempfile

    from PIL import Image

    from studio2 import Studio2Service

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        svc = Studio2Service(root)
        Image.new("RGB", (16, 16), (180, 60, 60)).save(
            root / "references" / "house.png")
        view = svc.submit_model3d(
            {"source": "references/house.png", "backend": "quality"})
        print(f"[selftest] job status={view['status']} "
              f"registry_backend={view['backend']}")
        result = view.get("result") or {}
        print(f"[selftest] result mock={result.get('mock')} "
              f"backend={result.get('backend')} "
              f"outputs={result.get('output_files')}")
        ok = (view["status"] == "completed"
              and result.get("mock") is True
              and result.get("backend") == "hunyuan"
              and result.get("output_files", [""])[0].endswith(
                  "_MOCK.glb"))
        health = svc.model3d_health()
        print(f"[selftest] health: {json.dumps(health)}")
        print("[selftest] MOCK SELFTEST "
              + ("PASS" if ok else "FAIL"))
        return 0 if ok else 1


def docker_ok() -> bool:
    return shutil.which("docker") is not None


def engine_present() -> bool:
    rc = run_streamed(
        ["docker", "run", "--rm", DOCKER_IMAGE, "/usr/bin/test",
         "-x", "/opt/hunyuan-venv/bin/python"], timeout=300)
    return rc == 0


def main() -> int:
    global _log_file
    _log_file = LOG.open("w", encoding="utf-8")
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    log(f"PLUSHY-AI QUALITY SAMPLE RUN - started {started}")
    log(f"script folder: {BASE}")
    if DRYRUN:
        log("*** DRYRUN: PLUSHY_QUALITY_DRYRUN=1 - STEP 2-3 are "
            "SKIPPED; this log proves the runner and the mock "
            "wiring, not the GPU ***")
    ok = False
    try:
        step("STEP 0 - environment")
        env_report()

        step("STEP 1 - mock selftest (2.0 model3d wiring, no GPU)")
        env = dict(os.environ, PLUSHY_MOCK="1")
        child = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()),
             "--mock-selftest"],
            cwd=str(BASE), env=env, capture_output=True, text=True,
            errors="replace")
        log(child.stdout)
        if child.stderr:
            log("[child stderr]")
            log(child.stderr)
        step1_ok = child.returncode == 0
        log("STEP 1 PASS" if step1_ok else "STEP 1 FAIL - see above")

        if DRYRUN:
            ok = step1_ok
        elif not step1_ok:
            log("STEP 2-3 SKIPPED - the mock wiring already failed; "
                "fix that before spending GPU time")
        elif not docker_ok():
            step("STEP 2 - engine + weights")
            log("FAIL: docker not found on PATH. Start Docker "
                "Desktop (it provides the docker command), then run "
                "this file again. No placeholder was produced.")
        else:
            step("STEP 2 - engine + weights (docker)")
            if not engine_present():
                log("Hunyuan engine venv missing from the image - "
                    "building the Docker image now (one-time, long; "
                    "the Dockerfile changed when quality mode was "
                    "added)")
                rc = run_streamed(
                    ["docker", "build", "-t", DOCKER_IMAGE, "."],
                    timeout=7200)
                if rc != 0:
                    log(f"FAIL: docker build exited {rc} - see the "
                        "build output above. No placeholder was "
                        "produced.")
                    raise SystemExit(_finish(False))
            rc = run_streamed(
                ["docker", "run", "--rm",
                 "-v", f"{BASE}:/app",
                 "-v", f"{HF_VOLUME}:/root/.cache/huggingface",
                 DOCKER_IMAGE, "python",
                 "tools/prefetch_quality_3d.py"], timeout=3600)
            if rc != 0:
                log(f"FAIL: weight prefetch exited {rc} - the "
                    "quality weights are not verified in the "
                    "plushy-hf volume. No placeholder was produced.")
                raise SystemExit(_finish(False))
            log("STEP 2 PASS")

            step("STEP 3 - REAL quality generation (docker, GPU)")
            rc = run_streamed(
                ["docker", "run", "--rm", "--gpus", "all",
                 "-v", f"{BASE}:/app",
                 "-v", f"{HF_VOLUME}:/root/.cache/huggingface",
                 DOCKER_IMAGE, "python",
                 "tools/quality_sample_3d.py"], timeout=7200)
            ok = rc == 0
            log("STEP 3 PASS" if ok else
                f"STEP 3 FAIL - generation exited {rc}; see the "
                "engine output above (missing engine/weights fail "
                "loudly there, by design)")
    except SystemExit as e:
        return int(e.code)
    except Exception:
        log("UNEXPECTED FAILURE:")
        log(traceback.format_exc())
        ok = False
    return _finish(ok)


def _finish(ok: bool) -> int:
    step("STEP 4 - summary")
    log(f"QUALITY_SAMPLE_DONE ok={ok}")
    log("Send back this file: quality-sample-log.txt")
    _log_file.close()
    return 0 if ok else 1


if __name__ == "__main__":
    if "--mock-selftest" in sys.argv:
        raise SystemExit(mock_selftest())
    raise SystemExit(main())
