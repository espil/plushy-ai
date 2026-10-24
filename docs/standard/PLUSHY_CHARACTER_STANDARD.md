# PLUSHY CHARACTER STANDARD v1

Companion to PLUSHY_PRODUCTION_STANDARD.md. Measured values come from
the delivered cast (Hermes, Lunaris, retextures, LF2 pair).

## Production route

• 2D first, then 3D (Han policy, 2026-10-21). The 2D source follows
  the prompt pack character block: full-body front view, neutral pose,
  arms slightly away from the torso so Meshy rigging has room, pure
  white background, whole body in frame.
• Style lock: MapleStory 2 blocky-cute chibi. Big head, compact body,
  clean bold silhouette. One proportion family for every character;
  no per-character proportion drift without a design reason.
• Appearance change to an existing character = retexture first
  (standing rule). Hair and other modelled parts are geometry:
  a retexture changes colour only, never silhouette.

## Scale

• Standard character height: 1.70 m (player, NPC, variants).
• Giant/boss class: 7.20 m (Hermes precedent, 4x player reference).
• Height is verified numerically on the skinned rest pose, not from
  raw accessor bounds (Meshy rigs carry a 0.01 root scale).

## Rig and animation

• Meshy rig: 24 joints. Rigging 5 credits; animation clips 3 credits
  each; prices confirmed with Han before any batch.
• Game clip set: Idle / Walk / Run as the baseline. Role clips are
  added per character (example: Lunaris TimeCast for her time-stop
  role, Hermes Leap).
• Merged animation files are built with plushy-room/merge_anims.py
  (same-rig clips, root scale corrected) and clip names are the
  game-facing names: Idle, Walk, Run, plus role clips by name.
• Sprite-sheet characters (billboard route) follow
  PLUSHY_ANIMATION_STANDARD.md instead.

## Character canon constraints

• Espil: face is NEVER shown; full bangs always cover the eyes;
  short pink bob; pale skin; black turtleneck or oversized teal
  sweater. No face layer is ever generated for Espil.
• Lunaris: ankle-length silver-white iridescent hair, grey eyes,
  gold crescent hairpin, white/silver crescent-motif dress.
• Face is not a Meshy item: facial features are an anchor-overlay
  design sheet (prompt pack section 2), never a 3D conversion.

## Delivery

• Files: {name}_source.png, {name}.glb (static), {name}_rigged.glb,
  {name}_animated.glb, anim_manifest.json, README with measured
  height, footprint, triangle count and credit cost.
• Budgets: texture at most 1024, target at most 4 MB per GLB after
  the compression pass (asset size standard v1). Raw Meshy masters
  are delivered uncompressed and marked as masters in the manifest.
