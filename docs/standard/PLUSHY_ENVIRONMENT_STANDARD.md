# PLUSHY ENVIRONMENT STANDARD v1

Props, landmarks, nature pieces and dungeon pieces.
Companion to PLUSHY_PRODUCTION_STANDARD.md.

## General

• Same view discipline as buildings: the set declares its view
  (3/4 for Meshy-bound, front where ordered) and never mixes.
• Props are single objects, fully in frame, clean silhouette.
  Multi-object clusters are produced as one designed cluster item
  (example: basalt log pile, reed bundles), never as accidental
  groupings in a single-object prompt.
• Nature pieces follow the same style lock (MapleStory 2 blocky-cute,
  low-poly geometry, detail carried by texture).

## Scale classes (from current Zealandia orders)

• Hand props (barrel, crate, sacks, weapon rack, alchemy table):
  real-world size, recorded per item.
• Structures (teleporter, cave entrance, observation deck):
  sized to the ordering room's in-game dimensions.
• Landmarks: waterfall variants ~9 / 12 / 20 m (reusable set),
  Mount Taranaki ~34 m, Mount Finkol ~30 m, dungeon wall pieces
  6-8 m high, modular straight/corner pairs share one height so
  they tile in game.

## Modular pieces

• Wall/rim/cliff pieces that must join in game are produced as a
  matched family in one batch (same prompt family, same scale
  pass) and delivered with a note of which edges join.
• Reusable variants (waterfall sizes, moai head variants) share one
  design language and differ only in the declared variation
  (size, expression, tilt).

## Glowing elements

• Crystal clusters and portal stones carry their glow colour as a
  design constant per dungeon (teal = Sunken Grotto, orange =
  Emberdeep, teal-mint = Drowned Vault). The colour is named in
  the prompt and recorded in the delivery README.

## Delivery

• Same contract as buildings: source image, task record, raw GLB,
  final GLB at ordered size, base-centre pivot y=0, measured
  footprint and triangle count in the README, manifest entry.
• Decoration-class triangle budget: at most 2k after compression
  (asset size standard v1); landmark pieces at most 20k.
