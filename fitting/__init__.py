"""Plushy-AI 2.0 Paper Doll Integration (Phase 4).

Library + CLI only: no server or UI wiring in this package (Phase 6
wires it into the Studio). Reuses by importing - never modifying -
the 1.0 paper doll (`paperdoll`: load_prompts, extract_layer, and its
documented compose layer order), the Phase 1 Asset Standard Engine
(`asset_standard`, for measured content bounds), and Phase 3
generation job records (linked by output sha256, never trusted by
filename alone).

Rules (Plushy-AI 2.0 development prompt, Phase 4):
  - Direction order stays S, SE, E, NE, N, NW, W, SW, and all 8
    directions are always accounted for in the manifest.
  - Body/layer canvas sizes are VALIDATED, never silently resized
    (the headline difference from 1.0 compose).
  - Missing body or layer files mark the direction "missing",
    naming the missing side - never a silent skip.
  - Originals are read-only; outputs go to a separate directory.
  - Anchors stay None: no fitting coordinate is guessed.
"""

from .fit import (
    ANCHORS_NOTE,
    COMPOSE_ORDER,
    COMPOSITION_MODEL,
    DIRECTIONS,
    LAYER_SLOTS,
    MANIFEST_SCHEMA_VERSION,
    FittingError,
    direction_from_filename,
    discover_bodies,
    discover_layers,
    extract_layer,
    fit_layers,
    load_prompts,
)

__all__ = [
    "ANCHORS_NOTE",
    "COMPOSE_ORDER",
    "COMPOSITION_MODEL",
    "DIRECTIONS",
    "LAYER_SLOTS",
    "MANIFEST_SCHEMA_VERSION",
    "FittingError",
    "direction_from_filename",
    "discover_bodies",
    "discover_layers",
    "extract_layer",
    "fit_layers",
    "load_prompts",
]
