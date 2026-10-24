# PLUSHY ANIMATION STANDARD v1

Companion to PLUSHY_PRODUCTION_STANDARD.md. Covers sprite sheets
(2D) and Meshy clip sets (3D).

## Sprite sheets

• One sheet per monster per state group. Combat sheet rows
  top-to-bottom: idle / aggro / attack / hit. Walk sheet rows:
  front / left / right / back.
• Extraction: plushy-room/extract_frames.py (projection-valley
  bands, x-runs, flood-fill alpha). Output frames are named
  {monster}_{state}_{n}.png and {monster}_walk_{direction}_{n}.png.
• All frames of one monster share one canvas size; anchor is
  bottom-centre for every frame so the ground contact never jumps
  between frames.
• Frame counts per row are counted from the extracted files and
  written into the folder README. Empty slots in a source sheet
  are disclosed as empty, not filled silently.

## Skill and effect sprites

• Skill effects are Plushy 2D sprites on pure black, produced for
  additive blending, and never go to Meshy (prompt pack section 5).
• Footprint effects are top-down single decal sprites (prompt
  pack section 6).
• Effect batches are prompt files plus a runner (pattern:
  run_skill_fx.py + skill_fx_manifest.tsv) so a batch is one
  command on the GPU PC and every output is accounted for.

## 3D clip sets (Meshy)

• Baseline clips: Idle / Walk / Run. Free rig-included basics
  (WalkBasic / RunBasic) are kept in merged files as fallbacks.
• Prices: rigging 5 credits, each applied clip 3 credits.
  Confirmed with Han before a batch (standing rule).
• Merging: plushy-room/merge_anims.py, same-rig clips only,
  stride-aware accessor copy, clip names set to the game-facing
  names, root scale corrected for Meshy's 0.01 rig base.
• Verification: skinned rest-pose height is computed numerically
  and must equal the character standard height (1.70 m standard,
  7.20 m boss) before delivery.

## Naming

• Sprite frames: {monster}_{state}_{n}.png
• Clip names inside GLBs: Idle, Walk, Run, then role clips in
  PascalCase (TimeCast, Leap, Wave).
• No clip or frame is delivered without its count/name recorded
  in the set's README or anim_manifest.json.
