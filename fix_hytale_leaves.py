from pathlib import Path
from zipfile import ZipFile
from PIL import Image
import io, json

ROOT = Path(r"C:\Users\İlter\Desktop\PyCraft")
BLOCKS = ROOT / "Assets" / "block"
ARCHIVE = Path(r"C:\Users\İlter\AppData\Roaming\Hytale\install\release\package\game\latest\Assets.zip")
BACKUP = ROOT / "Hytale_Leaf_Fix_Backup_20261122"

SOURCE = {
    "oak": "Common/Blocks/Foliage/Leaves/Ball_Textures/Oak.png",
    "birch": "Common/Blocks/Foliage/Leaves/Ball_Textures/Birch.png",
    "maple": "Common/Blocks/Foliage/Leaves/Ball_Textures/CrimsonMaple.png",
    "aspen": "Common/Blocks/Foliage/Leaves/Ball_Textures/Aspen.png",
    "fir": "Common/Blocks/Foliage/Leaves/PineShape_Textures/Fir.png",
    "banyan": "Common/Blocks/Foliage/Leaves/DownShape_Textures/Banyan.png",
    "redwood": "Common/Blocks/Foliage/Leaves/UpShapeSoft_Textures/Redwood.png",
}
TARGETS = {
    "oak_leaves.png": ("oak", 1.00),
    "birch_leaves.png": ("birch", 1.00),
    "spruce_leaves.png": ("fir", 1.00),
    "jungle_leaves.png": ("banyan", 1.00),
    "acacia_leaves.png": ("redwood", 1.00),
    "dark_oak_leaves.png": ("oak", 0.70),
    "mangrove_leaves.png": ("banyan", 0.92),
    "cherry_leaves.png": ("maple", 1.00),
    "pale_oak_leaves.png": ("aspen", 0.95),
    "orange_poplar_leaves.png": ("aspen", 1.00),
    "red_poplar_leaves.png": ("maple", 0.85),
    "yellow_poplar_leaves.png": ("aspen", 1.08),
    "azalea_leaves.png": ("oak", 1.08),
    "flowering_azalea_leaves.png": ("oak", 1.08),
}

if not ARCHIVE.is_file() or not BLOCKS.is_dir() or not BACKUP.is_dir():
    raise SystemExit("Hytale archive, PyCraft assets, or original leaf backup is missing.")

def make_block_leaf(source_image, brightness):
    src = source_image.convert("RGBA")
    alpha = src.getchannel("A")
    bbox = alpha.getbbox()
    if not bbox:
        raise ValueError("Empty Hytale foliage texture")

    # Remove transparent padding from the source, then keep the leaf cluster
    # smaller than the block face so transparent gaps remain around it.
    crop = src.crop(bbox)
    cluster = crop.resize((12, 12), Image.Resampling.LANCZOS)
    r, g, b, a = cluster.split()
    if brightness != 1.0:
        from PIL import ImageEnhance
        rgb = Image.merge("RGB", (r, g, b))
        rgb = ImageEnhance.Brightness(rgb).enhance(brightness)
        r, g, b = rgb.split()
    # Convert soft antialiasing to clean pixel-art transparency.
    a = a.point(lambda value: 255 if value >= 96 else (0 if value < 48 else int((value - 48) * 255 / 48)))
    cluster = Image.merge("RGBA", (r, g, b, a))
    tile = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    tile.alpha_composite(cluster, (2, 2))
    return tile

with ZipFile(ARCHIVE) as z:
    available = set(z.namelist())
    cache, changed = {}, []
    for filename, (key, brightness) in TARGETS.items():
        target = BLOCKS / filename
        if not target.is_file():
            continue
        source_path = SOURCE[key]
        if source_path not in available:
            print("Missing Hytale source:", source_path)
            continue
        if key not in cache:
            cache[key] = Image.open(io.BytesIO(z.read(source_path))).convert("RGBA")
        make_block_leaf(cache[key], brightness).save(target, "PNG", optimize=True)
        changed.append({"target": filename, "source": source_path,
                        "cluster_size": "12x12", "transparent_border": 2,
                        "alpha": "preserved"})

report = {
    "changed": len(changed),
    "files": changed,
    "original_leaf_backup": str(BACKUP),
    "note": "Leaf-only update. Hytale leaf clusters are smaller than the 16x16 tile and retain transparent gaps."
}
(ROOT / "Hytale_Leaf_Fix_Report.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(report, ensure_ascii=False, indent=2))
