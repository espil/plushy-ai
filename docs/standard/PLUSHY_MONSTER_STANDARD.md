# PLUSHY MONSTER STANDARD v1

Companion to PLUSHY_PRODUCTION_STANDARD.md.

## Design

• Silhouette first: a monster must read at gameplay distance before
  any detail is added (prompt pack monster block).
• Original designs only. Type identity is carried by silhouette
  and one clear mechanic read (example from the delivered pack:
  Strayer = leaf-sprout chaser, Spitter = bud-cannon ranged,
  Brute = moss-rock golem tank).
• Size category is declared per monster (small / standard / large /
  boss). Boss class follows the character standard's giant scale.

## Two production routes

• Billboard sprite route (current Zealandia starting-village pack):
  generated sheets, frames extracted with plushy-room/
  extract_frames.py. Combat sheet rows top-to-bottom: idle /
  aggro / attack / hit, front view. Walk sheet rows: front / left /
  right / back. Frames: transparent PNG, per-monster uniform
  canvas, bottom-centre anchor. Frame counts are counted and
  recorded in the folder README; generated direction skew is
  disclosed, never silently patched (mirrored fill frames are
  declared in the README).
• 3D route: Plushy 2D source (front 3/4, silhouette-first) then
  Meshy, per the character standard's rig and clip rules.

## Animation states

• Sprite route: idle, aggro, attack, hit + walk in 4 directions.
• 3D route: Idle / Walk / Run baseline; attack and role clips per
  design (example: Hermes is never aggroed by design; his set is
  Idle / Walk / Run / Leap and the mechanic lives in the README
  handed to the game room).

## Data

• HP, speed and combat values are game-design data recorded in the
  delivery README and the manifest stats block; they are never
  baked into the artwork.
• Body collision, attack range and interaction range are game-side
  definitions based on the declared footprint, never on the sprite
  dimensions.
