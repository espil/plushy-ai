# PLUSHY BUILDING STANDARD v1

Companion to PLUSHY_PRODUCTION_STANDARD.md.

## Two building products, never mixed

• 2D sprite buildings (general environments): EverPlanet-style
  pre-rendered sprites. View is declared per set: --style 3d gives
  the 3/4 stock look; --subject-type building gives a straight-on
  front elevation for billboard facades. Delivery: alpha WebP
  default, long edge at most 512 px (landmarks 1024 px), target
  at most 150 KB (asset size standard v1).
• 3D buildings (crafted event maps, Zealandia class): Plushy 2D
  source in front 3/4 (prompt pack), Meshy image-to-3D, built to
  the in-game size ordered by the game room.

## 3D build contract

• Single mesh, single node named after the asset.
• Pivot base-centre, ground at y=0, XZ centred.
• Uniform scale only (no per-axis stretch); the build records raw
  size, scale factor and final footprint.
• Size classes from current orders: village buildings 7-12 m
  (well ~7 m, market/blacksmith/tavern ~11 m, chapel/lumbermill
  ~12 m, windmill ~10 m, houses ~10 m, watchtower ~9 m).
• Triangle budgets: landmark at most 20k, general at most 8k,
  decoration at most 2k. Textures 1024 per building.
• gltfpack (meshopt) compression is mandatory before production
  use; raw Meshy output (typically 12-14 MB) is a master, not a
  deliverable state.

## Facades

• A 3/4 render can never serve as a flat facade texture. Facades
  use the separate straight-on front-elevation prompt and preset
  (established 2026-10-11/12 after the facade-selection memo).

## Set consistency

• One prompt file per set, header carries the view, the style lock
  and the exact run command.
• A set is sampled first (one building end-to-end) and only batched
  after Han's approval (standing rule).
• Validated anchors: Vancouver sprite set (Han-approved), Auckland
  street buildings b1-b4 (11 m / 7 m, warm window glow family).
