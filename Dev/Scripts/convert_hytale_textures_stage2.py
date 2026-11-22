from pathlib import Path
from zipfile import ZipFile
from PIL import Image
import shutil, json

ROOT = Path(r"C:\Users\İlter\Desktop\PyCraft")
BLOCKS, ITEMS = ROOT/"Assets"/"block", ROOT/"Assets"/"item"
ARCHIVE = Path(r"C:\Users\İlter\AppData\Roaming\Hytale\install\release\package\game\latest\Assets.zip")
BACKUP = ROOT/"Hytale_Conversion_Backup_Stage2"
if not ARCHIVE.is_file() or not BLOCKS.is_dir() or not ITEMS.is_dir():
    raise SystemExit("PyCraft or Hytale source archive not found.")
if BACKUP.exists():
    raise SystemExit("Stage 2 backup already exists; refusing to overwrite it.")
shutil.copytree(BLOCKS, BACKUP/"block")
shutil.copytree(ITEMS, BACKUP/"item")

# Minecraft texture filename -> semantically equivalent Hytale source texture.
B = {
# terrain / fluids
"grass_block_top":"Soil_Grass_Deep", "grass_block_side":"Soil_Grass_Deep_Side",
"grass_block_side_overlay":"Soil_Grass_Deep_Side", "grass_block_snow":"Soil_Grass_Cold_Top",
"dirt":"Soil_Dirt", "coarse_dirt":"Soil_Dirt", "rooted_dirt":"Soil_Dirt",
"mud":"Soil_Mud", "clay":"Soil_Clay", "sand":"Soil_Sand", "red_sand":"Soil_Sand_Red",
"gravel":"Soil_Gravel", "snow":"Soil_Snow", "powder_snow":"Soil_Snow",
"ice":"Rock_Ice", "packed_ice":"Rock_Ice", "blue_ice":"Rock_Ice",
"water_still":"Fluid_Water", "water_flow":"Fluid_Water", "water_overlay":"Fluid_Water",
"lava_still":"Fluid_Lava", "lava_flow":"Fluid_Lava", "obsidian":"Rock_Obsidian",
"bedrock":"Rock_Bedrock", "stone":"Rock_Stone", "cobblestone":"Rock_Stone_Cobble",
"mossy_cobblestone":"Rock_Stone_Cobble_Mossy", "stone_bricks":"Rock_Stone_Brick",
"cracked_stone_bricks":"Rock_Stone_Brick", "mossy_stone_bricks":"Rock_Stone_Brick_Mossy",
"chiseled_stone_bricks":"Rock_Stone_Brick_Decorative", "smooth_stone":"Rock_Stone",
"andesite":"Rock_Stone", "polished_andesite":"Rock_Stone_Brick",
"diorite":"Rock_Chalk", "polished_diorite":"Rock_Chalk",
"granite":"Rock_Limestone", "polished_granite":"Rock_Limestone",
"deepslate":"Rock_Slate", "cobbled_deepslate":"Rock_Slate_Cobble",
"polished_deepslate":"Rock_Slate", "deepslate_bricks":"Rock_Slate_Brick",
"deepslate_tiles":"Rock_Slate_Brick", "tuff":"Rock_Volcanic",
"calcite":"Rock_White", "dripstone_block":"Rock_Limestone",
"sandstone":"Rock_Sandstone_Side", "sandstone_top":"Rock_Sandstone_Top",
"sandstone_bottom":"Rock_Sandstone_Top", "cut_sandstone":"Rock_Sandstone_Side",
"chiseled_sandstone":"Rock_Sandstone_Decorative",
"red_sandstone":"Rock_Sandstone_Red", "red_sandstone_top":"Rock_Sandstone_Red",
"red_sandstone_bottom":"Rock_Sandstone_Red",
"netherrack":"Rock_Volcanic", "nether_bricks":"Rock_Volcanic_Brick",
"blackstone":"Rock_Basalt", "blackstone_top":"Rock_Basalt",
"basalt_side":"Rock_Basalt", "basalt_top":"Rock_Basalt",
"end_stone":"Rock_White", "end_stone_bricks":"Rock_White_Brick",
"bricks":"Rock_Stone_Brick", "magma":"Rock_Magma",
"moss_block":"Soil_Moss", "mycelium_top":"Soil_Mushroom", "mycelium_side":"Soil_Mushroom_Side",
"podzol_top":"Soil_Dirt", "podzol_side":"Soil_Dirt",
"farmland":"Soil_Dirt_Tilled", "farmland_moist":"Soil_Dirt_Tilled_Watered",
"hay_block_side":"Plant_Straw", "hay_block_top":"Plant_Straw",
"cactus_side":"Plant_Cactus", "cactus_top":"Plant_Cactus", "cactus_bottom":"Plant_Cactus",
"pumpkin_side":"Plant_Pumpkin", "pumpkin_top":"Plant_Pumpkin",
"melon_side":"Plant_Melon", "melon_top":"Plant_Melon",
"bookshelf":"Wood_Softwood_Planks_02",
"glass":"Glass_Clear", "glass_pane_top":"Glass_Clear",
"glowstone":"Rock_Crystal", "sponge":"Plant_Sponge", "wet_sponge":"Plant_Sponge",
# ores, blocks
"coal_ore":"Ore_Coal_Stone", "deepslate_coal_ore":"Ore_Coal_Slate",
"iron_ore":"Ore_Iron_Stone", "deepslate_iron_ore":"Ore_Iron_Slate",
"gold_ore":"Ore_Gold_Stone", "deepslate_gold_ore":"Ore_Gold_Slate",
"copper_ore":"Ore_Copper_Stone", "deepslate_copper_ore":"Ore_Copper_Shale",
"diamond_ore":"Ore_Cobalt_Stone", "deepslate_diamond_ore":"Ore_Cobalt_Shale",
"emerald_ore":"Ore_Adamantite_Stone", "deepslate_emerald_ore":"Ore_Adamantite_Shale",
"lapis_ore":"Ore_Silver_Stone", "deepslate_lapis_ore":"Ore_Silver_Shale",
"redstone_ore":"Ore_Copper_Stone", "deepslate_redstone_ore":"Ore_Copper_Shale",
"nether_gold_ore":"Ore_Gold_Volcanic", "nether_quartz_ore":"Ore_Silver_Volcanic",
"coal_block":"Ore_Coal_Stone", "iron_block":"Ingredient_Bar_Iron",
"gold_block":"Ingredient_Bar_Gold", "copper_block":"Ingredient_Bar_Copper",
"diamond_block":"Ore_Cobalt_Stone", "emerald_block":"Ore_Adamantite_Stone",
"lapis_block":"Ore_Silver_Stone", "redstone_block":"Ore_Copper_Stone",
"raw_iron_block":"Ore_Iron_Stone", "raw_gold_block":"Ore_Gold_Stone",
"raw_copper_block":"Ore_Copper_Stone", "amethyst_block":"Rock_Crystal",
"ancient_debris_side":"Rock_Volcanic", "ancient_debris_top":"Rock_Volcanic",
# wood families, planks/logs
"oak_planks":"Wood_Softwood_Planks_02", "oak_log":"Wood_Trunk_Oak_Side",
"oak_log_top":"Wood_Trunk_Oak_Top", "stripped_oak_log":"Wood_Trunk_Oak_Side",
"stripped_oak_log_top":"Wood_Trunk_Oak_Top", "oak_leaves":"Plant_Oak_Leaves",
"oak_sapling":"Plant_Sapling_Oak",
"birch_planks":"Wood_Hardwood_Planks", "birch_log":"Wood_Trunk_Birch_Side",
"birch_log_top":"Wood_Trunk_Birch_Top", "stripped_birch_log":"Wood_Trunk_Birch_Side",
"stripped_birch_log_top":"Wood_Trunk_Birch_Top", "birch_leaves":"Plant_Birch_Leaves",
"birch_sapling":"Plant_Sapling_Oak",
"spruce_planks":"Wood_Darkwood_Planks", "spruce_log":"Wood_Trunk_Cedar",
"spruce_log_top":"Wood_Trunk_Cedar_Top", "stripped_spruce_log":"Wood_Trunk_Cedar",
"stripped_spruce_log_top":"Wood_Trunk_Cedar_Top", "spruce_leaves":"Plant_Leaves_Fir",
"spruce_sapling":"Plant_Sapling_Oak",
"jungle_planks":"Wood_Tropicalwood_Planks", "jungle_log":"Wood_Trunk_Jungle_Side",
"jungle_log_top":"Wood_Trunk_Jungle_Top", "jungle_leaves":"Plant_Tropical_Leaves",
"jungle_sapling":"Plant_Sapling_Oak",
"acacia_planks":"Wood_Redwood_Planks", "acacia_log":"Wood_Trunk_RedWood",
"acacia_log_top":"Wood_Trunk_RedWood_Top", "acacia_leaves":"Plant_Redwood_Leaves",
"acacia_sapling":"Plant_Redwood_Sapling",
"dark_oak_planks":"Wood_Blackwood_Planks", "dark_oak_log":"Wood_Trunk_Ash_Side",
"dark_oak_log_top":"Wood_Trunk_Ash_Top", "dark_oak_leaves":"Plant_Ash_Leaves",
"dark_oak_sapling":"Plant_Ash_Leaves",
"mangrove_planks":"Wood_Drywood_Planks", "mangrove_log":"Wood_Trunk_Banyan_Side",
"mangrove_log_top":"Wood_Trunk_Banyan_Top", "mangrove_leaves":"Plant_Banyan_Leaves",
"cherry_planks":"Wood_Pinkwood_Planks", "cherry_log":"Wood_Trunk_CrimsonMaple_Side",
"cherry_log_top":"Wood_Trunk_CrimsonMaple_Top", "cherry_leaves":"Plant_Maple_Leaves",
"pale_oak_planks":"Wood_Lightwood_Planks", "pale_oak_log":"Wood_Trunk_Aspen_Side",
"pale_oak_log_top":"Wood_Trunk_Aspen_Top", "pale_oak_leaves":"Plant_Aspen_Leaves",
"poplar_planks":"Wood_Goldenwood_Planks", "poplar_log":"Wood_Trunk_Aspen_Side",
"poplar_log_top":"Wood_Trunk_Aspen_Top",
"bamboo_block":"Wood_Trunk_Bamboo", "bamboo_block_top":"Wood_Trunk_Bamboo_Top",
"bamboo_planks":"Wood_Tropicalwood_Planks", "bamboo_mosaic":"Wood_Tropicalwood_Planks",
"crimson_stem":"Wood_Trunk_Fire", "crimson_stem_top":"Wood_Trunk_Fire_Top",
"crimson_planks":"Wood_Redwood_Planks", "warped_stem":"Wood_Trunk_Crystal",
"warped_stem_top":"Wood_Trunk_Crystal_Top", "warped_planks":"Wood_Blackwood_Planks",
"stripped_acacia_log":"Wood_Trunk_RedWood", "stripped_acacia_log_top":"Wood_Trunk_RedWood_Top",
"stripped_dark_oak_log":"Wood_Trunk_Ash_Side", "stripped_dark_oak_log_top":"Wood_Trunk_Ash_Top",
"stripped_jungle_log":"Wood_Trunk_Jungle_Side", "stripped_jungle_log_top":"Wood_Trunk_Jungle_Top",
"stripped_mangrove_log":"Wood_Trunk_Banyan_Side", "stripped_mangrove_log_top":"Wood_Trunk_Banyan_Top",
"stripped_cherry_log":"Wood_Trunk_CrimsonMaple_Side", "stripped_cherry_log_top":"Wood_Trunk_CrimsonMaple_Top",
"stripped_bamboo_block":"Wood_Trunk_Bamboo", "stripped_bamboo_block_top":"Wood_Trunk_Bamboo_Top",
# leaves/folliage/flowers/vegetation
"azalea_leaves":"Plant_Rhododendron_Pink_Leaves",
"flowering_azalea_leaves":"Plant_Rhododendron_Pink_Leaves",
"vine":"Plant_Vine", "glow_lichen":"Plant_Glow_Moss", "hanging_roots":"Plant_Roots_Leafy",
"fern":"Plant_Fern", "large_fern_bottom":"Plant_Fern", "large_fern_top":"Plant_Fern",
"tall_grass_bottom":"Plant_Grass_Tall", "tall_grass_top":"Plant_Grass_Tall",
"short_grass":"Plant_Grass_Short", "dead_bush":"Plant_Grass_Dry",
"bush":"Plant_Bush", "dandelion":"Plant_Flower_Yellow", "poppy":"Plant_Flower_Red",
"blue_orchid":"Plant_Flower_Water_Blue", "allium":"Plant_Flower_Purple",
"azure_bluet":"Plant_Flower_White", "cornflower":"Plant_Flower_Blue",
"lily_of_the_valley":"Plant_Flower_White", "oxeye_daisy":"Plant_Flower_White",
"sunflower_bottom":"Plant_Flower_Sunflower", "sunflower_top":"Plant_Flower_Sunflower",
"lilac_bottom":"Plant_Flower_Purple", "lilac_top":"Plant_Flower_Purple",
"peony_bottom":"Plant_Flower_Pink", "peony_top":"Plant_Flower_Pink",
"rose_bush_bottom":"Plant_Flower_Red", "rose_bush_top":"Plant_Flower_Red",
"lily_pad":"Plant_Flower_Water_Green", "seagrass":"Plant_Grass_Water_Tall",
"kelp":"Plant_Grass_Water_Tall", "kelp_plant":"Plant_Grass_Water_Tall",
"moss_carpet":"Soil_Leaves", "leaf_litter":"Soil_Leaves_Autumn",
"pink_petals":"Plant_Flower_Pink", "spore_blossom":"Plant_Flower_Pink",
"cobweb":"Plant_Web", "sugar_cane":"Plant_Reed", "cocoa_stage0":"Plant_Cocoa",
"cocoa_stage1":"Plant_Cocoa", "cocoa_stage2":"Plant_Cocoa",
"wheat_stage0":"Plant_Crop_Wheat", "wheat_stage1":"Plant_Crop_Wheat",
"wheat_stage2":"Plant_Crop_Wheat", "wheat_stage3":"Plant_Crop_Wheat",
"wheat_stage4":"Plant_Crop_Wheat", "wheat_stage5":"Plant_Crop_Wheat",
"wheat_stage6":"Plant_Crop_Wheat", "wheat_stage7":"Plant_Crop_Wheat",
"carrots_stage0":"Plant_Crop_Carrot", "carrots_stage1":"Plant_Crop_Carrot",
"carrots_stage2":"Plant_Crop_Carrot", "carrots_stage3":"Plant_Crop_Carrot",
"potatoes_stage0":"Plant_Crop_Potato", "potatoes_stage1":"Plant_Crop_Potato",
"potatoes_stage2":"Plant_Crop_Potato", "potatoes_stage3":"Plant_Crop_Potato",
"beetroots_stage0":"Plant_Crop_Beetroot", "beetroots_stage1":"Plant_Crop_Beetroot",
"beetroots_stage2":"Plant_Crop_Beetroot", "beetroots_stage3":"Plant_Crop_Beetroot",
# colors use Hytale cloth palette where Minecraft has no exact counterpart
}
for color in ("White","Black","Red","Blue","Green","Yellow","Orange","Purple","Pink","Brown","Gray","LightGray","LightBlue","Lime","Magenta","Cyan"):
    mc = color.lower()
    hy = color
    B[f"{mc}_wool"] = f"Cloth_{hy}"
    B[f"{mc}_carpet"] = f"Cloth_{hy}"
# items
I = {
"apple":"Plant_Fruit_Apple", "bread":"Food_Bread", "carrot":"Plant_Crop_Carrot",
"potato":"Plant_Crop_Potato", "beetroot":"Plant_Crop_Beetroot", "wheat":"Plant_Crop_Wheat",
"wheat_seeds":"Plant_Seeds_Wheat", "melon_slice":"Plant_Fruit_Melon",
"pumpkin_pie":"Food_Pie_Apple", "cookie":"Food_Biscuit", "cake":"Food_Cake",
"coal":"Ingredient_Coal", "charcoal":"Ingredient_Coal", "iron_ingot":"Ingredient_Bar_Iron",
"gold_ingot":"Ingredient_Bar_Gold", "copper_ingot":"Ingredient_Bar_Copper",
"diamond":"Ore_Cobalt", "emerald":"Ore_Adamantite", "lapis_lazuli":"Ore_Silver",
"raw_iron":"Ore_Iron", "raw_gold":"Ore_Gold", "raw_copper":"Ore_Copper",
"iron_nugget":"Ingredient_Bar_Iron", "gold_nugget":"Ingredient_Bar_Gold",
"wooden_pickaxe":"Tool_Pickaxe_Wood", "stone_pickaxe":"Tool_Pickaxe_Crude",
"iron_pickaxe":"Tool_Pickaxe_Iron", "diamond_pickaxe":"Tool_Pickaxe_Cobalt",
"wooden_sword":"Weapon_Sword_Wood", "stone_sword":"Weapon_Sword_Crude",
"iron_sword":"Weapon_Sword_Iron", "diamond_sword":"Weapon_Sword_Cobalt",
"wooden_axe":"Weapon_Axe_Crude", "stone_axe":"Weapon_Axe_Stone_Trork",
"iron_axe":"Weapon_Axe_Iron", "diamond_axe":"Weapon_Axe_Cobalt",
"wooden_shovel":"Tool_Shovel_Crude", "stone_shovel":"Tool_Shovel_Crude",
"iron_shovel":"Tool_Shovel_Iron", "diamond_shovel":"Tool_Shovel_Cobalt",
"wooden_hoe":"Tool_Hoe_Wood", "stone_hoe":"Tool_Hoe_Crude",
"iron_hoe":"Tool_Hoe_Iron", "diamond_hoe":"Tool_Hoe_Cobalt",
"bucket":"Container_Bucket", "water_bucket":"Container_Bucket_Water",
"lava_bucket":"Container_Bucket_Lava", "milk_bucket":"Container_Bucket_Milk",
"torch":"Furniture_Crude_Torch", "lantern":"Furniture_Ancient_Torch",
"stick":"Wood_Oak_Branch_Short", "arrow":"Weapon_Arrow",
"bow":"Weapon_Bow_Crude", "flint":"Ingredient_Flint",
"flint_and_steel":"Tool_Firestarter", "string":"Ingredient_Fiber",
"feather":"Ingredient_Feather", "bone":"Ingredient_Bone", "bone_meal":"Ingredient_Bone_Meal",
"leather":"Ingredient_Leather", "paper":"Ingredient_Paper", "book":"Ingredient_Book",
"ender_pearl":"Ingredient_Crystal", "blaze_rod":"Ingredient_Rod_Fire",
"gunpowder":"Ingredient_Powder", "slime_ball":"Ingredient_Slime",
"cooked_beef":"Food_Cooked_Beef", "beef":"Food_Raw_Beef",
"cooked_chicken":"Food_Cooked_Chicken", "chicken":"Food_Raw_Chicken",
"cooked_porkchop":"Food_Cooked_Pork", "porkchop":"Food_Raw_Pork",
"cooked_mutton":"Food_Cooked_Mutton", "mutton":"Food_Raw_Mutton",
"cooked_cod":"Food_Cooked_Fish", "cod":"Food_Raw_Fish",
"cooked_salmon":"Food_Cooked_Fish", "salmon":"Food_Raw_Fish",
"baked_potato":"Food_Baked_Potato", "golden_apple":"Plant_Fruit_Apple",
"carrot_on_a_stick":"Tool_Fishing_Rod", "fishing_rod":"Tool_Fishing_Rod",
"compass_00":"Tool_Compass", "clock_00":"Tool_Clock",
}
def image_source(z, src, dest, size=None):
    try:
        with z.open(src) as f:
            im = Image.open(f).convert("RGBA")
            if size: im = im.resize(size, Image.Resampling.LANCZOS)
            im.save(dest, "PNG", optimize=True)
        return True
    except (KeyError, OSError):
        return False

with ZipFile(ARCHIVE) as z:
    names = z.namelist()
    block_src = {Path(n).stem.lower():n for n in names if n.startswith("Common/BlockTextures/") and n.lower().endswith(".png")}
    icon_src = {Path(n).stem.lower():n for n in names if n.startswith("Common/Icons/ItemsGenerated/") and n.lower().endswith(".png")}
    block_ok, block_miss, item_ok, item_miss = [], [], [], []
    for target, source in B.items():
        src = block_src.get(source.lower()) or icon_src.get(source.lower())
        dest = BLOCKS/(target+".png")
        if src and dest.is_file() and image_source(z,src,dest,(16,16)):
            block_ok.append((target,src))
        elif dest.is_file(): block_miss.append((target,source))
    for target, source in I.items():
        src = icon_src.get(source.lower()) or block_src.get(source.lower())
        dest = ITEMS/(target+".png")
        if src and dest.is_file() and image_source(z,src,dest,(16,16)):
            item_ok.append((target,src))
        elif dest.is_file(): item_miss.append((target,source))
report = {
"stage":"2 semantic expansion", "backup":str(BACKUP),
"block_textures_replaced":len(block_ok), "item_textures_replaced":len(item_ok),
"block_misses":block_miss, "item_misses":item_miss,
"block_matches":[{"minecraft":a,"hytale":b} for a,b in block_ok],
"item_matches":[{"minecraft":a,"hytale":b} for a,b in item_ok],
"note":"Only existing PyCraft filenames were replaced; unmatched files preserved."
}
(ROOT/"Hytale_Conversion_Report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"blocks":len(block_ok),"items":len(item_ok),"block_misses":block_miss[:25],"item_misses":item_miss[:25],"backup":str(BACKUP)},ensure_ascii=False,indent=2))
