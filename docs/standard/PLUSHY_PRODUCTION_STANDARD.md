# PLUSHY AI PRODUCTION STANDARD v1

Master production standard for every graphic asset Plushy AI produces.
Established 2026-10-23 on Han's instruction, using the inspect-first method:
existing project values were measured first and take precedence over any
newly proposed default. Where this document sets a new default, it says so.

## 1. Primary directive

• Plushy AI is the single production line for ALL 2D graphics in the
  project (Han, 2026-10-23). No other line produces 2D art for the game.
• The 2D art identity is the EverPlanet style: readable 2.5D presentation,
  warm lighting, rich but controlled colour, distinct silhouettes.
  EverPlanet is a style REFERENCE only. Its characters, buildings, sprites
  and tilesets are Nexon property and are never copied or converted.
  Every asset Plushy ships is an original design.
• 3D production is a downstream branch of the same line: Plushy produces
  the 2D source first, Meshy AI converts it to 3D (Han policy, 2026-10-21).
  Characters are always 2D first, then 3D. Skill effects and footprint
  effects stay 2D sprites and never go to Meshy.
• Every asset must belong to the same visual world. No isolated sprites
  with inconsistent camera angle, scale, lighting or rendering style.

## 2. Existing standards discovered (measured, authoritative)

Pipeline (plushy-ai repo, pipeline_sprite.py / sprites.py):
• Engine: stabilityai/sdxl-turbo, fp16 on CUDA, ~5 s per sprite on an
  RTX 4060 8 GB. Background removal by rembg; alpha binarized at 127
  (crisp alpha) unless --no-crisp is set.
• Canvas: 512 px default; production batches run at 768 px.
• Prompt suffix system is the camera/style contract (section 3).
• Negative prompt default blocks: blurry, watermark, text, cropped,
  cut off, out of frame, partial object, multiple objects, dark,
  silhouette, black background, gloomy, night, deformed, broken,
  incomplete.
• File naming inside a batch: slug of the prompt's first 5 words plus
  the seed index. Prompt files live in prompts/, one prompt per line.

Standing rules already in force:
• Sample first: never mass-run a new method or batch before Han approves
  a small sample (Han, 2026-10-12; re-confirmed 2026-10-21).
• Credit confirmation: any Meshy batch with a meaningful total is
  confirmed with Han (method + per-item + total) BEFORE it runs
  (standing rule, 2026-10-21).
• Retexture first: appearance changes to an existing model are a
  retexture job, never a full regeneration, unless Han explicitly
  orders new production (standing rule, 2026-10-21).
• Asset size standard v1 (Architecture, 2026-10-21,
  ~/workspace/architecture/asset-size-standard-v1.md) sets all delivery
  budgets (section 6). It is incorporated here, not replaced.

Canon measurements already established:
• Player/NPC character height: 1.70 m. Giant boss class: 7.20 m
  (4x the 1.8 m player reference, Hermes).
• 3D pivot: base-centre, ground at y=0, XZ centred. Single node named
  after the asset.
• Source-image contract for Meshy (prompt pack,
  ~/workspace/your_files/plushy-to-meshy-prompt-pack.md): single subject,
  centred, whole object in frame with margin, pure white #FFFFFF
  background, no ground, no shadow, no text, no watermark, 1024x1024
  or larger, 1:1. File naming {category}_{target}_{item}_{no}.

## 3. Camera and view standard (the suffix contract)

One asset, one declared view. The pipeline suffix IS the camera:

• --style 3d: three-quarter view showing depth and volume, polished 3D
  game-model look. Default for city buildings and Meshy-bound sources.
• --subject-type building (no --style 3d): straight-on front elevation,
  flat facade. For billboard facades and any asset Han orders as a
  front view. NOTE: --style 3d replaces this suffix, so the two are
  never combined when a front view is required.
• default (object): neutral sprite framing, single object fully visible.
  Props that need a front view carry "straight-on front view" in the
  prompt text itself.
• --style chibi: MapleStory 2 blocky-cute character framing.
• --style 2.5d: cel-shaded game-asset finish, appended after the
  subject suffix; combines with the front-elevation preset.

Rules:
• Never mix views inside one asset set. A set declares its view in the
  prompt file header, including the exact run command.
• Meshy-bound building sources use front 3/4 (prompt pack section 3);
  facade textures use the separate straight-on elevation prompt.
• Globe/curvature effects are renderer-side. Source sprites stay
  geometrically flat and reusable; curvature is never baked in.

## 4. Global scale standard

• 2D sprites: produced at 768 px square (production) with the subject
  fully in frame. Delivery follows asset size standard v1: alpha WebP
  by default (PNG only when alpha-edge quality needs it), long edge
  at most 512 px for general buildings, 1024 px for landmarks only,
  target at most 150 KB per building.
• 3D models: scaled at build time to the in-game size given by the
  ordering room (current Zealandia values: village buildings 7-12 m
  wide class, characters 1.70 m, boss 7.20 m). The build step records
  raw size, uniform scale factor and final footprint in the delivery
  README.
• Every 3D delivery defines: node name, height, footprint (X x Z),
  pivot (base-centre, y=0), triangle count, file size, texture size.
• Collision is defined by the game side from the footprint, never
  derived from sprite transparency or visual silhouette.

## 5. Folder and naming standard

• Prompt batches: plushy-ai/prompts/{set}_{category}.txt with a header
  carrying the set purpose, the style lock and the exact run command.
• Deliverables: ~/workspace/goals/<goal>/files/{asset-set}/ holding the
  source image, the Meshy task record (JSON), the raw GLB, the final
  GLB and a README with the measured contract values.
• Asset file naming: {category}_{target}_{item}_{no} per the prompt
  pack. No final.png / test_latest.png style names.
• This standard lives in plushy-ai/docs/standard/ and is the reference
  every future batch header points to.

## 6. Delivery budgets (from asset size standard v1)

• 2D building sprites: alpha WebP default, long edge at most 512 px
  (landmarks 1024 px), target at most 150 KB each.
• 3D buildings: landmark at most 20k triangles, general at most 8k,
  decoration at most 2k; textures 1024 (buildings) / 512 (decor);
  gltfpack (meshopt) compression mandatory before production use.
• Characters: texture at most 1024, KTX2/WebP, target at most 4 MB
  per GLB.
• Meshy raw outputs exceed these budgets by design of the tool; a
  decimation + gltfpack pass is a required pipeline step, and the
  manifest marks uncompressed masters as such instead of calling
  them production-ready.

## 7. Workflow

1. Order arrives with in-game sizes and a declared view.
2. Prompt file written with the style lock and run command in header.
3. Sample first (one item end-to-end). Han approves or corrects.
4. Credit confirmation for any Meshy step (method, per-item, total).
5. Batch production. Per-item QC against section 8 gates.
6. Build step: scale, pivot, node naming, measurements recorded.
7. Manifest updated in the same pass (section 9). No manifest entry,
   no delivery claim.
8. Report: files, measurements, credits spent, what still needs
   Han's visual verdict (this machine cannot render GLBs; Han's PC
   check is the visual QA).

## 8. Quality gates

Visual:
• Correct declared view, consistent across the set
• Clean silhouette, subject fully in frame, nothing cropped
• Transparent background (2D) or pure white (Meshy-bound source)
• Style reads as the same world as the validated reference set

Technical:
• File exists at the recorded path; dimensions/format match
• 3D: single named node, base-centre pivot, y=0 ground contact
• Measurements inside the section 6 budgets, or the gap is recorded
• Manifest entry exists and matches the file

Validated reference set (the consistency anchor):
• Vancouver city sprites (approved by Han, 2026-10-11)
• Monster sprite sheets Strayer / Spitter / Brute (in-game, 2026-10-23)
• Hermes and Lunaris (produced 2026-10-21, wired into the game
  2026-10-22/23)
New work is compared against this set before it is called consistent.

## 9. Manifest

PLUSHY_ASSET_MANIFEST.json in this folder is the single registry.
It is generated from actual files by gen_manifest.py and must reflect
reality: an asset whose file does not exist is never marked ready.
Status values: ready / placeholder / missing / deprecated.

## 10. Scope boundary

• Plushy AI produces 2D graphics for everything, and the 2D sources
  for every 3D conversion. It does not place assets in the game,
  write game code, or set collision; those belong to the game rooms.
• Production scope (Han policy, 2026-10-21): skill effects, footprint
  effects, monsters, buildings, characters (2D first), town facilities
  and crafted Zealandia assets.
