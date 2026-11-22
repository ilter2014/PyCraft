from pathlib import Path
from zipfile import ZipFile
from PIL import Image
import io, json, shutil, math, colorsys

ROOT = Path(r"C:\Users\İlter\Desktop\PyCraft")
BLOCKS = ROOT / "Assets" / "block"
ARCHIVE = Path(r"C:\Users\İlter\AppData\Roaming\Hytale\install\release\package\game\latest\Assets.zip")
BACKUP = ROOT / "Hytale_Ore_Textures_Backup_20261122"

# (ore-bearing texture, matching source host for vein mask, displayed host rock, color)
MAPPING = {
    "coal_ore.png": ("Common/BlockTextures/Rock_Basalt_Iron_Cracks.png", "Common/BlockTextures/Rock_Basalt.png", "Common/BlockTextures/Rock_Basalt.png", "coal"),
    "iron_ore.png": ("Common/BlockTextures/Rock_Basalt_Iron_Cracks02.png", "Common/BlockTextures/Rock_Basalt.png", "Common/BlockTextures/Rock_Basalt.png", "iron"),
    "copper_ore.png": ("Common/BlockTextures/Rock_Basalt_Iron_Cracks03.png", "Common/BlockTextures/Rock_Basalt.png", "Common/BlockTextures/Rock_Basalt.png", "copper"),
    "gold_ore.png": ("Common/BlockTextures/Soil_Mud_Dry_Thorium_Cracks02.png", "Common/BlockTextures/Soil_Mud_Dry.png", "Common/BlockTextures/Rock_Stone.png", "gold"),
    "diamond_ore.png": ("Common/BlockTextures/Rock_Slate_Cobalt_Cracks03.png", "Common/BlockTextures/Rock_Slate.png", "Common/BlockTextures/Rock_Slate.png", "diamond"),
    "lapis_ore.png": ("Common/BlockTextures/Rock_Slate_Cobalt_Cracks02.png", "Common/BlockTextures/Rock_Slate.png", "Common/BlockTextures/Rock_Slate.png", "lapis"),
    "emerald_ore.png": ("Common/BlockTextures/Soil_Mud_Dry_Thorium_Cracks.png", "Common/BlockTextures/Soil_Mud_Dry.png", "Common/BlockTextures/Rock_Stone.png", "emerald"),
    "redstone_ore.png": ("Common/BlockTextures/Rock_Magma_Cooled_Adamantite_Cracks02.png", "Common/BlockTextures/Rock_Magma_Cooled.png", "Common/BlockTextures/Rock_Magma_Cooled.png", "redstone"),
}

def recolor(kind, rgb):
    r, g, b = rgb
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    if kind == "iron": return (min(255, int(160+v*70)), min(255, int(165+v*65)), min(255, int(155+v*65)))
    if kind == "coal": return (max(8,int(r*.22)), max(8,int(g*.22)), max(8,int(b*.24)))
    if kind == "copper": return (min(255,int(165+v*70)), min(255,int(76+v*52)), min(255,int(35+v*28)))
    if kind == "gold": return (min(255,int(190+v*60)), min(255,int(135+v*70)), min(255,int(25+v*28)))
    if kind == "diamond": return (min(255,int(60+v*70)), min(255,int(190+v*60)), min(255,int(205+v*50)))
    if kind == "lapis": return (min(255,int(28+v*40)), min(255,int(65+v*65)), min(255,int(165+v*85)))
    if kind == "emerald": return (min(255,int(30+v*35)), min(255,int(145+v*85)), min(255,int(75+v*65)))
    if kind == "redstone": return (min(255,int(175+v*75)), min(255,int(28+v*32)), min(255,int(22+v*25)))
    return rgb

def make_texture(ore, mask_host, display_host, kind):
    size = ore.size
    if mask_host.size != size: mask_host = mask_host.resize(size, Image.Resampling.BILINEAR)
    if display_host.size != size: display_host = display_host.resize(size, Image.Resampling.BILINEAR)
    op, hp = ore.convert("RGB").load(), mask_host.convert("RGB").load()
    out = display_host.convert("RGB")
    dst = out.load()
    for y in range(size[1]):
        for x in range(size[0]):
            a, b = op[x,y], hp[x,y]
            diff = math.sqrt(sum((a[i]-b[i])**2 for i in range(3)))
            threshold = 42 if kind == "coal" else 30
            if diff >= threshold:
                dst[x,y] = recolor(kind, a)
    return out

if not ARCHIVE.is_file() or not BLOCKS.is_dir() or not BACKUP.is_dir():
    raise SystemExit("Archive, assets, or original ore backup missing.")
changed = []
with ZipFile(ARCHIVE) as z:
    available = set(z.namelist())
    for name, (ore_path, mask_path, host_path, kind) in MAPPING.items():
        target = BLOCKS / name
        if not target.is_file() or any(p not in available for p in (ore_path, mask_path, host_path)):
            print("SKIP:", name)
            continue
        shutil.copy2(BACKUP / name, target)
        ore = Image.open(io.BytesIO(z.read(ore_path))).convert("RGB")
        mask_host = Image.open(io.BytesIO(z.read(mask_path))).convert("RGB")
        host = Image.open(io.BytesIO(z.read(host_path))).convert("RGB")
        tile = make_texture(ore, mask_host, host, kind).resize((16,16), Image.Resampling.LANCZOS)
        tile.save(target, "PNG", optimize=True)
        changed.append({"target":name,"vein_source":ore_path,"mask_host":mask_path,
                        "display_host":host_path,"style":kind,"output":"16x16"})
report={"changed":len(changed),"files":changed,"original_backup":str(BACKUP)}
(ROOT/"Hytale_Ore_Textures_Report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(report,ensure_ascii=False,indent=2))
