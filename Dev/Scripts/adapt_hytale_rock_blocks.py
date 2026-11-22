from pathlib import Path
from zipfile import ZipFile
from PIL import Image, ImageEnhance
import io, json, shutil

ROOT = Path(r"C:\Users\İlter\Desktop\PyCraft")
BLOCKS = ROOT / "Assets" / "block"
ARCHIVE = Path(r"C:\Users\İlter\AppData\Roaming\Hytale\install\release\package\game\latest\Assets.zip")
BACKUP = ROOT / "Hytale_Rock_Blocks_Backup_20261122"

# Hytale surface textures selected by material/function:
# cobblestone = small cold pebbles, mossy cobblestone = mossy stonework,
# gravel = loose gravel. All remain voxel-sized Minecraft tiles.
MAPPING = {
    "cobblestone.png": "Common/BlockTextures/Soil_Pebbles_Cold.png",
    "mossy_cobblestone.png": "Common/BlockTextures/Rock_Stone_Cobble_Mossy.png",
    "gravel.png": "Common/BlockTextures/Soil_Gravel.png",
}

if not ARCHIVE.is_file() or not BLOCKS.is_dir():
    raise SystemExit("Hytale archive or PyCraft block folder missing.")
targets = [name for name in MAPPING if (BLOCKS / name).is_file()]
if not targets:
    raise SystemExit("No matching rock textures found.")
if BACKUP.exists():
    raise SystemExit(f"Refusing to overwrite existing backup: {BACKUP}")
BACKUP.mkdir(parents=True)

report = []
with ZipFile(ARCHIVE) as z:
    names = set(z.namelist())
    for target_name in targets:
        source_name = MAPPING[target_name]
        if source_name not in names:
            print("MISSING:", source_name)
            continue
        target = BLOCKS / target_name
        shutil.copy2(target, BACKUP / target_name)
        src = Image.open(io.BytesIO(z.read(source_name))).convert("RGB")
        # Downsample with BOX filtering to preserve small individual stones
        # as readable pixel clusters rather than blurry smudges.
        tile = src.resize((16, 16), Image.Resampling.BOX)
        tile.save(target, "PNG", optimize=True)
        report.append({
            "target": target_name,
            "hytale_source": source_name,
            "source_resolution": list(src.size),
            "output_resolution": [16, 16],
        })

(ROOT / "Hytale_Rock_Blocks_Report.json").write_text(
    json.dumps({"changed": len(report), "files": report, "backup": str(BACKUP)},
               ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"changed": len(report), "files": report, "backup": str(BACKUP)},
                 ensure_ascii=False, indent=2))
