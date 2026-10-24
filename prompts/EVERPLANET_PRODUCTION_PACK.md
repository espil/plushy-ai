# EverPlanet-inspired Zealandia production pack

This pack prepares original Plushy AI source sprites for the whole
Zealandia route: Waitematā (the starting village only), the six ruin
villages, the nine instanced field maps between them, the three dungeon
entrances and the dungeon interiors. The mood is a
bright, chunky, cute fantasy MMORPG world. Every design must stay original:
do not copy an EverPlanet, MapleStory or other game asset, character,
building, costume or layout.

Plushy AI produces transparent PNG sprites. Use them directly as game
billboards where that is the intended asset form, or use the approved PNGs
as the 2D source for the separate Meshy image-to-3D step.

## Files and settings

| Prompt file | Contents | Subject type | Style | Size |
|---|---|---|---|---:|
| `everplanet_waitemata_buildings.txt` | Espil House, homes, chief hall, inn, market, workshop, kitchen, healer, gate, tower and barn | `building` | `2.5d` | 768 |
| `everplanet_waitemata_props.txt` | Well, stalls, signs, lanterns, fences, work stations and village dressing | `object` | `2.5d` | 768 |
| `everplanet_characters.txt` | Player travellers, Waitematā villagers, Lunaris, Ahi, Huka and Espil | `object` | `chibi` | 512 |
| `everplanet_dungeon_entrances.txt` | Sunken Grotto, Emberdeep, Drowned Vault and generic ruin gates | `building` | `2.5d` | 768 |
| `everplanet_dungeon_assets.txt` | Doors, exits, lore stele, themed set pieces, chests, guardians and creatures | `object` | `2.5d` | 768 |
| `everplanet_villages_buildings.txt` | The six ruin villages: landmark structures, elder halls and houses for Nan Madol, Ha'amonga, Taputapuatea, Ahu Tongariki, Leluh and Pulemelei | `building` | `2.5d` | 768 |
| `everplanet_villages_props.txt` | Four signature props per ruin village | `object` | `2.5d` | 768 |
| `everplanet_villages_characters.txt` | The elder and two villagers of each ruin village | `object` | `chibi` | 512 |
| `everplanet_field_landmarks.txt` | Landmarks and path props for the nine field instances, in route order, including the side paths to the three dungeons | `object` | `2.5d` | 768 |

## Style locks

• Buildings and dungeon entrances use a straight-on front elevation. A three-quarter building view is not accepted for the village set.
• Characters are one full-body figure per image, centered, with the whole silhouette inside the frame.
• Props and dungeon set pieces are one object per image unless the prompt names a fixed set piece.
• Keep colors bright and readable, with chunky shapes and a clean silhouette.
• No text, letters, logos, watermarks, copied symbols or copied costume details.
• Faces and small emblems must stay simple enough to read at game size.

## Recommended production order

• Waitematā is only the starting village. Generate its buildings first and choose the starting-village silhouette, then its props and people.
• Then work along the route, one village at a time: Nan Madol, Ha'amonga, Taputapuatea, Ahu Tongariki, Leluh, Pulemelei. For each, generate its buildings, props and characters before moving on.
• Generate each field map's landmarks right after the village it leads to, so a segment reads as one journey. The dungeon side-path pieces sit in the field file of their leg: Kepirohi (Sunken Grotto), Fautaua (Emberdeep), Sopoaga (Drowned Vault).
• Generate the dungeon entrances with their legs, two seeds each, and pick one hero entrance per dungeon. Generate dungeon assets after the entrances, starting with the boss door, exit portal, lore stele and ruin heart pedestal.
• Keep rejected generations in the batch folder until selection is finished. The `manifest.json` records the prompt and seed for every file.

## OneDrive output layout

Use this tree on the GPU PC:

• `OneDrive\Plushy AI\outputs\waitemata_buildings`
• `OneDrive\Plushy AI\outputs\waitemata_props`
• `OneDrive\Plushy AI\outputs\zealandia_characters`
• `OneDrive\Plushy AI\outputs\dungeon_entrances`
• `OneDrive\Plushy AI\outputs\dungeon_assets`
• `OneDrive\Plushy AI\outputs\villages_buildings`
• `OneDrive\Plushy AI\outputs\villages_props`
• `OneDrive\Plushy AI\outputs\villages_characters`
• `OneDrive\Plushy AI\outputs\field_landmarks`

Share the parent `Plushy AI` folder from OneDrive with the Muse team.

## Batch commands

Run these on the GPU PC in PowerShell from the repo folder. The commands
mount the pulled repo, so they use the newest prompt files without waiting
for a Docker image rebuild. They also mount the OneDrive output tree.

```powershell
git pull
$OutRoot = Join-Path $env:OneDrive "Plushy AI\outputs"
New-Item -ItemType Directory -Force $OutRoot | Out-Null
```

### Waitematā buildings

```powershell
docker run --rm --gpus all -v "${PWD}:/app" -v "${OutRoot}:/app/plushy_outputs" -v plushy-hf:/root/.cache/huggingface plushy-ai python sprites.py --prompts /app/prompts/everplanet_waitemata_buildings.txt --subject-type building --style 2.5d --seeds 2 --size 768 --output /app/plushy_outputs/waitemata_buildings
```

### Waitematā props

```powershell
docker run --rm --gpus all -v "${PWD}:/app" -v "${OutRoot}:/app/plushy_outputs" -v plushy-hf:/root/.cache/huggingface plushy-ai python sprites.py --prompts /app/prompts/everplanet_waitemata_props.txt --style 2.5d --seeds 2 --size 768 --output /app/plushy_outputs/waitemata_props
```

### Characters

```powershell
docker run --rm --gpus all -v "${PWD}:/app" -v "${OutRoot}:/app/plushy_outputs" -v plushy-hf:/root/.cache/huggingface plushy-ai python sprites.py --prompts /app/prompts/everplanet_characters.txt --style chibi --seeds 2 --size 512 --output /app/plushy_outputs/zealandia_characters
```

### Dungeon entrances

```powershell
docker run --rm --gpus all -v "${PWD}:/app" -v "${OutRoot}:/app/plushy_outputs" -v plushy-hf:/root/.cache/huggingface plushy-ai python sprites.py --prompts /app/prompts/everplanet_dungeon_entrances.txt --subject-type building --style 2.5d --seeds 2 --size 768 --output /app/plushy_outputs/dungeon_entrances
```

### Dungeon assets

```powershell
docker run --rm --gpus all -v "${PWD}:/app" -v "${OutRoot}:/app/plushy_outputs" -v plushy-hf:/root/.cache/huggingface plushy-ai python sprites.py --prompts /app/prompts/everplanet_dungeon_assets.txt --style 2.5d --seeds 2 --size 768 --output /app/plushy_outputs/dungeon_assets
```

### Ruin village buildings

```powershell
docker run --rm --gpus all -v "${PWD}:/app" -v "${OutRoot}:/app/plushy_outputs" -v plushy-hf:/root/.cache/huggingface plushy-ai python sprites.py --prompts /app/prompts/everplanet_villages_buildings.txt --subject-type building --style 2.5d --seeds 2 --size 768 --output /app/plushy_outputs/villages_buildings
```

### Ruin village props

```powershell
docker run --rm --gpus all -v "${PWD}:/app" -v "${OutRoot}:/app/plushy_outputs" -v plushy-hf:/root/.cache/huggingface plushy-ai python sprites.py --prompts /app/prompts/everplanet_villages_props.txt --style 2.5d --seeds 2 --size 768 --output /app/plushy_outputs/villages_props
```

### Ruin village characters

```powershell
docker run --rm --gpus all -v "${PWD}:/app" -v "${OutRoot}:/app/plushy_outputs" -v plushy-hf:/root/.cache/huggingface plushy-ai python sprites.py --prompts /app/prompts/everplanet_villages_characters.txt --style chibi --seeds 2 --size 512 --output /app/plushy_outputs/villages_characters
```

### Field landmarks (the nine maps between villages)

```powershell
docker run --rm --gpus all -v "${PWD}:/app" -v "${OutRoot}:/app/plushy_outputs" -v plushy-hf:/root/.cache/huggingface plushy-ai python sprites.py --prompts /app/prompts/everplanet_field_landmarks.txt --style 2.5d --seeds 2 --size 768 --output /app/plushy_outputs/field_landmarks
```

## Studio use from the laptop

• Start `start-gui.bat` on the RTX 4060 PC and leave the PC and Docker running.
• On the laptop, open `http://<GPU PC LAN IP>:8000/studio` on the same network.
• Paste a single line from any prompt file into the Studio when testing one design before a full batch.
• Studio results land directly in the OneDrive output folder selected by the launcher.
• Use the Studio gallery or OneDrive to review the shared results.

## Selection check

• The whole object is inside the frame and the silhouette reads at small size.
• The background removal did not eat thin parts, lanterns, staffs or roof edges.
• A building is front-on, not a perspective render.
• A character has one body, two arms, two legs and no extra held object unless the prompt asked for it.
• A dungeon entrance has one clear opening that reads as the interaction point.
• No generated text or copied emblem appears anywhere in the image.
