"""
tools/run_all_3d.py - ONE unattended run for the whole 3D pipeline.

    Phase 1  environment report (GPU, caches)
    Phase 2  prefetch + verify every asset (incl. the rembg provider
             probe - reported in the log, never a blocker)
    Phase 3  self-test (real conversion, anti-sphere gate)
    Phase 4  the Waitemata building batch (only if the self-test
             passes; resumable, so a partial batch just continues)

Everything is mirrored into outputs/run-all-log.txt. The operator runs
run-all-3d.bat once, walks away, and sends that ONE log file back -
no run-paste-repeat cycles. (Written after Han's 2026-10-25 feedback
that drip-fed single checks were exhausting; the method was wrong,
not the operator.)

Exit code 0 = every phase passed.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            s.write(data)
            s.flush()
        return len(data)

    def flush(self):
        for s in self.streams:
            s.flush()


def phase(title: str) -> None:
    print(f"\n===== {title} =====", flush=True)


def main() -> int:
    log_path = ROOT / "outputs" / "run-all-log.txt"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "w", encoding="utf-8")
    real_stdout = sys.stdout
    sys.stdout = Tee(real_stdout, log_file)
    results: dict[str, str] = {}
    started = time.time()
    try:
        print(f"[run-all] log file: {log_path}")

        phase("PHASE 1/4 - environment")
        try:
            from selftest_3d import env_report
            env_report()
            results["env"] = "reported"
        except Exception as e:
            results["env"] = f"FAILED ({type(e).__name__}: {e})"

        phase("PHASE 2/4 - prefetch + verify assets")
        try:
            from pipeline_3d import ensure_assets_cached
            ensure_assets_cached(lambda p, m: print(f"[run-all] {m}"))
            results["prefetch"] = "PASS"
        except Exception as e:
            results["prefetch"] = f"FAIL ({type(e).__name__}: {e})"

        if results["prefetch"] == "PASS":
            phase("PHASE 3/4 - self-test")
            try:
                from selftest_3d import main as selftest_main
                rc = selftest_main()
                results["selftest"] = "PASS" if rc == 0 else f"FAIL (exit {rc})"
            except Exception as e:
                results["selftest"] = f"FAIL ({type(e).__name__}: {e})"
        else:
            results["selftest"] = "SKIPPED (prefetch failed)"

        if results.get("selftest") == "PASS":
            phase("PHASE 4/4 - building batch (18 Waitemata buildings)")
            proc = subprocess.Popen(
                [sys.executable, str(ROOT / "run_buildings_3d.py")],
                cwd=str(ROOT), stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True)
            assert proc.stdout is not None
            for line in proc.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
            rc = proc.wait()
            results["batch"] = "PASS" if rc == 0 else f"FAIL (exit {rc}) - see batch lines above"
        else:
            results["batch"] = "SKIPPED (self-test did not pass)"

        phase("SUMMARY")
        for name, verdict in results.items():
            print(f"[run-all] {name}: {verdict}")
        print(f"[run-all] total elapsed: {time.time() - started:.0f}s")
        ok = all(v in ("PASS", "reported") for v in results.values())
        print(f"[run-all] OVERALL: {'PASS' if ok else 'NOT COMPLETE - send this log file back'}")
        return 0 if ok else 1
    finally:
        sys.stdout = real_stdout
        log_file.close()


if __name__ == "__main__":
    raise SystemExit(main())
