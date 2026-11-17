"""Plushy-AI 2.0 Asset Standard Engine (Phase 1).

Analyzes existing asset files (PNG and Aseprite) and emits the versioned
Espil asset-standard JSON described in docs/ASSET_STANDARD.md. Analysis is
read-only: source files are never modified, and anything that cannot be
measured from the file itself stays null/unknown - never guessed.
"""

from .analyze import SCHEMA_VERSION, AssetAnalysisError, analyze_file

__all__ = ["SCHEMA_VERSION", "AssetAnalysisError", "analyze_file"]
