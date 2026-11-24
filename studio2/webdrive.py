"""Web-drive output saving for Plushy-AI 2.0 (additive, 2.0-side only).

Han's directive (2026-11-24): from 2.0 on, generated outputs are
saved to a web drive, not only to the PC's local disk - so results
can be picked up from the drive directly instead of living and
dying inside one machine's folders.

Mechanism: this module MIRRORS output trees into a configured
folder. Point the folder at the desktop-sync directory of a web
drive (Google Drive, OneDrive, Dropbox - any of them) and the
drive client uploads from there; no cloud API credentials are
stored in this repo and no network code runs here. The mirror is
incremental (size + mtime), idempotent, and writes a
`webdrive_manifest.json` into the target root describing exactly
what was mirrored, when, and from where.

Configuration (environment):
  PLUSHY_WEBDRIVE_DIR   target folder inside the web drive. When
                         unset, web-drive saving is DISABLED and
                         every entry point reports that honestly
                         instead of pretending to save.

Entry points:
  - Studio2Service.sync_to_webdrive() mirrors the 2.0 data root;
    the service also calls it best-effort after every export, so
    exported work reaches the drive without an extra step.
  - `python3 -m studio2.webdrive` mirrors the default trees
    (2.0 data root + 1.0 outputs/) for batch/runner use and
    prints a JSON report.

Nothing in 1.0 is imported or modified by this module.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

ENV_VAR = "PLUSHY_WEBDRIVE_DIR"
MANIFEST_NAME = "webdrive_manifest.json"
SCHEMA_VERSION = 1

# Files that are never mirrored: the manifest itself and partial
# writes from other tools.
_SKIP_NAMES = {MANIFEST_NAME}
_SKIP_SUFFIXES = {".tmp", ".part"}


def webdrive_dir() -> Path | None:
    """The configured web-drive folder, or None when disabled."""
    raw = os.getenv(ENV_VAR, "").strip()
    return Path(raw).expanduser() if raw else None


def _iter_files(src: Path):
    for path in sorted(src.rglob("*")):
        if not path.is_file():
            continue
        if path.name in _SKIP_NAMES or path.suffix in _SKIP_SUFFIXES:
            continue
        yield path


def mirror_tree(src: Path, dst: Path) -> dict:
    """Mirror every file under src into dst (incremental).

    A file is copied when the target is missing or its size/mtime
    differ. Returns a report dict; raises OSError on real failures
    so callers decide whether that is fatal (CLI) or not (the
    service hook, which records the error instead).
    """
    src = Path(src)
    dst = Path(dst)
    copied: list[str] = []
    skipped = 0
    total_bytes = 0
    if src.is_dir():
        for path in _iter_files(src):
            rel = path.relative_to(src)
            target = dst / rel
            st = path.stat()
            if target.is_file():
                tst = target.stat()
                if tst.st_size == st.st_size and \
                        tst.st_mtime_ns == st.st_mtime_ns:
                    skipped += 1
                    continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            copied.append(rel.as_posix())
            total_bytes += st.st_size
    return {
        "source": str(src),
        "target": str(dst),
        "copied": copied,
        "copied_count": len(copied),
        "skipped_unchanged": skipped,
        "bytes_copied": total_bytes,
    }


def _write_manifest(target_root: Path, sections: list[dict]) -> Path:
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "tool": "plushy-ai-2.0 webdrive mirror",
        "synced_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "sections": sections,
    }
    path = target_root / MANIFEST_NAME
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def sync_trees(pairs: list[tuple[Path, str]]) -> dict:
    """Mirror (source, target-subfolder) pairs into the web drive.

    Returns a report dict with status "disabled" (no folder
    configured), "ok", or "error" (with the error text). Never
    raises: this is a saving convenience, not a generation step.
    """
    target = webdrive_dir()
    if target is None:
        return {"status": "disabled",
                "reason": f"{ENV_VAR} is not set"}
    try:
        target.mkdir(parents=True, exist_ok=True)
        sections = []
        for src, sub in pairs:
            sections.append(mirror_tree(Path(src), target / sub))
        manifest = _write_manifest(target, sections)
        return {"status": "ok", "target": str(target),
                "manifest": str(manifest), "sections": sections}
    except OSError as e:
        return {"status": "error", "target": str(target),
                "error": f"{type(e).__name__}: {e}"}


def sync_service_root(service_root: Path) -> dict:
    """Mirror the 2.0 service data root into the web drive."""
    return sync_trees([(Path(service_root), "plushy-ai-2.0/studio2_data")])


def default_pairs(repo_root: Path) -> list[tuple[Path, str]]:
    """The trees a batch/runner sync covers, mirroring the env
    conventions of studio2_server.py and app.py."""
    studio2_dir = Path(os.getenv("PLUSHY_STUDIO2_DIR",
                                 repo_root / "studio2_data"))
    outputs_dir = Path(os.getenv("PLUSHY_OUTPUT_DIR",
                                 repo_root / "outputs"))
    return [(studio2_dir, "plushy-ai-2.0/studio2_data"),
            (outputs_dir, "plushy-ai-2.0/outputs")]


def main(argv=None) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    report = sync_trees(default_pairs(repo_root))
    print(json.dumps(report, indent=2))
    if report["status"] == "error":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
