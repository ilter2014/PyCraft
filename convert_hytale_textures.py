from pathlib import Path
from zipfile import ZipFile
from PIL import Image
import shutil, json, re

root = Path(r"C:\Users\İlter\Desktop\PyCraft")
assets = root / "Assets"
block_dir, item_dir = assets / "block", assets / "item"
archive = Path(r"C:\Users\İlter\AppData\Roaming\Hytale\install\release\package\game\latest\Assets.zip")
backup = root / "Hytale_Conversion_Backup"
if not block_dir.is_dir() or not item_dir.is_dir() or not archive.is_file():
    raise SystemExit("Required PyCraft or Hytale assets were not found.")
if backup.exists():
    raise SystemExit(f"Backup already exists; refusing to overwrite: {backup}")
shutil.copytree(block_dir, backup / "block")
shutil.copytree(item_dir, backup / "item")

block_map = {
"grass_block_top":"Soil_Grass_Deep", "grass_block_side":"Soil_Grass_Deep_Side",
"dirt":"Soil_Dirt", "stone":"Rock_Stone", "cobblestone":"Rock_Stone_Cobble_Side",
"mossy_cobblestone":"Rock_Stone_Cobble_Mossy", "oak_log":"Wood_Trunk_Oak_Side",
"oak_log_top":"Wood_Trunk_Oak_Top", "birch_log":"Wood_Trunk_Birch_Side",
"birch_log_top":"Wood_Trunk_Birch_Top", "spruce_log":"Wood_Trunk_Cedar_Side",
"spruce_log_top":"Wood_Trunk_Cedar_Top", "oak_planks":"Wood_Softwood_Planks",
"birch_planks":"Wood_Hardwood_Planks", "sand":"Soil_Sand", "gravel":"Soil_Gravel",
"sandstone":"Rock_Sandstone_Side", "sandstone_top":"Rock_Sandstone_Top",
"sandstone_bottom":"Rock_Sandstone_Top", "bedrock":"Rock_Bedrock",
"ice":"Rock_Ice", "snow":"Soil_Snow", "stone_bricks":"Rock_Stone_Brick",
"bricks":"Rock_Stone_Brick", "andesite":"Rock_Stone", "granite":"Rock_Limestone",
"diorite":"Rock_Chalk", "deepslate":"Rock_Slate_Cobble", "netherrack":"Rock_Volcanic_Cobble",
"water_still":"Fluid_Water", "lava_still":"Fluid_Lava",
"white_wool":"Cloth_White", "black_wool":"Cloth_Black", "red_wool":"Cloth_Red",
"blue_wool":"Cloth_Blue", "green_wool":"Cloth_Green", "yellow_wool":"Cloth_Yellow",
}
item_map = {
"bread":"Food_Bread", "iron_ingot":"Ingredient_Bar_Iron",
"gold_ingot":"Ingredient_Bar_Gold", "copper_ingot":"Ingredient_Bar_Copper",
"wooden_pickaxe":"Tool_Pickaxe_Wood", "stone_pickaxe":"Tool_Pickaxe_Crude",
"iron_pickaxe":"Tool_Pickaxe_Iron", "wooden_sword":"Weapon_Sword_Wood",
"stone_sword":"Weapon_Sword_Crude", "iron_sword":"Weapon_Sword_Iron",
"bucket":"Container_Bucket", "water_bucket":"Container_Bucket_Water",
"torch":"Furniture_Crude_Torch", "arrow":"Weapon_Arrow",
"wooden_hoe":"Tool_Hoe_Wood", "wooden_shovel":"Tool_Shovel_Wood",
"iron_axe":"Tool_Axe_Iron", "wooden_axe":"Tool_Axe_Wood",
}
def save_resized(z, source, target):
    try:
        with z.open(source) as f:
            im = Image.open(f).convert("RGBA")
            im = im.resize((16, 16), Image.Resampling.LANCZOS)
            im.save(target, format="PNG", optimize=True)
        return True
    except KeyError:
        return False

with ZipFile(archive) as z:
    names = set(z.namelist())
    block_sources = {Path(n).stem.lower(): n for n in names
                     if n.startswith("Common/BlockTextures/") and n.lower().endswith(".png")}
    item_sources = {Path(n).stem.lower(): n for n in names
                    if n.startswith("Common/Icons/ItemsGenerated/") and n.lower().endswith(".png")}
    changed_blocks, missing_blocks, changed_items, missing_items = [], [], [], []
    for target, stem in block_map.items():
        src = block_sources.get(stem.lower())
        dst = block_dir / f"{target}.png"
        if src and dst.is_file() and save_resized(z, src, dst):
            changed_blocks.append(f"{target}.png <- {src}")
        else:
            missing_blocks.append(target)
    for target, stem in item_map.items():
        src = item_sources.get(stem.lower())
        dst = item_dir / f"{target}.png"
        if src and dst.is_file() and save_resized(z, src, dst):
            changed_items.append(f"{target}.png <- {src}")
        else:
            missing_items.append(target)

report = {
    "backup": str(backup), "block_textures_replaced": len(changed_blocks),
    "item_textures_replaced": len(changed_items),
    "block_matches": changed_blocks, "item_matches": changed_items,
    "unmatched_block_targets": missing_blocks, "unmatched_item_targets": missing_items,
    "note": "Unmatched files were left unchanged. Hytale source archive was not modified."
}
(root / "Hytale_Conversion_Report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps({"backup":str(backup),"blocks":len(changed_blocks),"items":len(changed_items),
                  "unmatched_blocks":missing_blocks,"unmatched_items":missing_items,
                  "report":str(root / 'Hytale_Conversion_Report.json')}, indent=2))
