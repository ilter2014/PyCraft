"""PyCraft - a small Minecraft-style voxel sandbox (optimized build).

A single-file Python game that loads the real Minecraft block textures from
``Assets/block`` and builds a first-person, editable voxel world with OpenGL.

Run:
    python app.py
    python app.py --screenshot shot.png
    python app.py --selftest

Controls:
    WASD move            Mouse look          Space jump
    Shift sprint/fly down F toggle fly        Left/Right click break/place
    Middle click pick    Wheel / 1-9 hotbar  E creative inventory
    F3 debug overlay     F5 third person     Esc pause           R respawn

Optimization summary (vs. the original):
    * Frustum culling per chunk (vectorised AABB test) + front-to-back draw.
    * Indexed quads (4 verts / face instead of 6): -33% VRAM and upload.
    * Chunk meshing trimmed to the occupied height range, run on a thread pool.
    * UI: indexed quads, array('f') batches, cached text geometry.
    * World gen: vectorised ore veins and spawn search (same RNG stream).
    * Clicks reuse the per-frame raycast instead of casting again.
"""

from __future__ import annotations

import argparse
import base64
import io
import getpass
import json
import math
import os
import queue
import re
import socket
import sys
import threading
import time
from array import array
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame
import moderngl

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
ASSET_DIR = ROOT / "Assets"
BLOCK_DIR = ASSET_DIR / "block"
ITEM_DIR = ASSET_DIR / "item"

WINDOW_W, WINDOW_H = 1280, 720
TITLE = "PyCraft"
DEFAULT_PORT = 25565
NET_VERSION = 1
MAX_CHAT = 200
WORLD_SAVE_DIR = ROOT / "Worlds"

CHUNK = 16
WX, WY, WZ = 192, 96, 192
SEA_LEVEL = 32
RENDER_DISTANCE = 128.0
FOG_START, FOG_END = 62.0, 112.0
FOV = 74.0
MAX_REACH = 7.0

GRASS_TINT = (160, 215, 100)
FOLIAGE_TINT = (135, 205, 75)
BIRCH_TINT = (158, 218, 100)
SPRUCE_TINT = (105, 170, 80)
WATER_TINT = (58, 120, 220)

# Water rendering is tuned through Assets/water_settings.json; invalid or
# missing values fall back safely without preventing the game from starting.
WATER_SETTINGS_DEFAULTS = {
    "wave_strength": 0.50,
    "wave_spacing": 1.50,
    "wave_speed": 0.85,
    "wave_count": 6,
    "shore_fade_distance": 2.0,
    "foam_amount": 0.30,
    "detail_strength": 0.58,
    "roughness": 0.22,
}

def load_water_settings() -> dict:
    settings = dict(WATER_SETTINGS_DEFAULTS)
    path = ASSET_DIR / "water_settings.json"
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            for key, default in WATER_SETTINGS_DEFAULTS.items():
                value = loaded.get(key, default)
                if isinstance(value, (int, float)) and math.isfinite(value):
                    settings[key] = value
    except (OSError, ValueError, TypeError):
        pass
    settings["wave_strength"] = float(np.clip(settings["wave_strength"], 0.0, 1.5))
    settings["wave_spacing"] = float(np.clip(settings["wave_spacing"], 0.5, 4.0))
    settings["wave_speed"] = float(np.clip(settings["wave_speed"], 0.1, 2.0))
    settings["wave_count"] = int(np.clip(round(settings["wave_count"]), 1, 8))
    settings["shore_fade_distance"] = float(np.clip(settings["shore_fade_distance"], 0.5, 8.0))
    settings["foam_amount"] = float(np.clip(settings["foam_amount"], 0.0, 1.0))
    settings["detail_strength"] = float(np.clip(settings["detail_strength"], 0.0, 2.0))
    settings["roughness"] = float(np.clip(settings["roughness"], 0.02, 1.0))
    return settings

WATER_SETTINGS = load_water_settings()

SKY_TOP = (0.30, 0.55, 0.92)
SKY_HORIZON = (0.76, 0.87, 0.98)
SUN_DIR = np.array([0.45, 0.62, -0.65], dtype=np.float32)
SUN_DIR /= np.linalg.norm(SUN_DIR)

# Face order: -X, +X, -Y, +Y, -Z, +Z
DIRS = [(-1, 0, 0), (1, 0, 0), (0, -1, 0), (0, 1, 0), (0, 0, -1), (0, 0, 1)]
CORNERS = np.array(
    [
        [[0, 0, 0], [0, 0, 1], [0, 1, 1], [0, 1, 0]],
        [[1, 0, 1], [1, 0, 0], [1, 1, 0], [1, 1, 1]],
        [[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]],
        [[0, 1, 1], [1, 1, 1], [1, 1, 0], [0, 1, 0]],
        [[1, 0, 0], [0, 0, 0], [0, 1, 0], [1, 1, 0]],
        [[0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]],
    ],
    dtype=np.float32,
)
FACE_SHADE = np.array([0.64, 0.78, 0.50, 1.00, 0.84, 0.70], dtype=np.float32)

# Plant cross quads.
PLANT_QUADS = (
    np.array([[0.08, 0.0, 0.08], [0.92, 0.0, 0.92],
              [0.92, 1.0, 0.92], [0.08, 1.0, 0.08]], dtype=np.float32),
    np.array([[0.92, 0.0, 0.08], [0.08, 0.0, 0.92],
              [0.08, 1.0, 0.92], [0.92, 1.0, 0.08]], dtype=np.float32),
)

# Shared quad index buffer: (0,1,2, 0,2,3) + 4*i.  Big enough for any chunk
# layer and for every UI batch.
QUAD_CAP = 131072


# ----------------------------------------------------------------------------
# Math helpers (row-major math matrices, transposed only when uploaded)
# ----------------------------------------------------------------------------

def normalize(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else v


def perspective(fovy_deg: float, aspect: float, near: float, far: float) -> np.ndarray:
    f = 1.0 / math.tan(math.radians(fovy_deg) * 0.5)
    m = np.zeros((4, 4), dtype=np.float32)
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = (2.0 * far * near) / (near - far)
    m[3, 2] = -1.0
    return m


def look_at(eye: np.ndarray, target: np.ndarray, up: np.ndarray) -> np.ndarray:
    f = normalize(target - eye)
    s = normalize(np.cross(f, up))
    u = np.cross(s, f)
    m = np.identity(4, dtype=np.float32)
    m[0, :3] = s
    m[1, :3] = u
    m[2, :3] = -f
    m[0, 3] = -float(np.dot(s, eye))
    m[1, 3] = -float(np.dot(u, eye))
    m[2, 3] = float(np.dot(f, eye))
    return m


def upload_mat(m: np.ndarray) -> bytes:
    return np.ascontiguousarray(m.T, dtype=np.float32).tobytes()


def frustum_planes(vp: np.ndarray) -> np.ndarray:
    """Gribb/Hartmann planes (6,4), normalised, pointing inward."""
    m = vp.astype(np.float64)
    r0, r1, r2, r3 = m[0], m[1], m[2], m[3]
    planes = np.array([r3 + r0, r3 - r0, r3 + r1, r3 - r1, r3 + r2, r3 - r2])
    planes /= np.maximum(np.linalg.norm(planes[:, :3], axis=1, keepdims=True), 1e-12)
    return planes


# ----------------------------------------------------------------------------
# Texture loading / atlas
# ----------------------------------------------------------------------------

class TextureStore:
    """Loads and tints 16x16 textures from any asset directory and packs
    them into one atlas (blocks and items share the same texture)."""

    def __init__(self) -> None:
        self.tiles: list[np.ndarray] = []
        self.index: dict[tuple, int] = {}
        self.warnings: list[str] = []

    def add(self, name: str, tint: tuple[int, int, int] | None = None,
            alpha: float = 1.0, directory: Path | None = None) -> int:
        directory = directory or BLOCK_DIR
        key = (str(directory), name, tint, round(alpha, 3))
        if key in self.index:
            return self.index[key]
        tile = self._load(directory, name, tint, alpha)
        self.tiles.append(tile)
        self.index[key] = len(self.tiles) - 1
        return self.index[key]

    def _load(self, directory: Path, name: str, tint, alpha: float) -> np.ndarray:
        path = directory / f"{name}.png"
        try:
            im = Image.open(path).convert("RGBA")
        except Exception:
            self.warnings.append(f"missing texture: {directory.name}/{name}.png")
            im = Image.new("RGBA", (16, 16), (255, 0, 255, 255))
            for y in range(0, 16, 4):
                for x in range(0, 16, 4):
                    if (x + y) % 8 == 0:
                        for yy in range(y, y + 4):
                            for xx in range(x, x + 4):
                                im.putpixel((xx, yy), (20, 20, 20, 255))
        # Animated strips (water / lava / fire / clocks): use the first frame.
        if im.height > im.width:
            im = im.crop((0, 0, im.width, im.width))
        if im.size != (16, 16):
            im = im.resize((16, 16), Image.NEAREST)
        arr = np.asarray(im, dtype=np.float32).copy()
        if tint is not None:
            arr[:, :, :3] *= np.array(tint, dtype=np.float32) / 255.0
        if alpha != 1.0:
            arr[:, :, 3] *= alpha
        return np.clip(arr, 0, 255).astype(np.uint8)

    def pack(self) -> tuple[np.ndarray, np.ndarray]:
        n = len(self.tiles)
        cols = 16
        rows = max(1, math.ceil(n / cols))
        aw, ah = cols * 16, rows * 16
        atlas = np.zeros((ah, aw, 4), dtype=np.uint8)
        uvs = np.zeros((n, 4), dtype=np.float32)
        eps = 0.02
        for i, tile in enumerate(self.tiles):
            cx, cy = (i % cols) * 16, (i // cols) * 16
            atlas[cy:cy + 16, cx:cx + 16] = tile
            # The atlas is flipped vertically for OpenGL upload.
            u0 = (cx + eps) / aw
            u1 = (cx + 16 - eps) / aw
            v0 = (ah - cy - 16 + eps) / ah
            v1 = (ah - cy - eps) / ah
            uvs[i] = (u0, v0, u1, v1)
        return atlas, uvs


TEX = TextureStore()


# ----------------------------------------------------------------------------
# Blocks
# ----------------------------------------------------------------------------

@dataclass(frozen=True)
class Block:
    key: str
    label: str
    top: int
    side: int
    bottom: int
    kind: str = "cube"          # cube | plant | water
    opaque: bool = True
    solid: bool = True


BLOCKS: list[Block] = []


def _label(key: str) -> str:
    special = {
        "tnt": "TNT", "grass_block": "Grass Block", "oak_log": "Oak Log",
        "oak_planks": "Oak Planks", "short_grass": "Short Grass",
        "oxeye_daisy": "Oxeye Daisy", "snow_block": "Snow Block",
        "tnt_side": "TNT", "freeze": "Ice", "light": "Light Block",
        "crossbow": "Crossbow", "tipped_arrow": "Tipped Arrow",
    }
    if key in special:
        return special[key]
    label = key.replace("_", " ").title()
    return (label.replace("Tnt", "TNT").replace("Xp", "XP")
                 .replace("Npc", "NPC"))


def add_block(key: str, top: str, side: str | None = None,
              bottom: str | None = None, *, tint=None,
              tint_top=None, tint_side=None, tint_bottom=None,
              alpha: float = 1.0, kind: str = "cube",
              opaque: bool = True, solid: bool = True) -> int:
    tt = tint_top if tint_top is not None else tint
    ts = tint_side if tint_side is not None else tint
    tb = tint_bottom if tint_bottom is not None else tint
    top_i = TEX.add(top, tt, alpha)
    if side is None:
        side_i = TEX.add(top, tt, alpha)
    else:
        side_i = TEX.add(side, ts, alpha)
    if bottom is None:
        if side is None:
            bot_i = TEX.add(top, tt, alpha)
        else:
            bot_i = TEX.add(side, ts, alpha)
    else:
        bot_i = TEX.add(bottom, tb, alpha)
    if kind == "plant":
        opaque, solid = False, False
    elif kind == "water":
        opaque, solid = False, False
    BLOCKS.append(Block(key, _label(key), top_i, side_i, bot_i,
                        kind, opaque, solid))
    return len(BLOCKS) - 1


# id 0
BLOCKS.append(Block("air", "Air", -1, -1, -1, "air", False, False))

GRASS = add_block("grass_block", "grass_block_top", "grass_block_side", "dirt",
                  tint_top=GRASS_TINT)
DIRT = add_block("dirt", "dirt")
STONE = add_block("stone", "stone")
COBBLE = add_block("cobblestone", "cobblestone")
MOSSY_COBBLE = add_block("mossy_cobblestone", "mossy_cobblestone")
OAK_PLANKS = add_block("oak_planks", "oak_planks")
OAK_LOG = add_block("oak_log", "oak_log_top", "oak_log", "oak_log_top")
OAK_LEAVES = add_block("oak_leaves", "oak_leaves", tint=FOLIAGE_TINT,
                       kind="cube", opaque=False)
BIRCH_LOG = add_block("birch_log", "birch_log_top", "birch_log", "birch_log_top")
BIRCH_LEAVES = add_block("birch_leaves", "birch_leaves", tint=BIRCH_TINT,
                         opaque=False)
SPRUCE_LOG = add_block("spruce_log", "spruce_log_top", "spruce_log", "spruce_log_top")
SPRUCE_LEAVES = add_block("spruce_leaves", "spruce_leaves", tint=SPRUCE_TINT,
                          opaque=False)
SAND = add_block("sand", "sand")
SANDSTONE = add_block("sandstone", "sandstone_top", "sandstone", "sandstone_bottom")
GRAVEL = add_block("gravel", "gravel")
CLAY = add_block("clay", "clay")
COAL_ORE = add_block("coal_ore", "coal_ore")
IRON_ORE = add_block("iron_ore", "iron_ore")
COPPER_ORE = add_block("copper_ore", "copper_ore")
GOLD_ORE = add_block("gold_ore", "gold_ore")
DIAMOND_ORE = add_block("diamond_ore", "diamond_ore")
REDSTONE_ORE = add_block("redstone_ore", "redstone_ore")
LAPIS_ORE = add_block("lapis_ore", "lapis_ore")
EMERALD_ORE = add_block("emerald_ore", "emerald_ore")
BEDROCK = add_block("bedrock", "bedrock")
SNOW_BLOCK = add_block("snow_block", "snow")
ICE = add_block("ice", "ice", opaque=False)
BRICKS = add_block("bricks", "bricks")
STONE_BRICKS = add_block("stone_bricks", "stone_bricks")
BOOKSHELF = add_block("bookshelf", "oak_planks", "bookshelf", "oak_planks")
CRAFTING_TABLE = add_block("crafting_table", "crafting_table_top",
                           "crafting_table_side", "oak_planks")
GLOWSTONE = add_block("glowstone", "glowstone")
OBSIDIAN = add_block("obsidian", "obsidian")
TNT = add_block("tnt", "tnt_top", "tnt_side", "tnt_bottom")
PUMPKIN = add_block("pumpkin", "pumpkin_top", "pumpkin_side", "pumpkin_top")
MELON = add_block("melon", "melon_top", "melon_side", "melon_top")
HAY = add_block("hay_block", "hay_block_top", "hay_block_side", "hay_block_top")
GLASS = add_block("glass", "glass", opaque=False)
WHITE_WOOL = add_block("white_wool", "white_wool")
RED_WOOL = add_block("red_wool", "red_wool")
BLUE_WOOL = add_block("blue_wool", "blue_wool")
YELLOW_WOOL = add_block("yellow_wool", "yellow_wool")
GREEN_WOOL = add_block("green_wool", "green_wool")
BLACK_WOOL = add_block("black_wool", "black_wool")
ANDESITE = add_block("andesite", "andesite")
GRANITE = add_block("granite", "granite")
DIORITE = add_block("diorite", "diorite")
DEEPSLATE = add_block("deepslate", "deepslate")
NETHERRACK = add_block("netherrack", "netherrack")
QUARTZ = add_block("quartz_block", "quartz_block_top", "quartz_block_side",
                    "quartz_block_top")
AMETHYST = add_block("amethyst_block", "amethyst_block")
WATER = add_block("water", "water_still", tint=WATER_TINT, alpha=0.72,
                  kind="water")
LAVA = add_block("lava", "lava_still", kind="water")
SHORT_GRASS = add_block("short_grass", "short_grass", tint=GRASS_TINT, kind="plant")
POPPY = add_block("poppy", "poppy", kind="plant")
DANDELION = add_block("dandelion", "dandelion", kind="plant")
CORNFLOWER = add_block("cornflower", "cornflower", kind="plant")
OXEYE_DAISY = add_block("oxeye_daisy", "oxeye_daisy", kind="plant")
DEAD_BUSH = add_block("dead_bush", "dead_bush", kind="plant")

# ----------------------------------------------------------------------------
# Auto-register every remaining block texture in Assets/block.
#
# Minecraft ships textures, not blockstate JSONs.  We group face textures
# (``_top``/``_bottom``/``_side``/...) and stage variants (``_stage3``) into
# one logical block, then expose all of them in the creative inventory.
# Auxiliary textures (destroy stages, particles, overlays, debug) are skipped.
# ----------------------------------------------------------------------------

_BLOCK_ROLES = (
    "top", "bottom", "side", "front", "back", "end", "inner", "outer",
    "open", "on", "off", "lit", "head", "foot", "tip", "middle", "base",
    "plant", "flow", "still", "particle", "overlay", "emissive", "eye",
    "honey", "fire",
)

_PLANT_WORDS = (
    "sapling", "flower", "grass", "fern", "bush", "mushroom", "torch",
    "vine", "root", "crop", "wheat", "carrot", "potato", "beetroot",
    "berry", "kelp", "seagrass", "lily", "dripleaf", "petal", "sprout",
    "sugar_cane", "cactus_flower", "chorus_flower", "nether_wart", "cocoa",
    "bamboo_sapling", "bamboo_singleleaf", "bamboo_small_leaves",
    "bamboo_large_leaves", "bamboo_stalk", "wildflower", "leaf_litter",
    "pickle", "lichen", "blossom", "propagule", "eyeblossom", "tulip",
    "allium", "bluet", "orchid", "sunflower", "peony", "lilac", "rose_bush",
    "melon_stem", "pumpkin_stem", "vein", "clump", "fire", "coral",
)

_CUBE_EXCEPTIONS = (
    "_block", "_stem", "_log", "_wood", "_planks", "_slab", "_stairs",
    "_wall", "_fence", "_gate", "_door", "_trapdoor", "_sign", "_bed",
    "_pane", "_bars", "_rail", "_button", "_plate", "_chest", "_pot",
    "_table", "_furnace", "_smoker", "_campfire", "_lantern", "_chain",
    "_candle", "_cake", "_anvil", "_beacon", "_bell", "_hopper",
    "_dispenser", "_dropper", "_piston", "_observer", "_repeater",
    "_comparator", "_cauldron", "_composter", "_lectern", "_jukebox",
    "_note", "_conduit", "_portal", "_frame", "_shelf",
)

_AUTO_LEAF_TINT = {
    "acacia_leaves", "dark_oak_leaves", "jungle_leaves", "mangrove_leaves",
}
_AUTO_GRASS_TINT = {"fern", "tall_grass", "large_fern"}


def _variant_rank(name: str) -> int:
    m = re.search(r"_(?:stage|age)_?(\d+)$", name)
    if m:
        return int(m.group(1))
    m = re.search(r"_(\d+)$", name)
    return int(m.group(1)) if m else -1


def _strip_block_role(name: str) -> str:
    if name.startswith("soul_campfire_"):
        return "soul_campfire"
    if name.startswith("campfire_"):
        return "campfire"
    s = name
    changed = True
    while changed:
        changed = False
        for role in _BLOCK_ROLES:
            suffix = "_" + role
            if s.endswith(suffix) and len(s) > len(suffix):
                s = s[:-len(suffix)]
                changed = True
        m = re.search(r"_(?:stage|age)_?\d+$", s)
        if m:
            s = s[:m.start()]
            changed = True
        m = re.search(r"_\d+$", s)
        if m and len(s) > len(m.group(0)):
            s = s[:m.start()]
            changed = True
    return s


def _pick_face(candidates: set[str], base: str, roles: tuple[str, ...]) -> str:
    for role in roles:
        name = f"{base}_{role}"
        if name in candidates:
            return name
    if base in candidates:
        return base
    return max(candidates, key=lambda n: (_variant_rank(n), n))


def _auto_blocks() -> None:
    texture_names = sorted(p.stem for p in BLOCK_DIR.glob("*.png"))
    groups: dict[str, set[str]] = {}
    for name in texture_names:
        if name in ("debug", "debug2"):
            continue
        if name.startswith("destroy_"):
            continue
        if "particle" in name or "overlay" in name:
            continue
        base = _strip_block_role(name)
        if not base or base in BLOCK_IDS:
            continue
        groups.setdefault(base, set()).add(name)

    for base in sorted(groups):
        candidates = groups[base]
        if base in BLOCK_IDS:
            continue
        top_name = _pick_face(candidates, base,
                              ("top", "end", "eye", "fire", "front", "side"))
        side_name = _pick_face(candidates, base,
                               ("side", "front", "back", "top", "end", "fire"))
        bottom_name = _pick_face(candidates, base,
                                 ("bottom", "top", "end", "front", "side"))
        has_top = any(n == f"{base}_{r}" for r in ("top", "end")
                      for n in candidates)
        has_side = f"{base}_side" in candidates
        cube_like = has_top and has_side
        lower = base.lower()

        if "portal" in lower:
            kind = "cube"
        elif cube_like:
            kind = "cube"
        elif any(w in lower for w in _PLANT_WORDS):
            kind = "plant"
        else:
            kind = "cube"

        if any(x in lower for x in _CUBE_EXCEPTIONS):
            kind = "cube"

        tint = None
        if base in _AUTO_LEAF_TINT:
            tint = FOLIAGE_TINT
        elif base == "pale_oak_leaves":
            tint = (205, 220, 195)
        elif base in _AUTO_GRASS_TINT:
            tint = GRASS_TINT

        top_i = TEX.add(top_name, tint)
        side_i = TEX.add(side_name, tint)
        bot_i = TEX.add(bottom_name, tint)
        opaque = True
        if kind == "plant":
            opaque = False
        else:
            alpha_top = TEX.tiles[top_i][:, :, 3]
            alpha_side = TEX.tiles[side_i][:, :, 3]
            if (alpha_top < 250).any() or (alpha_side < 250).any():
                opaque = False
        solid = kind != "plant"
        BLOCKS.append(Block(base, _label(base), top_i, side_i, bot_i,
                            kind, opaque, solid))


AIR = 0
BLOCK_IDS = {b.key: i for i, b in enumerate(BLOCKS)}
_auto_blocks()

# ----------------------------------------------------------------------------
# Items - every usable texture in Assets/item becomes a creative item.
# Animation/state frames are folded into their base item so the inventory
# shows actual items instead of dozens of clock/compass frames.
# ----------------------------------------------------------------------------

@dataclass(frozen=True)
class Item:
    key: str
    label: str
    tile: int


ITEMS: list[Item] = []
ITEM_INDEX: dict[str, int] = {}


def _item_group(name: str) -> str:
    if re.fullmatch(r"clock_\d+", name):
        return "clock"
    if re.fullmatch(r"compass_\d+", name):
        return "compass"
    if re.fullmatch(r"recovery_compass_\d+", name):
        return "recovery_compass"
    if re.fullmatch(r"light_\d+", name):
        return "light"
    if name.startswith("crossbow_"):
        return "crossbow"
    if name in ("tipped_arrow_base", "tipped_arrow_head"):
        return "tipped_arrow"
    return name


def _skip_item(name: str) -> bool:
    if name.endswith("_overlay") or name.endswith("_in_hand"):
        return True
    if name.endswith("_model") or name.endswith("_broken"):
        return True
    if re.search(r"_pulling_\d+$", name):
        return True
    if re.search(r"_open_(front|back)$", name):
        return True
    if name in ("crossbow_arrow", "crossbow_firework"):
        return True
    if name in ("fishing_rod_cast", "elytra_broken", "spyglass_model"):
        return True
    return False


def _register_items() -> None:
    groups: dict[str, list[str]] = {}
    for path in sorted(ITEM_DIR.glob("*.png")):
        name = path.stem
        if _skip_item(name):
            continue
        groups.setdefault(_item_group(name), []).append(name)
    for key in sorted(groups):
        names = groups[key]
        if key in names:
            source = key
        elif key == "crossbow" and "crossbow_standby" in names:
            source = "crossbow_standby"
        elif key == "light" and "light_15" in names:
            source = "light_15"
        elif key == "tipped_arrow" and "tipped_arrow_head" in names:
            source = "tipped_arrow_head"
        else:
            source = sorted(names)[0]
        tile = TEX.add(source, directory=ITEM_DIR)
        ITEM_INDEX[key] = len(ITEMS)
        ITEMS.append(Item(key, _label(key), tile))


_register_items()

N_BLOCKS = len(BLOCKS)
N_ITEMS = len(ITEMS)

FACE_TILE = np.array(
    [[b.side, b.side, b.bottom, b.top, b.side, b.side] for b in BLOCKS],
    dtype=np.int32,
).T
IS_OPAQUE = np.array([b.opaque for b in BLOCKS], dtype=bool)
IS_SOLID = np.array([b.solid for b in BLOCKS], dtype=bool)
IS_CUBE = np.array([b.kind == "cube" for b in BLOCKS], dtype=bool)
IS_PLANT = np.array([b.kind == "plant" for b in BLOCKS], dtype=bool)
IS_WATER = np.array([b.kind == "water" for b in BLOCKS], dtype=bool)
IS_LEAF = np.array(["leaves" in b.key for b in BLOCKS], dtype=bool)

ATLAS_IMAGE, TILE_UVS = TEX.pack()
PLACEABLE = [i for i in range(1, N_BLOCKS) if BLOCKS[i].kind in ("cube", "plant", "water")]
HOTBAR_DEFAULT = [GRASS, DIRT, STONE, COBBLE, OAK_LOG, OAK_PLANKS, SAND,
                  OAK_LEAVES, GLASS]

ITEM_BLOCK_MAP: dict[int, int] = {}
for _i, _item in enumerate(ITEMS):
    _block = BLOCK_IDS.get(_item.key)
    if _block is not None and _block != AIR:
        ITEM_BLOCK_MAP[_i] = _block


def entry_is_item(entry: int) -> bool:
    return entry < 0


def entry_label(entry: int) -> str:
    if entry < 0:
        return ITEMS[-entry - 1].label
    return BLOCKS[entry].label


def entry_block(entry: int) -> int:
    if entry >= 0:
        return entry
    return ITEM_BLOCK_MAP.get(-entry - 1, AIR)


INV_COLS, INV_ROWS = 9, 7
INV_CELL = 52


def inventory_entries(tab: int) -> list[int]:
    if tab == 1:
        return [-(i + 1) for i in range(len(ITEMS))]
    return list(PLACEABLE)


def inventory_page_count(tab: int) -> int:
    per_page = INV_COLS * INV_ROWS
    return max(1, (len(inventory_entries(tab)) + per_page - 1) // per_page)


if TEX.warnings:
    print("[assets] " + ", ".join(TEX.warnings), file=sys.stderr)

# ----------------------------------------------------------------------------
# Extra standalone textures (font, title, panorama, clouds)
# ----------------------------------------------------------------------------

def load_png(name: str, relative_to_assets: bool = True) -> Image.Image | None:
    p = (ASSET_DIR / name) if relative_to_assets else Path(name)
    try:
        return Image.open(p).convert("RGBA")
    except Exception:
        print(f"[assets] missing {p}", file=sys.stderr)
        return None


# ----------------------------------------------------------------------------
# World generation
# ----------------------------------------------------------------------------

@dataclass
class GpuMesh:
    vao: object
    vbo: object
    count: int          # number of *indices* to draw (6 per quad)


def _quads(pw: np.ndarray, quad: np.ndarray, tile_uv: np.ndarray,
           shade) -> np.ndarray:
    """Build (n*4, 7) float32 vertices: xyz, uv, shade and local flex."""
    n = pw.shape[0]
    out = np.empty((n, 4, 7), dtype=np.float32)
    out[:, :, 0:3] = pw[:, None, :] + quad[None, :, :]
    out[:, :, 3] = tile_uv[:, [0, 2, 2, 0]]
    out[:, :, 4] = tile_uv[:, [1, 1, 3, 3]]
    out[:, :, 5] = shade
    out[:, :, 6] = quad[None, :, 1]
    return out.reshape(-1, 7)


def _water_top_quads(pw: np.ndarray, tile_uv: np.ndarray, shade, segments: int = 6, shore_distance=None) -> np.ndarray:
    """Subdivide each water top into a grid for real geometric wave motion."""
    parts = []
    n = len(pw)
    if not n:
        return np.zeros((0, 7), dtype=np.float32)
    for iz in range(segments):
        for ix in range(segments):
            x0, x1 = ix / segments, (ix + 1) / segments
            z0, z1 = iz / segments, (iz + 1) / segments
            q = np.array([[x0, 1, z1], [x1, 1, z1], [x1, 1, z0], [x0, 1, z0]], dtype=np.float32)
            verts = _quads(pw, q, tile_uv, shade).reshape(n, 4, 7)
            uv0 = tile_uv[:, :2]; uv1 = tile_uv[:, 2:]
            uv = np.stack((uv0[:,0] + (uv1[:,0]-uv0[:,0])*x0, uv0[:,1] + (uv1[:,1]-uv0[:,1])*z1,
                           uv0[:,0] + (uv1[:,0]-uv0[:,0])*x1, uv0[:,1] + (uv1[:,1]-uv0[:,1])*z0), axis=1)
            # Preserve a continuous atlas mapping across the subdivided surface.
            verts[:, :, 3] = np.stack((uv0[:,0] + (uv1[:,0]-uv0[:,0])*x0, uv0[:,0] + (uv1[:,0]-uv0[:,0])*x1,
                                       uv0[:,0] + (uv1[:,0]-uv0[:,0])*x1, uv0[:,0] + (uv1[:,0]-uv0[:,0])*x0), axis=1)
            verts[:, :, 4] = np.stack((uv0[:,1] + (uv1[:,1]-uv0[:,1])*z1, uv0[:,1] + (uv1[:,1]-uv0[:,1])*z1,
                                       uv0[:,1] + (uv1[:,1]-uv0[:,1])*z0, uv0[:,1] + (uv1[:,1]-uv0[:,1])*z0), axis=1)
            if shore_distance is not None:
                vx = pw[:, 0, None] + np.array([x0, x1, x1, x0], dtype=np.float32)[None, :]
                vz = pw[:, 2, None] + np.array([z1, z1, z0, z0], dtype=np.float32)[None, :]
                gx_i = np.clip(np.floor(vx).astype(np.int32), 0, WX - 2)
                gz_i = np.clip(np.floor(vz).astype(np.int32), 0, WZ - 2)
                fx = vx - gx_i
                fz = vz - gz_i
                d00 = shore_distance[gx_i, gz_i]
                d10 = shore_distance[gx_i + 1, gz_i]
                d01 = shore_distance[gx_i, gz_i + 1]
                d11 = shore_distance[gx_i + 1, gz_i + 1]
                d0 = d00 * (1.0 - fx) + d10 * fx
                d1 = d01 * (1.0 - fx) + d11 * fx
                dist = d0 * (1.0 - fz) + d1 * fz
                fade = np.clip((dist - 0.25) / max(WATER_SETTINGS["shore_fade_distance"], 0.25), 0.0, 1.0)
                verts[:, :, 6] = fade * fade * (3.0 - 2.0 * fade)
            parts.append(verts.reshape(-1, 7))
    return np.concatenate(parts, axis=0)


def _shore_wash_quads(sand_pos: np.ndarray, tile_uv: np.ndarray, shade,
                      water_dx: int, water_dz: int, segments: int = 6) -> np.ndarray:
    """Thin, subdivided swash sheet over the first sand block at the waterline.
    flex stores normalized distance from the sea edge for the shore shader."""
    if len(sand_pos) == 0:
        return np.zeros((0, 7), dtype=np.float32)
    parts = []
    for i in range(segments):
        d0, d1 = i / segments, (i + 1) / segments
        verts = np.empty((len(sand_pos), 4, 7), dtype=np.float32)
        x0 = np.zeros(len(sand_pos), dtype=np.float32)
        x1 = np.ones(len(sand_pos), dtype=np.float32)
        z0 = np.zeros(len(sand_pos), dtype=np.float32)
        z1 = np.ones(len(sand_pos), dtype=np.float32)
        if water_dx:
            edge = 0.0 if water_dx < 0 else 1.0
            inward = -float(water_dx)
            x0[:] = edge + inward * d0
            x1[:] = edge + inward * d1
        else:
            edge = 0.0 if water_dz < 0 else 1.0
            inward = -float(water_dz)
            z0[:] = edge + inward * d0
            z1[:] = edge + inward * d1
        # Upward-facing top quad winding.
        coords = np.stack((
            np.stack((x0, np.ones_like(x0), z1), axis=1),
            np.stack((x1, np.ones_like(x1), z1), axis=1),
            np.stack((x1, np.ones_like(x1), z0), axis=1),
            np.stack((x0, np.ones_like(x0), z0), axis=1),
        ), axis=1)
        coords[:, :, 1] += 0.012
        verts[:, :, :3] = sand_pos[:, None, :] + coords
        uv0, uv1 = tile_uv[:, :2], tile_uv[:, 2:]
        verts[:, :, 3] = np.stack((uv0[:, 0], uv1[:, 0], uv1[:, 0], uv0[:, 0]), axis=1)
        verts[:, :, 4] = np.stack((uv1[:, 1], uv1[:, 1], uv0[:, 1], uv0[:, 1]), axis=1)
        verts[:, :, 5] = shade
        if water_dx:
            verts[:, :, 6] = np.array([d0, d1, d1, d0], dtype=np.float32)[None, :]
        else:
            verts[:, :, 6] = np.array([d1, d1, d0, d0], dtype=np.float32)[None, :]
        parts.append(verts.reshape(-1, 7))
    return np.concatenate(parts, axis=0)


class World:
    def __init__(self, seed: int = 1337) -> None:
        self.seed = seed
        self.blocks = np.zeros((WX, WY, WZ), dtype=np.uint16)
        self.heights = np.zeros((WX, WZ), dtype=np.int16)
        self.shore_distance = None
        self.spawn = (WX // 2 + 0.5, 64.0, WZ // 2 + 0.5)
        self.spawn_yaw = math.radians(35.0)
        self.spawn_pitch = math.radians(-8.0)
        self.meshes: dict[tuple[int, int], dict[str, GpuMesh]] = {}
        self.chunk_ymax: dict[tuple[int, int], int] = {}
        self.mesh_version = 0
        self.dirty: set[tuple[int, int]] = set()
        self.total_faces = 0
        # Latest value for every block changed since procedural generation.
        self.edits: dict[tuple[int, int, int], int] = {}

    # -- generation ---------------------------------------------------------

    def _noise(self, rng: np.random.Generator, res: int) -> np.ndarray:
        grid = rng.random((res, res)).astype(np.float32)
        img = Image.fromarray((grid * 255).astype(np.uint8), "L")
        img = img.resize((WX, WZ), Image.BICUBIC)
        return np.asarray(img, dtype=np.float32) / 255.0

    def generate(self) -> None:
        rng = np.random.default_rng(self.seed)
        n = (0.55 * self._noise(rng, 5) + 0.27 * self._noise(rng, 9) +
             0.12 * self._noise(rng, 17) + 0.06 * self._noise(rng, 33))
        mount = self._noise(rng, 6)
        heights = 34.0 + (n - 0.5) * 16.0
        heights += np.clip((mount - 0.60) * 2.5, 0.0, 1.0) ** 1.35 * 27.0

        # Winding river across the map.
        zz = np.arange(WZ, dtype=np.float32)[None, :]
        river_x = (WX * 0.50 + np.sin(zz * 0.048 + 1.7) * 18.0 +
                   np.sin(zz * 0.014 + 0.3) * 10.0)
        dist = np.abs(np.arange(WX, dtype=np.float32)[:, None] - river_x)
        river = np.clip(1.0 - dist / 11.0, 0.0, 1.0) ** 1.5
        heights -= river * 13.0
        heights = np.clip(heights, 4, WY - 20).astype(np.int16)
        self.heights = heights
        self.shore_distance = None

        world = self.blocks
        world.fill(AIR)
        yy = np.arange(WY, dtype=np.int16)[None, :, None]
        hh = heights[:, None, :]
        world[yy <= hh] = STONE
        depth = hh - yy
        world[(depth >= 1) & (depth <= 3)] = DIRT
        world[depth == 0] = GRASS

        top = depth == 0
        underwater = top & (hh < SEA_LEVEL)
        beach = top & (hh >= SEA_LEVEL) & (hh <= SEA_LEVEL + 1)
        rocky = top & (hh >= 47) & (hh < 52)
        snowy = top & (hh >= 52)
        world[underwater] = SAND
        world[(depth >= 1) & (depth <= 2) & underwater] = SAND
        world[beach] = SAND
        world[(depth >= 1) & (depth <= 2) & beach] = SAND
        world[rocky] = STONE
        world[snowy] = SNOW_BLOCK
        world[(yy > hh) & (yy <= SEA_LEVEL)] = WATER
        world[:, 0, :] = BEDROCK
        world[:, 1, :][rng.random((WX, WZ)) < 0.4] = BEDROCK

        # Ore veins (vectorised per vein; identical RNG consumption).
        ore_specs = [
            (COAL_ORE, 9, 62, 90, 3), (IRON_ORE, 6, 44, 65, 3),
            (COPPER_ORE, 14, 54, 45, 3), (GOLD_ORE, 4, 26, 28, 2),
            (REDSTONE_ORE, 3, 20, 34, 3), (DIAMOND_ORE, 2, 16, 22, 2),
            (LAPIS_ORE, 4, 24, 20, 2), (EMERALD_ORE, 5, 30, 12, 2),
        ]
        for block_id, ymin, ymax, veins, radius in ore_specs:
            for _ in range(veins):
                cx = int(rng.integers(2, WX - 2))
                cz = int(rng.integers(2, WZ - 2))
                cy = int(rng.integers(ymin, ymax + 1))
                rx = int(rng.integers(1, radius + 1))
                ry = int(rng.integers(1, radius + 1))
                rz = int(rng.integers(1, radius + 1))
                x0, x1 = max(1, cx - rx), min(WX, cx + rx + 1)
                y0, y1 = max(1, cy - ry), min(WY - 1, cy + ry + 1)
                z0, z1 = max(1, cz - rz), min(WZ, cz + rz + 1)
                if x0 >= x1 or y0 >= y1 or z0 >= z1:
                    continue
                gx, gy, gz = np.ogrid[x0:x1, y0:y1, z0:z1]
                ell = (((gx - cx) / rx) ** 2 + ((gy - cy) / ry) ** 2 +
                       ((gz - cz) / rz) ** 2) <= 1.0
                sub = world[x0:x1, y0:y1, z0:z1]
                sub[ell & (sub == STONE)] = block_id

        self._choose_spawn(rng)
        self._grow_trees(rng)
        self._scatter_plants(rng)
        self._clear_spawn()

    def _choose_spawn(self, rng: np.random.Generator) -> None:
        water = self.heights < SEA_LEVEL
        # Summed-area table -> "is there any water within 8 blocks" in O(1).
        sat = np.pad(water.astype(np.int32), ((1, 0), (1, 0))).cumsum(0).cumsum(1)
        xs = np.arange(24, WX - 24, 2)
        zs = np.arange(24, WZ - 24, 2)
        xa, xb = np.maximum(0, xs - 8), np.minimum(WX, xs + 9)
        za, zb = np.maximum(0, zs - 8), np.minimum(WZ, zs + 9)
        wsum = (sat[np.ix_(xb, zb)] - sat[np.ix_(xa, zb)] -
                sat[np.ix_(xb, za)] + sat[np.ix_(xa, za)])
        hsub = self.heights[np.ix_(xs, zs)]
        ok = (hsub >= SEA_LEVEL + 2) & (hsub <= SEA_LEVEL + 8) & (wsum > 0)
        ix, iz = np.nonzero(ok)          # row-major == original loop order
        if ix.size:
            noise = rng.random(ix.size) * 5
            cx_, cz_ = xs[ix], zs[iz]
            score = np.abs(cx_ - WX / 2) + np.abs(cz_ - WZ / 2) + noise
            best = int(np.argmin(score))
            sx, sz = int(cx_[best]), int(cz_[best])
        else:
            sx, sz = WX // 2, WZ // 2
            while self.heights[sx, sz] <= SEA_LEVEL:
                sx = (sx + 1) % (WX - 8) + 4
        h = int(self.heights[sx, sz])
        self.spawn = (sx + 0.5, float(h + 1), sz + 0.5)

        # Pick the most open view, preferring directions that follow the
        # river into the distance instead of staring straight at a hillside.
        eye = h + 1.7
        best_score = -1e9
        best_yaw = self.spawn_yaw
        heights = self.heights
        for step in range(72):
            yaw = step * math.tau / 72
            wcount = blocked = 0
            seen = 0
            sy_, cy_ = math.sin(yaw), math.cos(yaw)
            for d in range(2, 49):
                x = int(sx + 0.5 + sy_ * d)
                z = int(sz + 0.5 - cy_ * d)
                if not (0 <= x < WX and 0 <= z < WZ):
                    break
                seen += 1
                hv = heights[x, z]
                if hv < SEA_LEVEL:
                    wcount += 1
                if hv >= eye:
                    blocked += 1
            if seen < 20:
                continue
            score = wcount * 3.0 - blocked * 4.0
            if 0.25 * seen < wcount < 0.9 * seen:
                score += 8.0
            if score > best_score:
                best_score = score
                best_yaw = yaw
        self.spawn_yaw = best_yaw
        self.spawn_pitch = math.radians(-6.0)

    def _set_raw(self, x: int, y: int, z: int, block: int,
                 only_air: bool = False) -> None:
        if not (0 <= x < WX and 0 <= y < WY and 0 <= z < WZ):
            return
        if only_air and self.blocks[x, y, z] != AIR:
            return
        self.blocks[x, y, z] = block

    def _grow_trees(self, rng: np.random.Generator) -> None:
        trees: list[tuple[int, int]] = []
        sx, _, sz = self.spawn
        kinds = [("oak", OAK_LOG, OAK_LEAVES), ("birch", BIRCH_LOG, BIRCH_LEAVES),
                 ("spruce", SPRUCE_LOG, SPRUCE_LEAVES)]
        weights = [0.52, 0.28, 0.20]
        for _ in range(5000):
            if len(trees) >= 150:
                break
            x = int(rng.integers(7, WX - 7))
            z = int(rng.integers(7, WZ - 7))
            if (x - sx) ** 2 + (z - sz) ** 2 < 121:
                continue
            h = int(self.heights[x, z])
            if h <= SEA_LEVEL + 1 or h >= 46:
                continue
            if self.blocks[x, h, z] != GRASS:
                continue
            if any((x - tx) ** 2 + (z - tz) ** 2 < 36 for tx, tz in trees):
                continue
            kind, log_id, leaf_id = kinds[int(rng.choice(3, p=weights))]
            trunk = int(rng.integers(4, 7)) if kind != "spruce" else int(rng.integers(6, 10))
            base = h + 1
            if base + trunk + 3 >= WY:
                continue
            clear = True
            for y in range(base, base + trunk):
                b = int(self.blocks[x, y, z])
                if b != AIR and b != SHORT_GRASS:
                    clear = False
                    break
            if not clear:
                continue
            for y in range(base, base + trunk):
                self.blocks[x, y, z] = log_id
            top = base + trunk - 1
            for dy in range(-3, 2):
                y = top + dy
                if kind == "spruce":
                    r = 0 if dy == 1 else (1 if dy % 2 == 0 else 2)
                else:
                    r = 1 if dy in (-3, 1) else 2
                for dx in range(-r, r + 1):
                    for dz in range(-r, r + 1):
                        if r > 1 and abs(dx) == r and abs(dz) == r and rng.random() < 0.55:
                            continue
                        if dx == 0 and dz == 0 and y <= top:
                            continue
                        self._set_raw(x + dx, y, z + dz, leaf_id, only_air=True)
            trees.append((x, z))

    def _scatter_plants(self, rng: np.random.Generator) -> None:
        flowers = [POPPY, DANDELION, CORNFLOWER, OXEYE_DAISY]
        for _ in range(8000):
            x = int(rng.integers(1, WX - 1))
            z = int(rng.integers(1, WZ - 1))
            h = int(self.heights[x, z])
            if h < SEA_LEVEL or h > 46:
                continue
            if self.blocks[x, h, z] != GRASS:
                continue
            if self.blocks[x, h + 1, z] != AIR:
                continue
            r = rng.random()
            if r < 0.63:
                self.blocks[x, h + 1, z] = SHORT_GRASS
            elif r < 0.70:
                self.blocks[x, h + 1, z] = DEAD_BUSH
            else:
                self.blocks[x, h + 1, z] = flowers[int(rng.integers(0, len(flowers)))]

    def _clear_spawn(self) -> None:
        sx = int(self.spawn[0])
        sz = int(self.spawn[2])
        for dx in range(-2, 3):
            for dz in range(-2, 3):
                x, z = sx + dx, sz + dz
                if not (0 <= x < WX and 0 <= z < WZ):
                    continue
                h = int(self.heights[x, z])
                for y in range(h + 1, min(h + 5, WY)):
                    if IS_PLANT[self.blocks[x, y, z]]:
                        self.blocks[x, y, z] = AIR

    # -- world access -------------------------------------------------------

    def get(self, x: int, y: int, z: int) -> int:
        if 0 <= x < WX and 0 <= y < WY and 0 <= z < WZ:
            return int(self.blocks[x, y, z])
        return AIR

    def is_solid(self, x: int, y: int, z: int) -> bool:
        if x < 0 or x >= WX or z < 0 or z >= WZ or y < 0:
            return True
        if y >= WY:
            return False
        return bool(IS_SOLID[self.blocks[x, y, z]])

    def is_water(self, x: int, y: int, z: int) -> bool:
        return self.get(x, y, z) == WATER

    def mark_dirty(self, x: int, z: int) -> None:
        ncx, ncz = WX // CHUNK, WZ // CHUNK
        cx, cz = x // CHUNK, z // CHUNK
        lx, lz = x % CHUNK, z % CHUNK
        cand = [(cx, cz)]
        if lx == 0:
            cand.append((cx - 1, cz))
        elif lx == CHUNK - 1:
            cand.append((cx + 1, cz))
        if lz == 0:
            cand.append((cx, cz - 1))
        elif lz == CHUNK - 1:
            cand.append((cx, cz + 1))
        if lx == 0 and lz == 0:
            cand.append((cx - 1, cz - 1))
        elif lx == 0 and lz == CHUNK - 1:
            cand.append((cx - 1, cz + 1))
        elif lx == CHUNK - 1 and lz == 0:
            cand.append((cx + 1, cz - 1))
        elif lx == CHUNK - 1 and lz == CHUNK - 1:
            cand.append((cx + 1, cz + 1))
        for c in cand:
            if 0 <= c[0] < ncx and 0 <= c[1] < ncz:
                self.dirty.add(c)

    def set_block(self, x: int, y: int, z: int, block: int) -> bool:
        if not (0 <= x < WX and 0 <= y < WY and 0 <= z < WZ):
            return False
        if self.blocks[x, y, z] == block:
            return False
        self.blocks[x, y, z] = block
        self.edits[(int(x), int(y), int(z))] = int(block)
        self.mark_dirty(x, z)
        return True

    def break_block(self, x: int, y: int, z: int) -> bool:
        if not (0 <= x < WX and 0 <= y < WY and 0 <= z < WZ):
            return False
        if self.blocks[x, y, z] == AIR:
            return False
        self.set_block(x, y, z, AIR)
        if y + 1 < WY and IS_PLANT[self.blocks[x, y + 1, z]]:
            self.set_block(x, y + 1, z, AIR)
        return True

    def raycast(self, origin: np.ndarray, direction: np.ndarray,
                max_dist: float = MAX_REACH):
        ox, oy, oz = float(origin[0]), float(origin[1]), float(origin[2])
        dx, dy, dz = (float(direction[0]), float(direction[1]),
                      float(direction[2]))
        x, y, z = math.floor(ox), math.floor(oy), math.floor(oz)
        step_x = 1 if dx >= 0 else -1
        step_y = 1 if dy >= 0 else -1
        step_z = 1 if dz >= 0 else -1

        inf = float("inf")
        tdx = abs(1.0 / dx) if abs(dx) > 1e-9 else inf
        tdy = abs(1.0 / dy) if abs(dy) > 1e-9 else inf
        tdz = abs(1.0 / dz) if abs(dz) > 1e-9 else inf
        if dx > 0:
            tmx = (x + 1 - ox) / dx
        elif dx < 0:
            tmx = (x - ox) / dx
        else:
            tmx = inf
        if dy > 0:
            tmy = (y + 1 - oy) / dy
        elif dy < 0:
            tmy = (y - oy) / dy
        else:
            tmy = inf
        if dz > 0:
            tmz = (z + 1 - oz) / dz
        elif dz < 0:
            tmz = (z - oz) / dz
        else:
            tmz = inf

        blocks = self.blocks
        normal = (0, 0, 0)
        t = 0.0
        for _ in range(96):
            if 0 <= x < WX and 0 <= y < WY and 0 <= z < WZ:
                block = int(blocks[x, y, z])
                if block != AIR and block != WATER:
                    return (x, y, z), normal, block
            if tmx < tmy and tmx < tmz:
                t = tmx
                x += step_x
                tmx += tdx
                normal = (-step_x, 0, 0)
            elif tmy < tmz:
                t = tmy
                y += step_y
                tmy += tdy
                normal = (0, -step_y, 0)
            else:
                t = tmz
                z += step_z
                tmz += tdz
                normal = (0, 0, -step_z)
            if t > max_dist:
                break
        return None

    # -- chunk meshing ------------------------------------------------------

    def _column_ymax(self, cx: int, cz: int) -> int:
        """Highest non-air y + 1 in the chunk (0 for an empty chunk)."""
        x0, z0 = cx * CHUNK, cz * CHUNK
        sub = self.blocks[x0:x0 + CHUNK, :, z0:z0 + CHUNK]
        occupied = np.flatnonzero(sub.any(axis=(0, 2)))
        return int(occupied[-1]) + 1 if occupied.size else 0

    def _region(self, cx: int, cz: int, yh: int) -> np.ndarray:
        """Chunk data padded by one block, with the *real* neighbours on the
        sides, trimmed to the occupied height ``yh`` (everything above is
        air, so it never needs to be meshed)."""
        region = np.zeros((18, yh + 2, 18), dtype=np.uint16)
        x0, z0 = cx * CHUNK, cz * CHUNK
        b = self.blocks
        region[1:17, 1:1 + yh, 1:17] = b[x0:x0 + CHUNK, :yh, z0:z0 + CHUNK]
        region[0, 1:1 + yh, 1:17] = b[max(x0 - 1, 0), :yh, z0:z0 + CHUNK]
        region[17, 1:1 + yh, 1:17] = b[min(x0 + CHUNK, WX - 1), :yh, z0:z0 + CHUNK]
        region[1:17, 1:1 + yh, 0] = b[x0:x0 + CHUNK, :yh, max(z0 - 1, 0)]
        region[1:17, 1:1 + yh, 17] = b[x0:x0 + CHUNK, :yh,
                                       min(z0 + CHUNK, WZ - 1)]
        # Below the world counts as solid; above it is open sky.
        region[:, 0, :] = BEDROCK
        return region

    def mesh_arrays(self, cx: int, cz: int):
        """Thread-safe (read-only) mesher.  Returns (layers, faces, ymax);
        every layer is an (n*4, 6) float32 array of indexed quads."""
        ymax = self._column_ymax(cx, cz)
        yh = min(WY, ymax + 1)
        region = self._region(cx, cz, yh)
        src = region[1:17, 1:1 + yh, 1:17]
        ox, oz = cx * CHUNK, cz * CHUNK
        cube_parts, foliage_parts, water_parts, water_surface_parts, plant_parts, falling_leaf_parts, shore_parts = [], [], [], [], [], [], []
        face_total = 0

        cube_src = IS_CUBE[src] & ~IS_LEAF[src]
        foliage_src = IS_LEAF[src]
        water_src = IS_WATER[src]
        for di, (dx, dy, dz) in enumerate(DIRS):
            nb = region[1 + dx:17 + dx, 1 + dy:1 + yh + dy, 1 + dz:17 + dz]
            free = ~IS_OPAQUE[nb] & (nb != src)
            for src_mask, parts in ((cube_src, cube_parts), (foliage_src, foliage_parts),
                                    (water_src, water_parts)):
                mask = src_mask & free
                pos = np.argwhere(mask)
                n = pos.shape[0]
                if n == 0:
                    continue
                pw = pos.astype(np.float32)
                pw[:, 0] += ox
                pw[:, 2] += oz
                tiles = FACE_TILE[di][src[mask]]
                if src_mask is water_src and di == 3:
                    # Fade wave energy over the final two water blocks before land.
                    # The sea plane itself stays at the full one-block water height.
                    if self.shore_distance is None:
                        land = self.heights >= SEA_LEVEL
                        field = np.full(self.heights.shape, 99.0, dtype=np.float32)
                        for ddx in range(-4, 5):
                            for ddz in range(-4, 5):
                                x0, x1 = max(0, -ddx), min(WX, WX - ddx)
                                z0, z1 = max(0, -ddz), min(WZ, WZ - ddz)
                                if x0 >= x1 or z0 >= z1:
                                    continue
                                shifted = land[x0 + ddx:x1 + ddx, z0 + ddz:z1 + ddz]
                                target = field[x0:x1, z0:z1]
                                target[shifted] = np.minimum(target[shifted], math.hypot(ddx, ddz))
                        self.shore_distance = field
                    water_surface_parts.append(
                        _water_top_quads(pw, TILE_UVS[tiles], FACE_SHADE[di],
                                         segments=6, shore_distance=self.shore_distance))
                    face_total += n * 36
                else:
                    parts.append(_quads(pw, CORNERS[di], TILE_UVS[tiles], FACE_SHADE[di]))
                    face_total += n

        # Sparse individual leaflets detach from the canopy and drift down.
        leaf_pos = np.argwhere(foliage_src)
        if leaf_pos.size:
            code = (leaf_pos[:, 0] * 73856093 + leaf_pos[:, 1] * 19349663 + leaf_pos[:, 2] * 83492791) % 127
            chosen = leaf_pos[code == 0]
            if len(chosen):
                fp = chosen.astype(np.float32)
                fp[:, 0] += ox; fp[:, 2] += oz
                fuv = TILE_UVS[FACE_TILE[1][src[chosen[:, 0], chosen[:, 1], chosen[:, 2]]]]
                leaflet = np.array([[0.30, 0.48, 0.50], [0.50, 0.48, 0.32],
                                    [0.70, 0.48, 0.50], [0.50, 0.48, 0.68]], dtype=np.float32)
                fv = _quads(fp, leaflet, fuv, 0.95)
                phases = ((chosen[:, 0] * 0.173 + chosen[:, 1] * 0.317 + chosen[:, 2] * 0.119) % 1.0).astype(np.float32)
                fv[:, 6] = np.repeat(phases, 4)
                falling_leaf_parts.append(fv)

        plant_mask = IS_PLANT[src]
        plant_pos = np.argwhere(plant_mask)
        if plant_pos.shape[0] > 0:
            n = plant_pos.shape[0]
            pw = plant_pos.astype(np.float32)
            pw[:, 0] += ox
            pw[:, 2] += oz
            u = TILE_UVS[FACE_TILE[1][src[plant_mask]]]
            for quad in PLANT_QUADS:
                plant_parts.append(_quads(pw, quad, u, 0.92))
                face_total += n

        def cat(parts):
            if not parts:
                return np.zeros((0, 6), dtype=np.float32)
            return parts[0] if len(parts) == 1 else np.concatenate(parts, axis=0)

        return ({"cube": cat(cube_parts), "foliage": cat(foliage_parts),
                 "water": cat(water_parts), "water_surface": cat(water_surface_parts), "plant": cat(plant_parts),
                 "leaf_fall": cat(falling_leaf_parts), "shore": cat(shore_parts)},
                face_total, ymax)

    def upload_chunk(self, renderer, cx: int, cz: int, precomputed=None) -> None:
        old = self.meshes.pop((cx, cz), None)
        if old:
            renderer.release_chunk(old)
        arrays, _faces, ymax = precomputed or self.mesh_arrays(cx, cz)
        mesh = {}
        for layer, verts in arrays.items():
            if verts.shape[0] > 0:
                mesh[layer] = renderer.make_gpu_mesh(verts)
        self.meshes[(cx, cz)] = mesh
        self.chunk_ymax[(cx, cz)] = ymax
        self.mesh_version += 1
        self.dirty.discard((cx, cz))

    def flush_dirty(self, renderer) -> None:
        for cx, cz in list(self.dirty):
            self.upload_chunk(renderer, cx, cz)


# ----------------------------------------------------------------------------
# Player
# ----------------------------------------------------------------------------

class Player:
    def __init__(self, world: World) -> None:
        self.world = world
        self.half = 0.30
        self.height = 1.80
        self.eye_height = 1.62
        self.pos = np.array(world.spawn, dtype=np.float64)
        self.vel = np.zeros(3, dtype=np.float64)
        self.yaw = world.spawn_yaw
        self.pitch = world.spawn_pitch
        self.fly = False
        self.on_ground = False
        self.in_water = False
        self.underwater = False
        self.fov = FOV
        self.walk_phase = 0.0
        self.respawn()

    def respawn(self) -> None:
        self.pos[:] = self.world.spawn
        self.vel[:] = 0.0
        self.yaw = self.world.spawn_yaw
        self.pitch = self.world.spawn_pitch
        self.fly = False
        self.on_ground = False

    def eye_pos(self) -> np.ndarray:
        return self.pos + np.array([0.0, self.eye_height, 0.0])

    def forward(self) -> np.ndarray:
        cp = math.cos(self.pitch)
        return np.array([math.sin(self.yaw) * cp, math.sin(self.pitch),
                         -math.cos(self.yaw) * cp], dtype=np.float64)

    def flat_forward(self) -> np.ndarray:
        return np.array([math.sin(self.yaw), 0.0, -math.cos(self.yaw)],
                        dtype=np.float64)

    def right(self) -> np.ndarray:
        return np.array([math.cos(self.yaw), 0.0, math.sin(self.yaw)],
                        dtype=np.float64)

    def collides(self) -> bool:
        p = self.pos
        x0 = math.floor(p[0] - self.half + 1e-4)
        x1 = math.floor(p[0] + self.half - 1e-4)
        y0 = math.floor(p[1] + 1e-4)
        y1 = math.floor(p[1] + self.height - 1e-4)
        z0 = math.floor(p[2] - self.half + 1e-4)
        z1 = math.floor(p[2] + self.half - 1e-4)
        is_solid = self.world.is_solid
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                for z in range(z0, z1 + 1):
                    if is_solid(x, y, z):
                        return True
        return False

    def _move_axis(self, axis: int, amount: float) -> bool:
        if abs(amount) < 1e-9:
            return False
        start = float(self.pos[axis])
        self.pos[axis] = start + amount
        if not self.collides():
            return False
        lo, hi = 0.0, 1.0
        for _ in range(8):
            mid = (lo + hi) * 0.5
            self.pos[axis] = start + amount * mid
            if self.collides():
                hi = mid
            else:
                lo = mid
        self.pos[axis] = start + amount * lo
        return True

    def update(self, dt: float, forward: float, strafe: float, jump: bool,
               sprint: bool, descend: bool) -> None:
        dt = min(dt, 0.05)
        self.in_water = (self.world.is_water(math.floor(self.pos[0]),
                                             math.floor(self.pos[1] + 0.25),
                                             math.floor(self.pos[2])) or
                         self.world.is_water(math.floor(self.pos[0]),
                                             math.floor(self.pos[1] + 1.45),
                                             math.floor(self.pos[2])))
        eye_block = self.world.get(math.floor(self.pos[0]),
                                   math.floor(self.pos[1] + self.eye_height),
                                   math.floor(self.pos[2]))
        self.underwater = eye_block == WATER

        fwd = self.flat_forward()
        right = self.right()
        wish = fwd * forward + right * strafe
        wl = float(np.linalg.norm(wish))
        if wl > 1.0:
            wish /= wl

        was_ground = self.on_ground
        if self.fly:
            speed = 22.0 if sprint else 10.5
            target = wish * speed
            k = min(1.0, 12.0 * dt)
            self.vel[0] += (target[0] - self.vel[0]) * k
            self.vel[2] += (target[2] - self.vel[2]) * k
            vy = (1.0 if jump else 0.0) - (1.0 if descend else 0.0)
            self.vel[1] += (vy * speed - self.vel[1]) * k
        else:
            speed = 5.9 if sprint else 4.3
            if self.in_water:
                speed *= 0.55
            target = wish * speed
            accel = 34.0 if self.on_ground else 13.0
            if self.in_water:
                accel = 14.0
            k = min(1.0, accel * dt)
            self.vel[0] += (target[0] - self.vel[0]) * k
            self.vel[2] += (target[2] - self.vel[2]) * k

            if self.in_water:
                self.vel[1] -= 8.0 * dt
                self.vel[1] *= max(0.0, 1.0 - 2.5 * dt)
                if jump:
                    self.vel[1] = min(self.vel[1] + 20.0 * dt, 4.2)
            else:
                self.vel[1] -= 28.0 * dt
                if jump and was_ground:
                    self.vel[1] = 8.5
            self.vel[1] = max(self.vel[1], -55.0)

        self.on_ground = False
        d = self.vel * dt
        steps = max(1, int(math.ceil(max(abs(d[0]), abs(d[1]), abs(d[2])) / 0.35)))
        step = d / steps
        for _ in range(steps):
            if self._move_axis(0, float(step[0])):
                self.vel[0] = 0.0
            if self._move_axis(1, float(step[1])):
                if step[1] < 0:
                    self.on_ground = True
                self.vel[1] = 0.0
            if self._move_axis(2, float(step[2])):
                self.vel[2] = 0.0

        if max(abs(self.vel[0]), abs(self.vel[2])) > 0.4 and self.on_ground:
            self.walk_phase += dt * (12.0 if sprint else 9.0)
        else:
            self.walk_phase *= max(0.0, 1.0 - 6.0 * dt)

        target_fov = FOV + (7.0 if sprint and not self.fly else 0.0)
        if self.fly and (abs(forward) + abs(strafe)) > 0:
            target_fov += 3.0
        self.fov += (target_fov - self.fov) * min(1.0, 8.0 * dt)

        if self.pos[1] < -16.0:
            self.respawn()

    def intersects_block(self, x: int, y: int, z: int) -> bool:
        p = self.pos
        return (p[0] + self.half > x and p[0] - self.half < x + 1 and
                p[1] + self.height > y and p[1] < y + 1 and
                p[2] + self.half > z and p[2] - self.half < z + 1)


# ----------------------------------------------------------------------------
# Multiplayer (LAN, TCP + newline-delimited JSON)
# ----------------------------------------------------------------------------

def sanitize_name(name: str) -> str:
    clean = "".join(ch for ch in str(name) if ch.isprintable()).strip()
    return (clean or "Player")[:16]


def read_local_skin_b64() -> str:
    """Return this installation's skin.png as PNG base64 for LAN sharing."""
    for path in (ROOT / "skin.png", ASSET_DIR / "skin.png", Path.cwd() / "skin.png"):
        try:
            if path.is_file():
                with Image.open(path) as im:
                    im = im.convert("RGBA")
                    if im.size not in ((64, 64), (64, 32)):
                        continue
                    out = io.BytesIO()
                    im.save(out, format="PNG")
                    return base64.b64encode(out.getvalue()).decode("ascii")
        except Exception as exc:
            print(f"[skin] cannot share {path}: {exc}", file=sys.stderr)
    return ""


def split_address(address: str) -> tuple[str, int]:
    address = address.strip()
    if address.startswith("["):
        end = address.find("]")
        if end > 0:
            host = address[1:end]
            rest = address[end + 1:]
            if rest.startswith(":"):
                try:
                    return host, int(rest[1:])
                except ValueError:
                    return host, DEFAULT_PORT
            return host, DEFAULT_PORT
    if ":" in address:
        host, port = address.rsplit(":", 1)
        try:
            return host, int(port)
        except ValueError:
            return address, DEFAULT_PORT
    return address, DEFAULT_PORT


def local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


def _clean_block(msg: dict):
    try:
        x, y, z = int(msg["x"]), int(msg["y"]), int(msg["z"])
        b = int(msg["b"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (0 <= x < WX and 0 <= y < WY and 0 <= z < WZ):
        return None
    if not (0 <= b < N_BLOCKS):
        return None
    return {"x": x, "y": y, "z": z, "b": b}


def _clean_pos(msg: dict):
    try:
        x, y, z = float(msg["x"]), float(msg["y"]), float(msg["z"])
        yaw, pitch = float(msg.get("yaw", 0.0)), float(msg.get("pitch", 0.0))
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (x, y, z, yaw, pitch)):
        return None
    return {"x": x, "y": y, "z": z, "yaw": yaw, "pitch": pitch}


@dataclass
class ClientLink:
    conn: socket.socket
    addr: tuple
    reader: object
    name: str = ""
    send_lock: threading.Lock = None
    alive: bool = True

    def __post_init__(self):
        if self.send_lock is None:
            self.send_lock = threading.Lock()

    def send(self, obj: dict) -> bool:
        try:
            data = (json.dumps(obj, separators=(",", ":")) + "\n").encode()
            with self.send_lock:
                self.conn.sendall(data)
            return True
        except Exception:
            self.alive = False
            return False

    def close(self) -> None:
        self.alive = False
        try:
            self.conn.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            self.conn.close()
        except Exception:
            pass


class NetSession:
    """Host-authoritative LAN session.

    The host owns the world.  Clients generate the same deterministic world
    from the seed and then receive the host's block-edit journal, so joining
    mid-game works.  Block edits and player positions are relayed through the
    host; the protocol is newline-delimited JSON over TCP.
    """

    def __init__(self, name: str, is_host: bool) -> None:
        self.name = sanitize_name(name)
        self.is_host = is_host
        self.local_skin = read_local_skin_b64()
        self.seed: int | None = None
        self.host_name = "Host"
        self.connected = False
        self.error = ""
        self.inbox: queue.Queue = queue.Queue()
        self.clients: list[ClientLink] = []
        self.block_log: list[dict] = []
        self.lock = threading.RLock()
        self.server: socket.socket | None = None
        self.sock: socket.socket | None = None
        self.reader = None
        self._running = False
        self._thread: threading.Thread | None = None

    # -- lifecycle ----------------------------------------------------------

    def host(self, port: int, seed: int) -> int:
        self.seed = int(seed)
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", int(port)))
        srv.listen(8)
        self.server = srv
        self.connected = True
        self._running = True
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        return int(srv.getsockname()[1])

    def join(self, host: str, port: int) -> int:
        sock = socket.create_connection((host, int(port)), timeout=6.0)
        sock.settimeout(6.0)
        self.sock = sock
        self.reader = sock.makefile("r", encoding="utf-8", newline="\n")
        try:
            self._send_raw({"t": "hello", "v": NET_VERSION, "name": self.name,
                            "skin": self.local_skin})
            line = self.reader.readline()
            if not line:
                raise ConnectionError("server closed the connection")
            msg = json.loads(line)
            if msg.get("t") != "hello":
                raise ConnectionError("unexpected handshake")
            if int(msg.get("v", 0)) != NET_VERSION:
                raise ConnectionError("different PyCraft version")
            self.seed = int(msg["seed"])
            self.host_name = sanitize_name(msg.get("name", "Host"))
            self.host_skin = str(msg.get("skin", ""))[:140000]
        except Exception:
            try:
                sock.close()
            except Exception:
                pass
            self.sock = None
            raise
        sock.settimeout(None)
        self.connected = True
        self._running = True
        self._thread = threading.Thread(target=self._client_loop, daemon=True)
        self._thread.start()
        return self.seed

    def close(self) -> None:
        self._running = False
        self.connected = False
        with self.lock:
            clients = list(self.clients)
            self.clients.clear()
        for link in clients:
            link.close()
        if self.server is not None:
            try:
                self.server.close()
            except Exception:
                pass
            self.server = None
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    # -- sending ------------------------------------------------------------

    def _send_raw(self, obj: dict) -> bool:
        try:
            data = (json.dumps(obj, separators=(",", ":")) + "\n").encode()
            if self.sock is None:
                return False
            self.sock.sendall(data)
            return True
        except Exception:
            self.connected = False
            return False

    def send(self, obj: dict) -> bool:
        if self.is_host:
            return self.broadcast(obj)
        return self._send_raw(obj)

    def broadcast(self, obj: dict, exclude: ClientLink | None = None) -> None:
        if not self.is_host:
            return
        with self.lock:
            clients = list(self.clients)
        for link in clients:
            if link is not exclude and link.alive:
                if not link.send(obj):
                    link.close()

    def send_block(self, x: int, y: int, z: int, block: int) -> None:
        msg = {"t": "block", "x": int(x), "y": int(y), "z": int(z),
               "b": int(block)}
        if self.is_host:
            self.record_block(x, y, z, block)
            self.broadcast(msg)
        else:
            self._send_raw(msg)

    def record_block(self, x: int, y: int, z: int, block: int) -> None:
        if not self.is_host:
            return
        self.block_log.append({"x": int(x), "y": int(y), "z": int(z),
                               "b": int(block)})
        if len(self.block_log) > 50000:
            del self.block_log[:10000]

    def send_pos(self, pos, yaw: float, pitch: float) -> None:
        self.send({"t": "pos", "name": self.name,
                   "x": round(float(pos[0]), 3),
                   "y": round(float(pos[1]), 3),
                   "z": round(float(pos[2]), 3),
                   "yaw": round(float(yaw), 4),
                   "pitch": round(float(pitch), 4)})

    def send_chat(self, text: str) -> None:
        text = str(text).replace("\n", " ").strip()[:MAX_CHAT]
        if not text:
            return
        if self.is_host:
            self.send({"t": "chat", "name": self.name, "text": text})
        else:
            self._send_raw({"t": "chat", "text": text})

    # -- receiving ----------------------------------------------------------

    def poll(self) -> list[dict]:
        out = []
        while True:
            try:
                out.append(self.inbox.get_nowait())
            except queue.Empty:
                break
        return out

    def _accept_loop(self) -> None:
        assert self.server is not None
        while self._running:
            try:
                conn, addr = self.server.accept()
            except OSError:
                break
            try:
                reader = conn.makefile("r", encoding="utf-8", newline="\n")
                link = ClientLink(conn, addr, reader)
                threading.Thread(target=self._client_loop, args=(link,),
                                 daemon=True).start()
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass

    def _client_loop(self, link: ClientLink | None = None) -> None:
        if link is not None:
            self._host_client_loop(link)
            return
        assert self.reader is not None
        try:
            for line in self.reader:
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line)
                except Exception:
                    continue
                if isinstance(msg, dict):
                    self.inbox.put(msg)
        except Exception:
            pass
        finally:
            self.connected = False
            self.inbox.put({"t": "disconnected"})

    def _host_client_loop(self, link: ClientLink) -> None:
        try:
            link.send({"t": "hello", "v": NET_VERSION, "name": self.name,
                       "seed": self.seed, "host": True,
                       "skin": self.local_skin})
            line = link.reader.readline()
            if not line:
                return
            hello = json.loads(line)
            if hello.get("t") != "hello":
                return
            if int(hello.get("v", 0)) != NET_VERSION:
                return
            link.name = sanitize_name(hello.get("name", "Player"))
            with self.lock:
                self.clients.append(link)
                peers = [self.name] + [c.name for c in self.clients
                                       if c is not link and c.name]
            link.send({"t": "peers", "peers": peers})
            # Send every already-connected player's own skin to the newcomer.
            with self.lock:
                existing = [{"name": self.name, "skin": self.local_skin}]
                existing.extend({"name": c.name, "skin": getattr(c, "skin", "")}
                                for c in self.clients if c is not link and c.name)
            link.send({"t": "skin_list", "players": existing})
            link.skin = str(hello.get("skin", ""))[:140000]
            self.inbox.put({"t": "skin", "name": link.name, "skin": link.skin})
            self.broadcast({"t": "skin", "name": link.name, "skin": link.skin}, exclude=link)
            if self.block_log:
                link.send({"t": "blocks", "edits": self.block_log[-50000:]})
            self.broadcast({"t": "join", "name": link.name}, exclude=link)
            self.inbox.put({"t": "join", "name": link.name})

            for line in link.reader:
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line)
                except Exception:
                    continue
                if not isinstance(msg, dict):
                    continue
                kind = msg.get("t")
                if kind == "block":
                    clean = _clean_block(msg)
                    if clean:
                        self.inbox.put({"t": "remote_block", "src": link,
                                        "name": link.name, **clean})
                elif kind == "pos":
                    clean = _clean_pos(msg)
                    if clean:
                        clean["name"] = link.name
                        self.broadcast({"t": "pos", **clean}, exclude=link)
                        self.inbox.put({"t": "pos", **clean})
                elif kind == "skin":
                    skin = str(msg.get("skin", ""))[:140000]
                    ev = {"t": "skin", "name": link.name, "skin": skin}
                    self.broadcast(ev, exclude=link)
                    self.inbox.put(ev)
                elif kind == "chat":
                    text = str(msg.get("text", "")).replace("\n", " ")[:MAX_CHAT]
                    if text.strip():
                        ev = {"t": "chat", "name": link.name,
                              "text": text.strip()}
                        self.broadcast(ev, exclude=link)
                        self.inbox.put(ev)
        except Exception:
            pass
        finally:
            with self.lock:
                if link in self.clients:
                    self.clients.remove(link)
            link.close()
            if link.name:
                self.broadcast({"t": "leave", "name": link.name})
                self.inbox.put({"t": "leave", "name": link.name})


@dataclass
class RemotePlayer:
    name: str
    pos: np.ndarray
    target: np.ndarray
    yaw: float = 0.0
    pitch: float = 0.0
    has_pos: bool = False
    color: tuple = (0.85, 0.45, 0.35, 1.0)
    skin_tex: object | None = None


def remote_color(name: str):
    palette = [
        (0.92, 0.36, 0.30, 1.0), (0.30, 0.62, 0.95, 1.0),
        (0.36, 0.82, 0.45, 1.0), (0.95, 0.78, 0.30, 1.0),
        (0.78, 0.42, 0.90, 1.0), (0.30, 0.85, 0.82, 1.0),
        (0.95, 0.55, 0.30, 1.0), (0.80, 0.80, 0.88, 1.0),
    ]
    h = 0
    for ch in name:
        h = (h * 131 + ord(ch)) & 0x7FFFFFFF
    return palette[h % len(palette)]


def build_world(renderer, seed: int) -> World:
    """Generate a world and upload all chunk meshes with a loading screen."""
    renderer.draw_loading(0.02, "GENERATING TERRAIN")
    world = World(seed)
    world.generate()
    chunks = [(cx, cz) for cx in range(WX // CHUNK)
              for cz in range(WZ // CHUNK)]
    total = len(chunks)
    sx, _, sz = world.spawn
    chunks.sort(key=lambda c: (c[0] * CHUNK + 8 - sx) ** 2 +
                              (c[1] * CHUNK + 8 - sz) ** 2)
    last_ui = 0.0
    with ThreadPoolExecutor(max_workers=_worker_count()) as ex:
        futures = [ex.submit(world.mesh_arrays, cx, cz) for cx, cz in chunks]
        for i, ((cx, cz), fut) in enumerate(zip(chunks, futures)):
            world.upload_chunk(renderer, cx, cz, fut.result())
            futures[i] = None
            now = time.perf_counter()
            if now - last_ui > 0.12 or i == total - 1:
                progress = 0.10 + 0.90 * (i + 1) / total
                renderer.draw_loading(progress,
                                      f"BUILDING CHUNKS  {i + 1}/{total}")
                last_ui = now
    renderer.draw_loading(1.0, "READY")
    return world


# ----------------------------------------------------------------------------
# Game logic / input
# ----------------------------------------------------------------------------

class Game:
    def __init__(self, renderer, world: World, player: Player,
                 scene: str = "menu", net: "NetSession | None" = None,
                 name: str | None = None) -> None:
        self.renderer = renderer
        self.world = world
        self.player = player
        self.state = "menu"
        self.hotbar = list(HOTBAR_DEFAULT)
        self.slot = 0
        self.running = True
        self.captured = False
        self.debug = False
        self.third_person = False
        self.break_cool = 0.0
        self.place_cool = 0.0
        self.target = None
        self.last_fps = 0.0
        self.fps_timer = 0.0
        self.fps_frames = 0
        self.toast = ""
        self.toast_timer = 0.0
        self.auto_screenshot = None
        self.auto_record = None
        self.record_seconds = 10
        self.auto_scene = scene
        self.frame_count = 0
        self.last_time = time.perf_counter()

        # Creative inventory / items.
        self.inv_tab = 0                 # 0 = blocks, 1 = items
        self.inv_page = 0

        # Multiplayer.
        self.name = sanitize_name(name or getpass.getuser())
        self.net: NetSession | None = net
        self.remote_players: dict[str, RemotePlayer] = {}
        self.remote_labels: list[tuple[str, int, int]] = []
        self.net_pos_timer = 0.0
        self.mp_address = "127.0.0.1:25565"
        self.mp_focus = False
        self.mp_name_focus = False
        self.mp_status = ""
        self.mp_busy = False

        # Singleplayer world management and autosave.
        self.active_world_name = ""
        self.active_world_file: Path | None = None
        self.world_name_input = "My World"
        self.world_seed_input = ""
        self.world_form_focus = "name"
        self.world_list_scroll = 0
        self.autosave_elapsed = 0.0
        self.autosave_interval = 5.0
        self.world_status = ""
        self.delete_world_path: Path | None = None
        self.delete_world_name = ""
        self.selected_host_world: Path | None = None
        self.create_for_host = False
        self.create_return_state = "world_select"

        # Chat.
        self.chat_open = False
        self.chat_text = ""
        self.chat_messages: list[list] = []   # [name, text, ttl]

        if self.net is not None:
            self._register_net_peers()

    # -- state --------------------------------------------------------------

    def set_captured(self, on: bool) -> None:
        if on == self.captured:
            return
        self.captured = on
        try:
            pygame.mouse.set_relative_mode(on)
        except Exception:
            pass
        pygame.event.set_grab(on)
        pygame.mouse.set_visible(not on)
        try:
            pygame.mouse.get_rel()
        except Exception:
            pass
        if not on:
            pygame.mouse.set_pos((self.renderer.width // 2,
                                  self.renderer.height // 2))

    # -- multiplayer / chat -------------------------------------------------

    def _ensure_remote(self, name: str) -> RemotePlayer | None:
        if not name or name == self.name:
            return None
        rp = self.remote_players.get(name)
        if rp is None:
            rp = RemotePlayer(name, np.zeros(3), np.zeros(3),
                              color=remote_color(name))
            self.remote_players[name] = rp
        return rp

    def _register_net_peers(self) -> None:
        if not self.net:
            return
        if not self.net.is_host and self.net.host_name:
            self._ensure_remote(self.net.host_name)

    def add_chat(self, name: str, text: str) -> None:
        self.chat_messages.append([str(name), str(text), 12.0])
        if len(self.chat_messages) > 100:
            del self.chat_messages[:20]

    def open_chat(self) -> None:
        if self.state == "playing" and not self.chat_open:
            self.chat_open = True
            self.chat_text = ""
            self.set_captured(False)

    def close_chat(self) -> None:
        if self.chat_open:
            self.chat_open = False
            self.chat_text = ""
            self.set_captured(True)

    def send_chat(self) -> None:
        text = self.chat_text.replace("\n", " ").strip()[:MAX_CHAT]
        if text:
            if self.net and self.net.connected:
                self.net.send_chat(text)
            self.add_chat(self.name, text)
        self.chat_open = False
        self.chat_text = ""
        self.set_captured(True)

    def host_game(self) -> None:
        if self.selected_host_world is None:
            self.mp_status = "Select a saved world before hosting"
            return
        if not self.open_saved_world(self.selected_host_world):
            self.mp_status = self.world_status or "Could not open selected world"
            return
        if self.net:
            self.net.close()
            self.net = None
        # The host keeps the selected save attached so edits autosave to it.
        net = NetSession(self.name, True)
        try:
            port = net.host(DEFAULT_PORT, self.world.seed)
        except OSError as exc:
            net.close()
            self.mp_status = f"Could not host: {exc}"
            return
        self.net = net
        self.mp_status = f"Hosting on {local_ip()}:{port}"
        self.add_chat("System", f"Hosting LAN world on {local_ip()}:{port}")
        self.start_play()
        self.toast = f"Hosting on {local_ip()}:{port}  -  T to chat"
        self.toast_timer = 7.0

    def join_game(self) -> None:
        address = self.mp_address.strip() or "127.0.0.1:25565"
        host, port = split_address(address)
        if not host:
            self.mp_status = "Enter a server address"
            return
        self.mp_status = "Connecting..."
        self.renderer.draw_loading(0.05, f"CONNECTING TO {host}:{port}")
        net = NetSession(self.name, False)
        try:
            seed = net.join(host, port)
        except Exception as exc:
            net.close()
            self.mp_status = f"Connection failed: {exc}"
            return
        self.mp_status = ""
        self.renderer.draw_loading(0.10, "CONNECTED - JOINING WORLD")
        self.load_world(seed, net)
        if net.local_skin:
            net.send({"t": "skin", "name": net.name, "skin": net.local_skin})
        self.add_chat("System", f"Joined {host}:{port}  -  T to chat")
        self.toast = "Joined multiplayer world  -  T to chat"
        self.toast_timer = 6.0

    def load_world(self, seed: int, net: "NetSession | None" = None) -> None:
        if self.net:
            self.net.close()
        self.active_world_name = ""
        self.active_world_file = None
        self.renderer.release_world(self.world)
        self.world = build_world(self.renderer, seed)
        self.player = Player(self.world)
        self.player.respawn()
        self.remote_players.clear()
        self.net = net
        self.state = "playing"
        self.inv_page = 0
        self.set_captured(True)
        self._register_net_peers()

    def _handle_net_events(self) -> None:
        if not self.net:
            return
        for ev in self.net.poll():
            kind = ev.get("t")
            if kind == "pos":
                name = ev.get("name")
                rp = self._ensure_remote(name)
                if rp is not None:
                    rp.target[:] = (float(ev["x"]), float(ev["y"]),
                                    float(ev["z"]))
                    if not rp.has_pos:
                        rp.pos[:] = rp.target
                    rp.yaw = float(ev.get("yaw", rp.yaw))
                    rp.pitch = float(ev.get("pitch", rp.pitch))
                    rp.has_pos = True
            elif kind == "remote_block":
                clean = _clean_block(ev)
                if clean:
                    self.world.set_block(clean["x"], clean["y"], clean["z"],
                                         clean["b"])
                    if self.net and self.net.is_host:
                        self.net.record_block(clean["x"], clean["y"],
                                              clean["z"], clean["b"])
                        self.net.broadcast(
                            {"t": "block", "x": clean["x"], "y": clean["y"],
                             "z": clean["z"], "b": clean["b"]},
                            exclude=ev.get("src"))
            elif kind == "block":
                clean = _clean_block(ev)
                if clean:
                    self.world.set_block(clean["x"], clean["y"], clean["z"],
                                         clean["b"])
            elif kind == "blocks":
                for edit in ev.get("edits", []):
                    clean = _clean_block(edit)
                    if clean:
                        self.world.set_block(clean["x"], clean["y"],
                                             clean["z"], clean["b"])
            elif kind == "join":
                name = sanitize_name(ev.get("name", "Player"))
                if self._ensure_remote(name) is not None:
                    self.add_chat("System", f"{name} joined the game")
            elif kind == "leave":
                name = sanitize_name(ev.get("name", "Player"))
                if self.remote_players.pop(name, None) is not None:
                    self.add_chat("System", f"{name} left the game")
            elif kind == "peers":
                for name in ev.get("peers", []):
                    self._ensure_remote(sanitize_name(name))
            elif kind in ("skin", "skin_list"):
                entries = ([ev] if kind == "skin" else ev.get("players", []))
                for entry in entries:
                    name = sanitize_name(entry.get("name", "Player"))
                    rp = self._ensure_remote(name)
                    encoded = str(entry.get("skin", ""))[:140000]
                    if rp is None or not encoded:
                        continue
                    try:
                        raw = base64.b64decode(encoded, validate=True)
                        if len(raw) > 100000:
                            continue
                        with Image.open(io.BytesIO(raw)) as im:
                            im = im.convert("RGBA")
                            if im.size not in ((64, 64), (64, 32)):
                                continue
                            if im.size == (64, 32):
                                padded = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
                                padded.paste(im, (0, 0))
                                im = padded
                            new_tex = self.renderer._upload_texture(im, repeat=False, linear=False, mipmaps=False)
                        if rp.skin_tex is not None:
                            rp.skin_tex.release()
                        rp.skin_tex = new_tex
                    except Exception as exc:
                        print(f"[skin] invalid network skin for {name}: {exc}", file=sys.stderr)
            elif kind == "chat":
                name = sanitize_name(ev.get("name", "Player"))
                text = str(ev.get("text", ""))[:MAX_CHAT]
                if text:
                    self.add_chat(name, text)
            elif kind == "disconnected":
                if self.net:
                    self.net.close()
                    self.net = None
                self.remote_players.clear()
                self.add_chat("System", "Connection lost - now singleplayer")
                self.toast = "Disconnected from server"
                self.toast_timer = 4.0

    def _send_net_pos(self, dt: float) -> None:
        if not self.net or not self.net.connected:
            return
        self.net_pos_timer -= dt
        if self.net_pos_timer <= 0.0:
            self.net_pos_timer = 0.10
            self.net.send_pos(self.player.pos, self.player.yaw,
                              self.player.pitch)

    @staticmethod
    def _world_slug(name: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip()).strip("_-")
        return (slug[:48] or "World")

    def list_saved_worlds(self) -> list[dict]:
        WORLD_SAVE_DIR.mkdir(parents=True, exist_ok=True)
        worlds = []
        for path in WORLD_SAVE_DIR.glob("*.json"):
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("format") != "pycraft-world":
                    continue
                worlds.append({"path": path, "name": str(data.get("name") or path.stem),
                               "seed": int(data.get("seed", 0)),
                               "updated": str(data.get("updated", ""))})
            except Exception as exc:
                print(f"[worlds] skipping invalid save {path.name}: {exc}", file=sys.stderr)
        worlds.sort(key=lambda item: item["updated"], reverse=True)
        return worlds

    def delete_saved_world(self, path: Path) -> bool:
        """Delete a world only after the user confirms the action."""
        try:
            resolved = path.resolve()
            if resolved.parent != WORLD_SAVE_DIR.resolve() or resolved.suffix.lower() != ".json":
                raise ValueError("Invalid world path")
            if self.active_world_file and self.active_world_file.resolve() == resolved:
                self.save_world(silent=True)
                self.active_world_file = None
                self.active_world_name = ""
            resolved.unlink(missing_ok=True)
            resolved.with_suffix(".json.tmp").unlink(missing_ok=True)
            self.world_status = "World deleted"
            return True
        except Exception as exc:
            self.world_status = f"Could not delete world: {exc}"
            return False

    def save_world(self, silent: bool = False) -> bool:
        """Autosave the active world into its own JSON file."""
        if self.net is not None and not self.net.is_host:
            return False
        if self.active_world_file is None:
            return False
        try:
            WORLD_SAVE_DIR.mkdir(parents=True, exist_ok=True)
            payload = {
                "format": "pycraft-world", "version": 2,
                "name": self.active_world_name,
                "seed": int(self.world.seed),
                "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
                "player": {
                    "position": [round(float(v), 5) for v in self.player.pos],
                    "yaw": float(self.player.yaw), "pitch": float(self.player.pitch),
                    "fly": bool(self.player.fly),
                },
                "blocks": [[x, y, z, int(block)]
                           for (x, y, z), block in sorted(self.world.edits.items())],
            }
            temp_path = self.active_world_file.with_suffix(".json.tmp")
            with temp_path.open("w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
            temp_path.replace(self.active_world_file)
            self.autosave_elapsed = 0.0
            if not silent:
                self.toast = f"{self.active_world_name} saved"
                self.toast_timer = 2.5
            return True
        except Exception as exc:
            if not silent:
                self.toast = f"Autosave failed: {exc}"
                self.toast_timer = 5.0
            print(f"[worlds] save failed: {exc}", file=sys.stderr)
            return False

    def create_world(self) -> None:
        name = self.world_name_input.strip()[:48] or "My World"
        seed_text = self.world_seed_input.strip()
        try:
            seed = int(seed_text) if seed_text else int.from_bytes(os.urandom(4), "big")
            if not -(2**63) <= seed < 2**63:
                raise ValueError("Seed must be a 64-bit integer")
        except ValueError:
            self.world_status = "Seed must be a valid 64-bit integer"
            return
        WORLD_SAVE_DIR.mkdir(parents=True, exist_ok=True)
        base = self._world_slug(name)
        path = WORLD_SAVE_DIR / f"{base}.json"
        suffix = 2
        while path.exists():
            path = WORLD_SAVE_DIR / f"{base}_{suffix}.json"
            suffix += 1
        self.renderer.draw_loading(0.02, "CREATING WORLD")
        if self.net:
            self.net.close()
            self.net = None
        self.renderer.release_world(self.world)
        self.world = build_world(self.renderer, seed)
        self.player = Player(self.world)
        self.player.respawn()
        self.remote_players.clear()
        self.active_world_name = name
        self.active_world_file = path
        self.autosave_elapsed = 0.0
        self.state = "playing"
        self.set_captured(True)
        self.save_world(silent=True)
        self.toast = f"Created {name}"
        self.toast_timer = 3.0
        if self.create_for_host:
            self.create_for_host = False
            self.selected_host_world = path
            self.host_game()

    def open_saved_world(self, path: Path) -> bool:
        try:
            with path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            if payload.get("format") != "pycraft-world" or int(payload.get("version", 0)) not in (1, 2):
                raise ValueError("Unsupported world save format")
            seed = int(payload["seed"])
            edits = payload.get("blocks", [])
            if not isinstance(edits, list) or len(edits) > WX * WY * WZ:
                raise ValueError("Invalid block edit list")
            player_data = payload.get("player", {})
            pos = player_data.get("position", [])
            if len(pos) != 3:
                raise ValueError("Invalid player position")
            position = [float(v) for v in pos]
            if not all(math.isfinite(v) for v in position):
                raise ValueError("Invalid player position")
            if self.net:
                self.net.close()
                self.net = None
            self.remote_players.clear()
            self.renderer.draw_loading(0.02, "LOADING WORLD")
            self.renderer.release_world(self.world)
            self.world = build_world(self.renderer, seed)
            for item in edits:
                if not isinstance(item, list) or len(item) != 4:
                    continue
                x, y, z, block = (int(v) for v in item)
                if 0 <= x < WX and 0 <= y < WY and 0 <= z < WZ and 0 <= block < len(BLOCKS):
                    self.world.set_block(x, y, z, block)
            self.world.flush_dirty(self.renderer)
            self.player = Player(self.world)
            self.player.pos[:] = position
            self.player.yaw = float(player_data.get("yaw", self.world.spawn_yaw))
            self.player.pitch = max(math.radians(-89), min(math.radians(89),
                float(player_data.get("pitch", self.world.spawn_pitch))))
            self.player.fly = bool(player_data.get("fly", False))
            if self.player.collides():
                self.player.respawn()
            self.active_world_name = str(payload.get("name") or path.stem)
            self.active_world_file = path
            self.autosave_elapsed = 0.0
            self.state = "playing"
            self.set_captured(True)
            self.toast = f"Loaded {self.active_world_name}"
            self.toast_timer = 3.0
            return True
        except Exception as exc:
            self.world_status = f"Could not load world: {exc}"
            self.state = "world_select"
            return False

    def start_play(self) -> None:
        self.state = "playing"
        self.set_captured(True)
        self.toast = ("WASD move  -  LMB break  -  RMB place  -  E inventory"
                      "  -  T chat")
        self.toast_timer = 6.0

    def pause(self) -> None:
        if self.state == "playing":
            self.chat_open = False
            self.state = "paused"
            self.set_captured(False)

    def resume(self) -> None:
        self.state = "playing"
        self.set_captured(True)

    def to_title(self) -> None:
        self.save_world(silent=True)
        self.state = "menu"
        self.chat_open = False
        self.set_captured(False)
        if self.net:
            self.net.close()
            self.net = None
        self.remote_players.clear()

    def open_inventory(self) -> None:
        if self.state == "playing":
            self.state = "inventory"
            self.set_captured(False)

    def close_inventory(self) -> None:
        if self.state == "inventory":
            self.resume()

    # -- events -------------------------------------------------------------

    def handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.save_world(silent=True)
                self.running = False
            elif event.type == pygame.WINDOWFOCUSLOST and self.state == "playing":
                self.pause()
            elif event.type == pygame.KEYDOWN:
                self._key_down(event)
            elif event.type == pygame.MOUSEBUTTONDOWN:
                self._mouse_down(event)
            elif event.type == pygame.MOUSEWHEEL:
                if self.state == "playing" and not self.chat_open:
                    self.slot = (self.slot - event.y) % len(self.hotbar)
                elif self.state == "inventory":
                    pages = inventory_page_count(self.inv_tab)
                    self.inv_page = max(0, min(pages - 1,
                                               self.inv_page - event.y))
            elif event.type == pygame.MOUSEMOTION and self.captured:
                dx, dy = event.rel
                self.player.yaw += dx * 0.0022
                self.player.pitch -= dy * 0.0022
                self.player.pitch = max(math.radians(-89.0),
                                        min(math.radians(89.0), self.player.pitch))

    def _key_down(self, event) -> None:
        k = event.key

        # Chat input captures every key while it is open.
        if self.chat_open:
            if k == pygame.K_ESCAPE:
                self.close_chat()
            elif k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.send_chat()
            elif k == pygame.K_BACKSPACE:
                self.chat_text = self.chat_text[:-1]
            elif len(self.chat_text) < MAX_CHAT:
                ch = getattr(event, "unicode", "")
                if ch and ch.isprintable():
                    self.chat_text += ch
            return

        if k == pygame.K_ESCAPE:
            if self.state == "playing":
                self.pause()
            elif self.state == "paused":
                self.resume()
            elif self.state == "inventory":
                self.close_inventory()
            elif self.state == "multiplayer":
                self.mp_focus = False
                self.state = "menu"
            elif self.state == "host_world_select":
                self.state = "multiplayer"
            elif self.state == "delete_world_confirm":
                self.delete_world_path = None
                self.state = "world_select"
            elif self.state == "world_select":
                self.state = "menu"
            elif self.state == "create_world":
                self.create_for_host = False
                self.state = self.create_return_state
            return

        if self.state == "menu":
            if k == pygame.K_m:
                self.state = "multiplayer"
                self.mp_status = ""
            return

        if self.state == "create_world":
            if k == pygame.K_TAB:
                self.world_form_focus = "seed" if self.world_form_focus == "name" else "name"
            elif k == pygame.K_BACKSPACE:
                if self.world_form_focus == "name":
                    self.world_name_input = self.world_name_input[:-1]
                else:
                    self.world_seed_input = self.world_seed_input[:-1]
            elif k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.create_world()
            else:
                ch = getattr(event, "unicode", "")
                if ch and ch.isprintable():
                    if self.world_form_focus == "name" and len(self.world_name_input) < 48:
                        self.world_name_input += ch
                    elif self.world_form_focus == "seed" and len(self.world_seed_input) < 20 and (ch.isdigit() or (ch == "-" and not self.world_seed_input)):
                        self.world_seed_input += ch
            return

        if self.state == "world_select":
            if k in (pygame.K_RETURN, pygame.K_n):
                self.world_name_input = "My World"
                self.world_seed_input = ""
                self.world_status = ""
                self.state = "create_world"
            return

        if self.state == "multiplayer":
            if self.mp_name_focus:
                if k == pygame.K_BACKSPACE:
                    self.name = self.name[:-1] or "Player"
                elif k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    self.mp_name_focus = False
                elif len(self.name) < 16:
                    ch = getattr(event, "unicode", "")
                    if ch and ch.isprintable() and ch not in " ":
                        self.name += ch
            elif self.mp_focus:
                if k == pygame.K_BACKSPACE:
                    self.mp_address = self.mp_address[:-1]
                elif k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    self.mp_focus = False
                    self.join_game()
                elif len(self.mp_address) < 64:
                    ch = getattr(event, "unicode", "")
                    if ch and ch.isprintable():
                        self.mp_address += ch
            elif k == pygame.K_RETURN:
                self.join_game()
            elif k == pygame.K_TAB:
                self.mp_focus = True
            return

        if self.state == "paused":
            if k in (pygame.K_RETURN,):
                self.resume()
            return

        if self.state == "inventory":
            if k in (pygame.K_e, pygame.K_RETURN):
                self.close_inventory()
            elif pygame.K_1 <= k <= pygame.K_9:
                self.slot = k - pygame.K_1
            elif k == pygame.K_TAB:
                self.inv_tab = 1 - self.inv_tab
                self.inv_page = 0
            elif k == pygame.K_LEFT:
                self.inv_page = max(0, self.inv_page - 1)
            elif k == pygame.K_RIGHT:
                self.inv_page = min(inventory_page_count(self.inv_tab) - 1,
                                    self.inv_page + 1)
            return

        if self.state != "playing":
            return
        if k == pygame.K_e:
            self.open_inventory()
        elif k == pygame.K_t:
            self.open_chat()
        elif k == pygame.K_f:
            self.player.fly = not self.player.fly
            self.toast = "Fly mode " + ("ON" if self.player.fly else "OFF")
            self.toast_timer = 2.0
        elif k == pygame.K_r:
            self.player.respawn()
        elif k == pygame.K_F3:
            self.debug = not self.debug
        elif k == pygame.K_F5:
            self.third_person = not self.third_person
            self.toast = "Third person " + ("ON" if self.third_person else "OFF")
            self.toast_timer = 2.0
        elif pygame.K_1 <= k <= pygame.K_9:
            self.slot = k - pygame.K_1

    def _mouse_down(self, event) -> None:
        pos = pygame.mouse.get_pos()
        if self.state == "menu":
            hit = self.renderer.hit_hotspot(pos)
            if hit == "play":
                self.state = "world_select"
                self.world_status = ""
            elif hit == "multiplayer":
                self.state = "multiplayer"
                self.mp_focus = False
                self.mp_status = ""
            elif hit == "quit":
                self.running = False
            return
        if self.state == "world_select":
            hit = self.renderer.hit_hotspot(pos)
            if hit == "create_world":
                self.world_name_input = "My World"
                self.world_seed_input = ""
                self.world_status = ""
                self.world_form_focus = "name"
                self.state = "create_world"
            elif hit and hit.startswith("world:"):
                index = int(hit.split(":", 1)[1])
                worlds = self.list_saved_worlds()
                if 0 <= index < len(worlds):
                    self.open_saved_world(worlds[index]["path"])
            elif hit and hit.startswith("world_delete:"):
                index = int(hit.split(":", 1)[1])
                worlds = self.list_saved_worlds()
                if 0 <= index < len(worlds):
                    self.delete_world_path = worlds[index]["path"]
                    self.delete_world_name = worlds[index]["name"]
                    self.state = "delete_world_confirm"
            elif hit == "world_back":
                self.state = "menu"
            return
        if self.state == "delete_world_confirm":
            hit = self.renderer.hit_hotspot(pos)
            if hit == "delete_confirm_yes" and self.delete_world_path is not None:
                self.delete_saved_world(self.delete_world_path)
                self.delete_world_path = None
                self.state = "world_select"
            elif hit == "delete_confirm_no":
                self.delete_world_path = None
                self.state = "world_select"
            return
        if self.state == "host_world_select":
            hit = self.renderer.hit_hotspot(pos)
            if hit and hit.startswith("host_world:"):
                index = int(hit.split(":", 1)[1])
                worlds = self.list_saved_worlds()
                if 0 <= index < len(worlds):
                    self.selected_host_world = worlds[index]["path"]
                    self.mp_status = "Selected world: " + worlds[index]["name"]
                    self.state = "multiplayer"
            elif hit == "host_world_back":
                self.state = "multiplayer"
            elif hit == "host_world_create":
                self.create_for_host = True
                self.create_return_state = "host_world_select"
                self.world_name_input = "My World"
                self.world_seed_input = ""
                self.world_status = ""
                self.world_form_focus = "name"
                self.state = "create_world"
            return
        if self.state == "create_world":
            hit = self.renderer.hit_hotspot(pos)
            if hit == "world_name":
                self.world_form_focus = "name"
            elif hit == "world_seed":
                self.world_form_focus = "seed"
            elif hit == "world_create":
                self.create_world()
            elif hit == "world_cancel":
                self.create_for_host = False
                self.state = self.create_return_state
            return
        if self.state == "multiplayer":
            hit = self.renderer.hit_hotspot(pos)
            if hit == "host":
                self.state = "host_world_select"
                self.mp_status = "Choose which saved world to host"
            elif hit == "join":
                self.join_game()
            elif hit == "back":
                self.mp_focus = False
                self.state = "menu"
            elif hit == "address":
                self.mp_focus = True
                self.mp_name_focus = False
            elif hit == "name":
                self.mp_name_focus = True
                self.mp_focus = False
            else:
                self.mp_focus = False
                self.mp_name_focus = False
            return
        if self.state == "paused":
            hit = self.renderer.hit_hotspot(pos)
            if hit == "resume":
                self.resume()
            elif hit == "title":
                self.to_title()
            elif hit == "quit":
                self.running = False
            return
        if self.state == "inventory":
            if event.button == 1:
                hit = self.renderer.hit_hotspot(pos)
                if hit == "inv_blocks":
                    self.inv_tab = 0
                    self.inv_page = 0
                    return
                if hit == "inv_items":
                    self.inv_tab = 1
                    self.inv_page = 0
                    return
                if hit == "inv_prev":
                    self.inv_page = max(0, self.inv_page - 1)
                    return
                if hit == "inv_next":
                    self.inv_page = min(inventory_page_count(self.inv_tab) - 1,
                                        self.inv_page + 1)
                    return
                picked = self.renderer.inventory_pick(pos)
                if picked is not None:
                    self.hotbar[self.slot] = picked
                    self.close_inventory()
            return
        if self.state == "playing" and self.captured:
            if event.button == 1 and self.break_cool <= 0.0:
                self.break_block()
            elif event.button == 3 and self.place_cool <= 0.0:
                self.place_block()
            elif event.button == 2:
                hit = self.world.raycast(self.player.eye_pos(),
                                         self.player.forward(), MAX_REACH)
                if hit:
                    block = hit[2]
                    if block in PLACEABLE:
                        self.hotbar[self.slot] = block

    # -- actions ------------------------------------------------------------

    def _hit(self, cached):
        """Event clicks get a fresh ray; held-button repeats reuse the ray
        already cast this frame."""
        if cached:
            return self.target
        return self.world.raycast(self.player.eye_pos(), self.player.forward(),
                                  MAX_REACH)

    def break_block(self, cached: bool = False) -> None:
        hit = self._hit(cached)
        if hit is None:
            return
        pos, _normal, _block = hit
        above = self.world.get(pos[0], pos[1] + 1, pos[2])
        if self.world.break_block(*pos):
            self.break_cool = 0.20
            if self.net and self.net.connected:
                self.net.send_block(pos[0], pos[1], pos[2], AIR)
                if pos[1] + 1 < WY and IS_PLANT[above]:
                    self.net.send_block(pos[0], pos[1] + 1, pos[2], AIR)

    def place_block(self, cached: bool = False) -> None:
        hit = self._hit(cached)
        if hit is None:
            return
        pos, normal, block = hit
        if IS_PLANT[block]:
            target = pos
        else:
            target = (pos[0] + normal[0], pos[1] + normal[1], pos[2] + normal[2])
        tx, ty, tz = target
        if not (0 <= tx < WX and 0 <= ty < WY and 0 <= tz < WZ):
            return
        existing = self.world.get(tx, ty, tz)
        if existing != AIR and existing != WATER and not IS_PLANT[existing]:
            return
        held = self.hotbar[self.slot]
        placed = entry_block(held)
        if placed == AIR:
            return
        if IS_PLANT[placed]:
            support = self.world.get(tx, ty - 1, tz)
            if support == AIR or not IS_SOLID[support]:
                return
        if self.player.intersects_block(tx, ty, tz):
            return
        if self.world.set_block(tx, ty, tz, placed):
            self.place_cool = 0.20
            if self.net and self.net.connected:
                self.net.send_block(tx, ty, tz, placed)

    def update(self, dt: float) -> None:
        self._handle_net_events()
        self.target = self.world.raycast(self.player.eye_pos(),
                                         self.player.forward(), MAX_REACH)
        keys = pygame.key.get_pressed()
        if self.chat_open:
            forward = strafe = 0
            jump = sprint = descend = False
        else:
            forward = (1 if keys[pygame.K_w] else 0) - (1 if keys[pygame.K_s] else 0)
            strafe = (1 if keys[pygame.K_d] else 0) - (1 if keys[pygame.K_a] else 0)
            if self.player.fly:
                sprint = bool(keys[pygame.K_LCTRL] or keys[pygame.K_RCTRL])
                descend = bool(keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT])
            else:
                sprint = bool(keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT])
                descend = False
            jump = bool(keys[pygame.K_SPACE])
        self.player.update(dt, float(forward), float(strafe), jump, sprint, descend)
        self.break_cool = max(0.0, self.break_cool - dt)
        self.place_cool = max(0.0, self.place_cool - dt)
        self.toast_timer = max(0.0, self.toast_timer - dt)
        if self.captured and not self.chat_open and self.target is not None:
            mouse = pygame.mouse.get_pressed()
            if mouse[0] and self.break_cool <= 0.0:
                self.break_block(cached=True)
            if mouse[2] and self.place_cool <= 0.0:
                self.place_block(cached=True)

        # Smooth remote players and keep the host updated.
        k = min(1.0, 14.0 * dt)
        for rp in self.remote_players.values():
            if rp.has_pos:
                rp.pos += (rp.target - rp.pos) * k
        self._send_net_pos(dt)

        # Chat messages fade out after a while.
        for msg in self.chat_messages:
            msg[2] -= dt
        self.chat_messages = [m for m in self.chat_messages if m[2] > 0.0]

        self.world.flush_dirty(self.renderer)

    # -- main loop ----------------------------------------------------------

    def render(self) -> None:
        self.renderer.draw(self)
        pygame.display.flip()

    def run(self) -> None:
        if self.auto_record:
            scene = {"world": "playing", "pause": "paused"}.get(
                self.auto_scene, self.auto_scene)
            self.state = scene
            self.set_captured(False)
            self.toast_timer = 0.0
            frame_dir = Path(self.auto_record)
            frame_dir.mkdir(parents=True, exist_ok=True)
            fps = 30
            total = max(1, int(self.record_seconds * fps))
            frame_step = 1.0 / fps
            for i in range(total):
                frame_start = time.perf_counter()
                self.renderer.draw(self)
                self.renderer.save_screenshot(str(frame_dir / f"frame_{i:05d}.png"))
                pygame.display.flip()
                pygame.event.pump()
                time.sleep(max(0.0, frame_step - (time.perf_counter() - frame_start)))
            print(f"recorded {total} frames to {frame_dir}")
            self.running = False
            return

        if self.auto_screenshot:
            scene = {"world": "playing", "pause": "paused"}.get(
                self.auto_scene, self.auto_scene)
            self.state = scene
            self.set_captured(False)
            if self.state == "playing":
                self.toast_timer = 0.0
            for i in range(14):
                if self.state == "playing":
                    self.player.update(1.0 / 60.0, 0.0, 0.0, False, False, False)
                self.renderer.draw(self)
                if i == 13:
                    self.renderer.save_screenshot(self.auto_screenshot)
                pygame.display.flip()
                pygame.event.pump()
                time.sleep(0.01)
            print(f"screenshot saved: {self.auto_screenshot}")
            self.running = False
            return

        clock = pygame.time.Clock()
        while self.running:
            dt = min(clock.tick(144) / 1000.0, 0.05)
            self.handle_events()
            if self.state == "playing":
                self.update(dt)
                if self.active_world_file is not None and (self.net is None or self.net.is_host):
                    self.autosave_elapsed += dt
                    if self.autosave_elapsed >= self.autosave_interval:
                        self.save_world(silent=True)
            self.render()
            self.fps_frames += 1
            self.fps_timer += dt
            if self.fps_timer >= 0.5:
                self.last_fps = self.fps_frames / max(self.fps_timer, 1e-6)
                self.fps_frames = 0
                self.fps_timer = 0.0
            self.frame_count += 1
        self.save_world(silent=True)


# ----------------------------------------------------------------------------
# Renderer
# ----------------------------------------------------------------------------

TERRAIN_VS = """
#version 330
in vec3 in_pos;
in vec2 in_uv;
in float in_shade;
uniform mat4 u_vp;
out vec2 v_uv;
out float v_shade;
out vec3 v_world;
void main() {
    v_uv = in_uv;
    v_shade = in_shade;
    v_world = in_pos;
    gl_Position = u_vp * vec4(in_pos, 1.0);
}
"""

TERRAIN_FS = """
#version 330
uniform sampler2D u_tex;
uniform vec3 u_cam;
uniform vec3 u_fog;
uniform vec2 u_fog_range;
uniform int u_cutout;
uniform float u_alpha;
uniform vec2 u_uv_offset;
in vec2 v_uv;
in float v_shade;
in vec3 v_world;
out vec4 frag;
void main() {
    vec4 tex = texture(u_tex, v_uv + u_uv_offset);
    if (u_cutout == 1 && tex.a < 0.5) discard;
    vec3 col = tex.rgb * v_shade;
    float d = distance(v_world, u_cam);
    float f = smoothstep(u_fog_range.x, u_fog_range.y, d);
    col = mix(col, u_fog, f);
    frag = vec4(col, tex.a * u_alpha);
}
"""

SKY_VS = """
#version 330
in vec2 in_pos;
out vec2 v_ndc;
void main() {
    v_ndc = in_pos;
    gl_Position = vec4(in_pos, 0.999, 1.0);
}
"""



LINE_VS = """
#version 330
in vec3 in_pos;
uniform mat4 u_vp;
uniform vec3 u_center;
void main() {
    gl_Position = u_vp * vec4(u_center + (in_pos - 0.5) * 1.008, 1.0);
}
"""

LINE_FS = """
#version 330
uniform vec4 u_color;
out vec4 frag;
void main() {
    frag = u_color;
}
"""

SOLID_VS = """
#version 330
in vec3 in_pos;
uniform mat4 u_vp;
uniform vec3 u_center;
uniform vec3 u_scale;
void main() {
    gl_Position = u_vp * vec4(u_center + (in_pos - 0.5) * u_scale, 1.0);
}
"""

SOLID_FS = """
#version 330
uniform vec4 u_color;
out vec4 frag;
void main() {
    frag = u_color;
}
"""

_CUBE_CORNERS = np.array([
    [0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1],
    [0, 1, 0], [1, 1, 0], [1, 1, 1], [0, 1, 1],
], dtype="f4")
_CUBE_FACES = (
    (0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6),
    (0, 4, 5), (0, 5, 1), (3, 2, 6), (3, 6, 7),
    (0, 3, 7), (0, 7, 4), (1, 5, 6), (1, 6, 2),
)
_CUBE_TRIS = _CUBE_CORNERS[list(_CUBE_FACES)].reshape(-1, 3)


SKIN_VS = """
#version 330
in vec3 in_pos;
in vec2 in_uv;
uniform mat4 u_vp;
uniform vec3 u_center;
uniform vec3 u_scale;
uniform float u_yaw;
out vec2 v_uv;
void main() {
    v_uv = in_uv;
    vec3 p = (in_pos - 0.5) * u_scale;
    float c = cos(u_yaw);
    float s = sin(u_yaw);
    vec3 r = vec3(p.x * c + p.z * s, p.y, -p.x * s + p.z * c);
    gl_Position = u_vp * vec4(u_center + r, 1.0);
}
"""
SKIN_FS = """
#version 330
uniform sampler2D u_skin;
in vec2 v_uv;
out vec4 frag;
void main() {
    frag = texture(u_skin, v_uv);
    if (frag.a < 0.08) discard;
}
"""

def _skin_cube_mesh(w, h, d, u, v):
    """Build classic Minecraft skin UV cuboid mesh; dimensions and UVs are pixels."""
    # Face corner order matches the triangles below; each UV rectangle is top-origin.
    faces = [
        # front (+z), back (-z), left (-x), right (+x), top (+y), bottom (-y)
        ((3, 2, 6, 7), (u+d, v+d, w, h)),
        ((0, 1, 5, 4), (u+2*d+w, v+d, w, h)),
        ((0, 3, 7, 4), (u, v+d, d, h)),
        ((1, 2, 6, 5), (u+d+w, v+d, d, h)),
        ((4, 5, 6, 7), (u+d, v, w, d)),
        ((0, 1, 2, 3), (u+d+w, v, w, d)),
    ]
    corners = np.array([[0,0,0],[1,0,0],[1,0,1],[0,0,1],
                       [0,1,0],[1,1,0],[1,1,1],[0,1,1]], dtype=np.float32)
    out=[]
    for face_index, (ids, rect) in enumerate(faces):
        x, y, rw, rh = rect
        # The four side faces are ordered bottom-left, bottom-right,
        # top-right, top-left in model space. Match those vertices to the
        # corresponding bottom/top rows in the skin image. The texture upload
        # uses flipud(), so OpenGL V coordinates are inverted.
        if face_index < 4:
            uv4 = (
                (x / 64, 1 - (y + rh) / 64),
                ((x + rw) / 64, 1 - (y + rh) / 64),
                ((x + rw) / 64, 1 - y / 64),
                (x / 64, 1 - y / 64),
            )
        else:
            # Top and bottom faces lie in the X/Z plane; preserve their
            # horizontal atlas orientation.
            uv4 = (
                (x / 64, 1 - y / 64),
                ((x + rw) / 64, 1 - y / 64),
                ((x + rw) / 64, 1 - (y + rh) / 64),
                (x / 64, 1 - (y + rh) / 64),
            )
        for j in (0, 1, 2, 0, 2, 3):
            out.extend(corners[ids[j]].tolist())
            out.extend(uv4[j])
    return np.asarray(out, dtype=np.float32)



UI_VS = """
#version 330
in vec2 in_pos;
in vec2 in_uv;
in vec4 in_color;
uniform vec2 u_screen;
out vec2 v_uv;
out vec4 v_color;
void main() {
    v_uv = in_uv;
    v_color = in_color;
    vec2 ndc = vec2(in_pos.x / u_screen.x * 2.0 - 1.0,
                    1.0 - in_pos.y / u_screen.y * 2.0);
    gl_Position = vec4(ndc, 0.0, 1.0);
}
"""

UI_FS = """
#version 330
uniform sampler2D u_tex;
uniform int u_use_tex;
in vec2 v_uv;
in vec4 v_color;
out vec4 frag;
void main() {
    vec4 c = v_color;
    if (u_use_tex == 1) c *= texture(u_tex, v_uv);
    if (c.a <= 0.002) discard;
    frag = c;
}
"""


def col(r: int, g: int, b: int, a: int = 255):
    return (r / 255.0, g / 255.0, b / 255.0, a / 255.0)


WHITE = col(255, 255, 255)
BLACK = col(0, 0, 0)
SHADOW = col(0, 0, 0, 175)

UI_QUAD_BYTES = 4 * 8 * 4      # 4 vertices * 8 floats * 4 bytes


class Renderer:
    def __init__(self, ctx, width: int, height: int) -> None:
        self.ctx = ctx
        self.width = width
        self.height = height
        self.window = pygame.display.get_surface()

        # Shader files are editable independently; embedded GLSL remains a safe fallback.
        shader_dir = ASSET_DIR / "shaders"
        def shader_source(filename: str, fallback: str) -> str:
            path = shader_dir / filename
            try:
                return path.read_text(encoding="utf-8")
            except OSError:
                return fallback

        self.terrain_prog = ctx.program(
            vertex_shader=shader_source("terrain.vert", TERRAIN_VS),
            fragment_shader=shader_source("terrain.frag", TERRAIN_FS))

        # Use Azure Water's original fragment shader directly from the research
        # project. Its vertex input is adapted only to PyCraft's world-space
        # block mesh and per-vertex shoreline fade attribute.
        azure_shader_dir = ROOT / "_research" / "azure-water" / "water" / "shaders"
        azure_water_vs = (azure_shader_dir / "water.vert").read_text(encoding="utf-8")
        azure_water_fs = (azure_shader_dir / "water.frag").read_text(encoding="utf-8")
        azure_water_vs = azure_water_vs.replace(
            "in vec2 in_pos;", "in vec3 in_pos;\nin float in_flex;")
        azure_water_vs = azure_water_vs.replace(
            "uniform vec2 u_center;", "")
        azure_water_vs = azure_water_vs.replace(
            "vec2 xz = in_pos + u_center;", "vec2 xz = in_pos.xz;")
        azure_water_vs = azure_water_vs.replace(
            "vec3 P = vec3(xz.x, 0.0, xz.y);", "vec3 P = in_pos;")
        azure_water_vs = azure_water_vs.replace(
            "float Aeff = A * lod;", "float Aeff = A * lod * clamp(in_flex, 0.0, 1.0);")
        self.azure_water_prog = ctx.program(vertex_shader=azure_water_vs,
                                            fragment_shader=azure_water_fs)
        self.azure_water_vaos = {}
        azure_sky_fs = (ROOT / "Assets" / "shaders" / "sky.frag").read_text(encoding="utf-8")
        self.sky_prog = ctx.program(
            vertex_shader=shader_source("sky.vert", SKY_VS),
            fragment_shader=azure_sky_fs)
        self.line_prog = ctx.program(vertex_shader=LINE_VS,
                                     fragment_shader=LINE_FS)
        self.ui_prog = ctx.program(vertex_shader=UI_VS,
                                   fragment_shader=UI_FS)

        # One shared index buffer for every quad-based mesh (terrain + UI).
        base = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint32)
        idx = (np.arange(QUAD_CAP, dtype=np.uint32)[:, None] * 4 + base).ravel()
        self.quad_ibo = ctx.buffer(idx.tobytes())

        # Fullscreen sky triangle.
        sky_vbo = ctx.buffer(np.array([-1, -1, 3, -1, -1, 3],
                                      dtype="f4").tobytes())
        self.sky_vao = ctx.vertex_array(self.sky_prog,
                                        [(sky_vbo, "2f", "in_pos")])

        # Azure Water integration: a screen-color copy for refraction and a
        # mirrored procedural-sky pass for projective planar reflections.
        # Keep these targets independent from the voxel world's depth buffer.
        rw, rh = max(2, width // 2), max(2, height // 2)
        self.water_scene_tex = ctx.texture((width, height), 4, dtype="f2")
        self.water_scene_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.water_scene_depth = ctx.depth_texture((width, height))
        self.water_scene_depth.filter = (moderngl.NEAREST, moderngl.NEAREST)
        self.water_scene_fbo = ctx.framebuffer(
            color_attachments=[self.water_scene_tex],
            depth_attachment=self.water_scene_depth)
        self.water_refl_tex = ctx.texture((rw, rh), 4, dtype="f2")
        self.water_refl_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.water_refl_fbo = ctx.framebuffer(color_attachments=[self.water_refl_tex])

        # Block selection wireframe (unit cube).
        edges = []
        for a in range(8):
            for b in range(a + 1, 8):
                if bin(a ^ b).count("1") == 1:
                    edges += [a & 1, (a >> 1) & 1, (a >> 2) & 1,
                              b & 1, (b >> 1) & 1, (b >> 2) & 1]
        line_vbo = ctx.buffer(np.array(edges, dtype="f4").tobytes())
        self.line_vao = ctx.vertex_array(self.line_prog,
                                         [(line_vbo, "3f", "in_pos")])

        # Solid unit cube for remote player avatars.
        self.solid_prog = ctx.program(vertex_shader=SOLID_VS,
                                      fragment_shader=SOLID_FS)
        solid_vbo = ctx.buffer(_CUBE_TRIS.astype("f4").tobytes())
        self.solid_vao = ctx.vertex_array(
            self.solid_prog, [(solid_vbo, "3f", "in_pos")])
        # Minecraft-style skin-textured cuboids for remote player models.
        self.skin_prog = ctx.program(vertex_shader=SKIN_VS, fragment_shader=SKIN_FS)
        self.skin_prog["u_skin"].value = 0
        self.skin_meshes = {}
        # classic 64x64 layout: head, torso, right arm, right leg
        for key, dims, uv in (
            ("head", (8,8,8), (0,0)), ("torso", (8,12,4), (16,16)),
            ("arm", (4,12,4), (40,16)), ("leg", (4,12,4), (0,16)),
        ):
            mesh = _skin_cube_mesh(*dims, *uv)
            vbo = ctx.buffer(mesh.tobytes())
            self.skin_meshes[key] = ctx.vertex_array(self.skin_prog, [(vbo, "3f 2f", "in_pos", "in_uv")])

        # Textures.
        self.atlas_tex = self._upload_texture(ATLAS_IMAGE, repeat=False,
                                              linear=False, kind="atlas")
        self.font_tex, self.glyphs = self._load_font()
        self.cloud_vao, self.cloud_tex, self.cloud_count = None, None, 0
        self.panorama_tex = None
        self.title_tex = None
        self.title_size = (1024, 256)
        pano = load_png("gui/title/background/panorama_0.png")
        if pano is not None:
            self.panorama_tex = self._upload_texture(pano, repeat=False,
                                                     linear=True, mipmaps=True)
        logo = load_png("gui/title/minecraft.png")
        if logo is not None:
            self.title_tex = self._upload_texture(logo, repeat=False,
                                                  linear=True, mipmaps=True)
            self.title_size = logo.size
        self.skin_tex = None
        # Load the skin relative to this script, not the process working
        # directory. This allows launching PyCraft from a shortcut/terminal in
        # another folder. Also support the optional Assets/skin.png location.
        skin_path = next((p for p in (ROOT / "skin.png", ASSET_DIR / "skin.png",
                                       Path.cwd() / "skin.png") if p.is_file()), None)
        if skin_path is not None:
            try:
                skin = Image.open(skin_path).convert("RGBA")
                if skin.size not in ((64, 64), (64, 32)):
                    raise ValueError(f"Unsupported skin dimensions: {skin.size}; expected 64x64 or legacy 64x32")
                if skin.size == (64, 32):
                    # Legacy skin files are supported for loading/preview; their
                    # missing lower half is padded transparent for the preview.
                    padded = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
                    padded.paste(skin, (0, 0))
                    skin = padded
                self.skin_tex = self._upload_texture(skin, repeat=False,
                                                   linear=False, mipmaps=False)
                print(f"[skin] loaded {skin_path} ({skin.size[0]}x{skin.size[1]})")
            except Exception as exc:
                print(f"[skin] failed to load {skin_path}: {exc}", file=sys.stderr)
        else:
            print("[skin] skin.png not found. Put a classic 64x64 Minecraft skin next to app.py.", file=sys.stderr)

        # UI batches (indexed quads).
        self.ui_solid = array("f")
        self.ui_icons = array("f")
        self.ui_text: list[np.ndarray] = []
        self._text_cache: dict[tuple, np.ndarray] = {}
        self._width_cache: dict[tuple, int] = {}
        self.ui_solid_vbo = ctx.buffer(reserve=2 * 1024 * 1024, dynamic=True)
        self.ui_icon_vbo = ctx.buffer(reserve=2 * 1024 * 1024, dynamic=True)
        self.ui_text_vbo = ctx.buffer(reserve=2 * 1024 * 1024, dynamic=True)
        layout = "2f 2f 4f"
        names = ("in_pos", "in_uv", "in_color")

        def ui_vao(vbo):
            return ctx.vertex_array(self.ui_prog, [(vbo, layout, *names)],
                                    index_buffer=self.quad_ibo)

        self.ui_solid_vao = ui_vao(self.ui_solid_vbo)
        self.ui_icon_vao = ui_vao(self.ui_icon_vbo)
        self.ui_text_vao = ui_vao(self.ui_text_vbo)
        self.scratch_vbo = ctx.buffer(reserve=UI_QUAD_BYTES, dynamic=True)
        self.scratch_vao = ui_vao(self.scratch_vbo)

        self.hotspots: dict[str, pygame.Rect] = {}
        self.inventory_cells: list[tuple[pygame.Rect, int]] = []
        self.start_time = time.perf_counter()
        self.time = 0.0

        # Frustum-culling cache (rebuilt only when chunk meshes change).
        self._cull_version = -1
        self._cull_keys: list[tuple[int, int]] = []
        self._cull_min = np.zeros((0, 3), dtype=np.float64)
        self._cull_max = np.zeros((0, 3), dtype=np.float64)
        self._cull_ctr = np.zeros((0, 2), dtype=np.float64)

    # -- setup helpers ------------------------------------------------------

    def _upload_texture(self, img, repeat: bool = False, linear: bool = False,
                        mipmaps: bool = False, kind: str = "") -> object:
        if not isinstance(img, Image.Image):
            arr = np.asarray(img, dtype=np.uint8)
            h, w = arr.shape[:2]
            rgba = arr if arr.shape[2] == 4 else np.dstack(
                [arr, np.full((h, w), 255, np.uint8)])
        else:
            rgba = np.asarray(img.convert("RGBA"), dtype=np.uint8)
            h, w = rgba.shape[:2]
        tex = self.ctx.texture((w, h), 4, np.flipud(rgba).tobytes())
        if mipmaps:
            tex.build_mipmaps()
        if linear:
            tex.filter = ((moderngl.LINEAR_MIPMAP_LINEAR if mipmaps else moderngl.LINEAR),
                          moderngl.LINEAR)
        else:
            tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        tex.repeat_x = repeat
        tex.repeat_y = repeat
        return tex

    def _load_font(self):
        glyphs = {}
        try:
            im = Image.open(ASSET_DIR / "font" / "ascii.png").convert("RGBA")
            arr = np.asarray(im, dtype=np.uint8)
            sw, sh = im.size
            for code in range(32, 127):
                cx = (code % 16) * 8
                cy = (code // 16) * 8
                if cx + 8 > sw or cy + 8 > sh:
                    continue
                alpha = arr[cy:cy + 8, cx:cx + 8, 3]
                cols = np.where(alpha.max(axis=0) > 8)[0]
                if cols.size:
                    adv = min(8, int(cols[-1]) + 2)
                    has_ink = True
                else:
                    adv, has_ink = 4, False
                u0 = (cx + 0.02) / sw
                u1 = (cx + 7.98) / sw
                v0 = (sh - cy - 8 + 0.02) / sh
                v1 = (sh - cy - 0.02) / sh
                glyphs[chr(code)] = (u0, v0, u1, v1, adv, has_ink)
            tex = self._upload_texture(im, linear=False)
        except Exception as exc:
            print(f"[font] failed: {exc}", file=sys.stderr)
            tex = None
        return tex, glyphs

    def _make_cloud_layer(self):
        """Build a big repeating cloud plane from the asset's dither mask.

        clouds.png is a 1-bit dither, so averaging it down to 16x16
        recovers the intended chunky silhouette.  One texel becomes a
        ~12-block cloud cell, and the layer sits high above the terrain.
        """
        try:
            im = Image.open(ASSET_DIR / "environment" / "clouds.png")
            small = im.convert("L").resize((16, 16), Image.BOX)
            arr = np.asarray(small, dtype=np.float32) / 255.0
            alpha = np.where(arr > 0.32, 255, 0).astype(np.uint8)
            rgba = np.full((16, 16, 4), 255, np.uint8)
            rgba[:, :, 3] = alpha
            tex = self._upload_texture(rgba, repeat=True, linear=False)
        except Exception:
            return None, None, 0

        c = WX * 2.0
        cxw, czw = WX * 0.5, WZ * 0.5
        cy = 140.0
        positions = [(cxw - c, cy, czw + c), (cxw + c, cy, czw + c),
                     (cxw + c, cy, czw - c), (cxw - c, cy, czw - c)]
        uvs = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]
        verts = []
        for idx in (0, 1, 2, 0, 2, 3):
            verts.extend([*positions[idx], *uvs[idx], 1.0])
        vbo = self.ctx.buffer(np.asarray(verts, dtype="f4").tobytes())
        vao = self.ctx.vertex_array(
            self.terrain_prog,
            [(vbo, "3f 2f 1f", "in_pos", "in_uv", "in_shade")])
        return vao, tex, 6

    def make_gpu_mesh(self, verts: np.ndarray) -> GpuMesh:
        quads = min(verts.shape[0] // 4, QUAD_CAP)
        vbo = self.ctx.buffer(np.ascontiguousarray(verts, dtype="f4").tobytes())
        vao = self.ctx.vertex_array(
            self.terrain_prog,
            [(vbo, "3f 2f 1f 1f", "in_pos", "in_uv", "in_shade", "in_flex")],
            index_buffer=self.quad_ibo)
        return GpuMesh(vao, vbo, quads * 6)

    def release_chunk(self, meshes: dict[str, GpuMesh]) -> None:
        for mesh in meshes.values():
            try:
                azure_vao = self.azure_water_vaos.pop(id(mesh), None)
                if azure_vao is not None:
                    azure_vao.release()
                mesh.vao.release()
                mesh.vbo.release()
            except Exception:
                pass

    def release_world(self, world: World) -> None:
        for meshes in world.meshes.values():
            self.release_chunk(meshes)
        world.meshes.clear()
        self._cull_version = -1
        self._cull_keys = []
        self._cull_min = np.zeros((0, 3), dtype=np.float64)
        self._cull_max = np.zeros((0, 3), dtype=np.float64)
        self._cull_ctr = np.zeros((0, 2), dtype=np.float64)

    # -- 2D primitives ------------------------------------------------------

    def _push(self, batch, points, uvs, colors):
        multi = isinstance(colors, list)
        c = colors
        for i in range(4):
            p = points[i]
            uv = uvs[i]
            if multi:
                c = colors[i]
            batch.extend((p[0], p[1], uv[0], uv[1], c[0], c[1], c[2], c[3]))

    def rect(self, x, y, w, h, color, batch=None):
        b = self.ui_solid if batch is None else batch
        pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
        self._push(b, pts, [(0, 0)] * 4, color)

    def outline(self, x, y, w, h, thickness, color):
        t = thickness
        self.rect(x, y, w, t, color)
        self.rect(x, y + h - t, w, t, color)
        self.rect(x, y, t, h, color)
        self.rect(x + w - t, y, t, h, color)

    def tex_rect(self, x, y, w, h, tile, color=WHITE):
        u0, v0, u1, v1 = tile
        pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
        uvs = [(u0, v1), (u1, v1), (u1, v0), (u0, v0)]
        self._push(self.ui_icons, pts, uvs, color)

    def poly_tex(self, points, tile, shades):
        u0, v0, u1, v1 = tile
        uvs = [(u0, v1), (u1, v1), (u1, v0), (u0, v0)]
        colors = [(s, s, s, 1.0) for s in shades]
        self._push(self.ui_icons, points, uvs, colors)

    def measure_text(self, text: str, scale: int) -> int:
        key = (text, scale)
        w = self._width_cache.get(key)
        if w is not None:
            return w
        best = 0
        glyphs = self.glyphs
        fallback = glyphs.get("?")
        for line in text.split("\n"):
            lw = 0
            for ch in line:
                g = glyphs.get(ch, fallback)
                lw += (g[4] if g else 4) * scale
            best = max(best, lw)
        if len(self._width_cache) > 2048:
            self._width_cache.clear()
        self._width_cache[key] = best
        return best

    def _text_geometry(self, text: str, scale: int, color, shadow: bool):
        """Quad geometry for a string at origin (0,0); cached per style."""
        key = (text, scale, color, shadow)
        geo = self._text_cache.get(key)
        if geo is not None:
            return geo
        out = array("f")
        line_h = 9 * scale
        fallback = self.glyphs.get("?")
        for li, line in enumerate(text.split("\n")):
            ly = li * line_h
            for pass_shadow in (True, False):
                if pass_shadow and not shadow:
                    continue
                xx = float(scale if pass_shadow else 0)
                yy = float(ly + (scale if pass_shadow else 0))
                c = SHADOW if pass_shadow else color
                for ch in line:
                    g = self.glyphs.get(ch) or fallback
                    if g is None:
                        continue
                    u0, v0, u1, v1, adv, ink = g
                    if ink:
                        x1, y1 = xx + 8 * scale, yy + 8 * scale
                        out.extend((xx, yy, u0, v1, *c,
                                    x1, yy, u1, v1, *c,
                                    x1, y1, u1, v0, *c,
                                    xx, y1, u0, v0, *c))
                    xx += adv * scale
        geo = np.frombuffer(out, dtype=np.float32).reshape(-1, 8).copy()
        if len(self._text_cache) > 1024:      # e.g. debug overlay churn
            self._text_cache.clear()
        self._text_cache[key] = geo
        return geo

    def text(self, text: str, x, y, scale=2, color=WHITE, shadow=True,
             align="left"):
        if self.font_tex is None or not text:
            return
        if align == "center":
            x -= self.measure_text(text, scale) // 2
        elif align == "right":
            x -= self.measure_text(text, scale)
        geo = self._text_geometry(text, scale, color, shadow)
        if geo.shape[0] == 0:
            return
        g = geo.copy()
        g[:, 0] += x
        g[:, 1] += y
        self.ui_text.append(g)

    def draw_block_icon(self, block_id: int, x, y, size):
        b = BLOCKS[block_id]
        if b.kind != "cube":
            self.tex_rect(x + size * 0.06, y + size * 0.06, size * 0.88,
                          size * 0.88, TILE_UVS[b.side])
            return
        top_tile = TILE_UVS[b.top]
        side_tile = TILE_UVS[b.side]
        cx = x + size * 0.5
        top_y = y + size * 0.04
        mid_y = y + size * 0.30
        center_y = y + size * 0.54
        side_bottom = y + size * 0.78
        bottom_y = y + size
        left_x = x + size * 0.04
        right_x = x + size * 0.96
        T = (cx, top_y)
        R = (right_x, mid_y)
        C = (cx, center_y)
        L = (left_x, mid_y)
        BL = (left_x, side_bottom)
        BR = (right_x, side_bottom)
        B = (cx, bottom_y)
        self.poly_tex([T, R, C, L], top_tile, [1.0, 1.0, 1.0, 1.0])
        self.poly_tex([L, C, B, BL], side_tile, [0.82, 0.82, 0.82, 0.82])
        self.poly_tex([C, R, BR, B], side_tile, [0.64, 0.64, 0.64, 0.64])

    def draw_item_icon(self, item_id: int, x, y, size):
        if not (0 <= item_id < len(ITEMS)):
            return
        pad = size * 0.04
        self.tex_rect(x + pad, y + pad, size - pad * 2, size - pad * 2,
                      TILE_UVS[ITEMS[item_id].tile])

    def draw_entry_icon(self, entry: int, x, y, size):
        if entry < 0:
            self.draw_item_icon(-entry - 1, x, y, size)
        elif 0 <= entry < N_BLOCKS:
            self.draw_block_icon(entry, x, y, size)

    # -- UI rendering -------------------------------------------------------

    def _begin_ui(self):
        self.ui_solid = array("f")
        self.ui_icons = array("f")
        self.ui_text = []
        self.hotspots = {}
        self.inventory_cells = []
        ctx = self.ctx
        ctx.viewport = (0, 0, self.width, self.height)
        ctx.disable(moderngl.DEPTH_TEST)
        ctx.disable(moderngl.CULL_FACE)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA)
        ctx.depth_mask = False
        self.ui_prog["u_screen"].value = (float(self.width), float(self.height))
        self.ui_prog["u_tex"].value = 0

    def _flush_batch(self, data, vao, vbo, use_tex: int, texture=None):
        if data is None or data.size == 0:
            return
        quads = data.size // 32
        max_quads = min(vbo.size // UI_QUAD_BYTES, QUAD_CAP)
        if quads > max_quads:
            quads = max_quads
            data = data[:quads * 32]
        vbo.write(data.tobytes())
        self.ui_prog["u_use_tex"].value = use_tex
        if use_tex and texture is not None:
            texture.use(0)
        vao.render(moderngl.TRIANGLES, vertices=quads * 6)

    def _flush_ui(self):
        if self.ui_solid:
            self._flush_batch(np.frombuffer(self.ui_solid, dtype=np.float32),
                              self.ui_solid_vao, self.ui_solid_vbo, 0)
        if self.ui_icons:
            self._flush_batch(np.frombuffer(self.ui_icons, dtype=np.float32),
                              self.ui_icon_vao, self.ui_icon_vbo, 1,
                              self.atlas_tex)
        if self.ui_text:
            data = (self.ui_text[0] if len(self.ui_text) == 1
                    else np.concatenate(self.ui_text, axis=0))
            self._flush_batch(np.ascontiguousarray(data).reshape(-1),
                              self.ui_text_vao, self.ui_text_vbo, 1,
                              self.font_tex)

    def _scratch_quad(self, pts, uvs, c, use_tex, tex=None):
        verts = array("f")
        for i in range(4):
            p, uv = pts[i], uvs[i]
            verts.extend((p[0], p[1], uv[0], uv[1], c[0], c[1], c[2], c[3]))
        self.scratch_vbo.write(verts.tobytes())
        self.ui_prog["u_use_tex"].value = use_tex
        if use_tex and tex is not None:
            tex.use(0)
        self.scratch_vao.render(moderngl.TRIANGLES, vertices=6)

    def texture_quad(self, tex, x, y, w, h, alpha=1.0):
        if tex is None:
            return
        c = col(255, 255, 255, int(255 * alpha))
        pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
        self._scratch_quad(pts, [(0, 1), (1, 1), (1, 0), (0, 0)], c, 1, tex)

    def hit_hotspot(self, pos):
        for key, rect in self.hotspots.items():
            if rect.collidepoint(pos):
                return key
        return None

    def inventory_pick(self, pos):
        for rect, block_id in self.inventory_cells:
            if rect.collidepoint(pos):
                return block_id
        return None

    def save_screenshot(self, path: str) -> None:
        data = self.ctx.screen.read(components=3)
        img = Image.frombytes("RGB", (self.width, self.height), data)
        img = img.transpose(Image.FLIP_TOP_BOTTOM)
        out = Path(path)
        if out.parent != Path(""):
            out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out)

    # -- frustum culling ----------------------------------------------------

    def visible_chunks(self, world: World, vp: np.ndarray, cam) -> list:
        """Layer dicts of chunks inside the view frustum and draw distance,
        sorted nearest-first."""
        if self._cull_version != world.mesh_version:
            keys = list(world.meshes.keys())
            self._cull_keys = keys
            if keys:
                ks = np.array(keys, dtype=np.float64)
                ymax = np.array([max(1, world.chunk_ymax.get(k, WY)) for k in keys],
                                dtype=np.float64)
                mins = np.stack([ks[:, 0] * CHUNK, np.zeros(len(keys)),
                                 ks[:, 1] * CHUNK], axis=1)
                maxs = mins + np.stack([np.full(len(keys), CHUNK), ymax,
                                        np.full(len(keys), CHUNK)], axis=1)
            else:
                mins = maxs = np.zeros((0, 3))
            self._cull_min, self._cull_max = mins, maxs
            self._cull_ctr = (mins[:, [0, 2]] + CHUNK * 0.5)
            self._cull_version = world.mesh_version
        if not self._cull_keys:
            return []

        planes = frustum_planes(vp)
        n = planes[:, :3]
        # Positive vertex of each AABB per plane.
        pv = np.where(n[None, :, :] >= 0.0, self._cull_max[:, None, :],
                      self._cull_min[:, None, :])
        dist = (pv * n[None, :, :]).sum(axis=2) + planes[None, :, 3]
        inside = (dist >= 0.0).all(axis=1)
        d = self._cull_ctr - np.array([cam[0], cam[2]])
        d2 = (d * d).sum(axis=1)
        inside &= d2 <= (RENDER_DISTANCE + 32.0) ** 2
        idx = np.flatnonzero(inside)
        if idx.size == 0:
            return []
        idx = idx[np.argsort(d2[idx], kind="stable")]
        keys = self._cull_keys
        meshes = world.meshes
        return [meshes[keys[i]] for i in idx]

    # -- world rendering ----------------------------------------------------

    # -- world rendering ----------------------------------------------------

    def _set_azure_sky_uniforms(self, forward, right, up, tan_x, tan_y, reflected=False):
        """Use Azure Water's procedural sky in both the camera and water reflection passes."""
        if reflected:
            forward = np.array([forward[0], -forward[1], forward[2]], dtype=np.float32)
            up = np.array([up[0], -up[1], up[2]], dtype=np.float32)
            sun = np.array([SUN_DIR[0], -SUN_DIR[1], SUN_DIR[2]], dtype=np.float32)
        else:
            sun = np.asarray(SUN_DIR, dtype=np.float32)
        p = self.sky_prog
        p["u_forward"].value = tuple(float(v) for v in forward)
        p["u_right"].value = tuple(float(v) for v in right)
        p["u_up"].value = tuple(float(v) for v in up)
        p["u_tan"].value = (float(tan_x), float(tan_y))
        p["u_sun_dir"].value = tuple(float(v) for v in sun)
        p["u_sun_color"].value = (1.0, 0.93, 0.83)
        p["u_sun_intensity"].value = 3.2
        p["u_disc_bright"].value = 20.0
        p["u_zenith"].value = (0.135, 0.30, 0.72)
        p["u_horizon"].value = (0.70, 0.82, 0.96)
        p["u_haze"].value = (0.78, 0.86, 1.00)
        p["u_cloud_offset"].value = (float(self.time * 0.00105), float(self.time * 0.00066))
        p["u_cloud_coverage"].value = 0.62
        p["u_cloud_scale"].value = 0.00035

    def draw_world(self, game: "Game") -> None:
        ctx = self.ctx
        world = game.world
        player = game.player
        w, h = self.width, self.height
        aspect = w / max(h, 1)
        cam = player.eye_pos()
        forward = player.forward()
        right = player.right()
        up = normalize(np.cross(right, forward))
        if getattr(game, "third_person", False):
            distance = 4.0
            cam = cam - forward * distance + np.array([0.0, 0.5, 0.0])
            forward = normalize(player.eye_pos() - cam)
        proj = perspective(player.fov, aspect, 0.05, 420.0)
        view = look_at(cam, cam + forward, up)
        vp = proj @ view
        vp_bytes = upload_mat(vp)
        tan_y = math.tan(math.radians(player.fov) * 0.5)
        tan_x = tan_y * aspect

        ctx.viewport = (0, 0, w, h)
        ctx.clear(SKY_HORIZON[0], SKY_HORIZON[1], SKY_HORIZON[2], 1.0)

        # Sky.
        ctx.disable(moderngl.DEPTH_TEST)
        ctx.depth_mask = False
        ctx.disable(moderngl.CULL_FACE)
        ctx.disable(moderngl.BLEND)
        self._set_azure_sky_uniforms(forward, right, up, tan_x, tan_y, reflected=False)
        self.sky_vao.render(moderngl.TRIANGLES, vertices=3)

        # Terrain.
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.enable(moderngl.CULL_FACE)
        ctx.depth_mask = True
        prog = self.terrain_prog
        prog["u_vp"].write(vp_bytes)
        prog["u_cam"].value = tuple(float(v) for v in cam)
        prog["u_sun_dir"].value = tuple(float(v) for v in SUN_DIR)
        prog["u_wind_dir"].value = (0.78, 0.62)
        prog["u_time"].value = float(self.time)
        if player.underwater:
            prog["u_fog"].value = (0.045, 0.16, 0.28)
            prog["u_fog_range"].value = (3.0, 34.0)
        else:
            prog["u_fog"].value = SKY_HORIZON
            prog["u_fog_range"].value = (FOG_START, FOG_END)
        prog["u_tex"].value = 0
        prog["u_alpha"].value = 1.0
        prog["u_cutout"].value = 1
        prog["u_uv_offset"].value = (0.0, 0.0)
        self.atlas_tex.use(0)

        tri = moderngl.TRIANGLES
        visible = self.visible_chunks(world, vp, cam)   # nearest first
        game.drawn_chunks = len(visible)

        # Opaque terrain, front to back (best early-Z rejection).
        if "u_anim_mode" in prog:
            prog["u_anim_mode"].value = 0
        for layers in visible:
            mesh = layers.get("cube")
            if mesh:
                mesh.vao.render(tri, vertices=mesh.count)

        # Leaf canopy and small plants move gently with the wind.
        if "u_anim_mode" in prog:
            prog["u_anim_mode"].value = 1
        for layers in visible:
            mesh = layers.get("foliage")
            if mesh:
                mesh.vao.render(tri, vertices=mesh.count)
        # Individual leaflets detach and flutter down independently.
        if "u_anim_mode" in prog:
            prog["u_anim_mode"].value = 3
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA)
        ctx.depth_mask = False
        # Falling leaves are a near-field detail: avoid transparent particle
        # batches and vertex animation on distant chunks.
        for layers in visible[:6]:
            mesh = layers.get("leaf_fall")
            if mesh:
                mesh.vao.render(tri, vertices=mesh.count)
        ctx.depth_mask = True
        ctx.disable(moderngl.BLEND)
        # Flowers, grass and thin stems flex from their rooted bases.
        if "u_anim_mode" in prog:
            prog["u_anim_mode"].value = 1
        # Cutout plants (two crossed quads, no back-face culling).
        ctx.disable(moderngl.CULL_FACE)
        for layers in visible:
            mesh = layers.get("plant")
            if mesh:
                mesh.vao.render(tri, vertices=mesh.count)

        # Water block sides retain the voxel material; only the top surface
        # is rendered by Azure Water's original Gerstner/reflection shader.
        water_sides = [layers["water"] for layers in reversed(visible)
                       if "water" in layers]
        water_surfaces = [layers["water_surface"] for layers in reversed(visible)
                          if "water_surface" in layers]
        if water_sides:
            prog["u_anim_mode"].value = 0
            prog["u_cutout"].value = 0
            prog["u_alpha"].value = 0.72
            ctx.enable(moderngl.BLEND)
            ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA)
            ctx.depth_mask = False
            for mesh in water_sides:
                mesh.vao.render(tri, vertices=mesh.count)
            ctx.depth_mask = True
            ctx.disable(moderngl.BLEND)
            prog["u_cutout"].value = 1
            prog["u_alpha"].value = 1.0

        if water_surfaces:
            # 1. Mirrored sky reflection, matching Azure Water's planar pass.
            water_level = float(SEA_LEVEL + 1)
            mirror_y = np.eye(4, dtype=np.float32)
            mirror_y[1, 1] = -1.0
            mirror_y[1, 3] = 2.0 * water_level
            reflected_vp = proj @ view @ mirror_y

            rw, rh = self.water_refl_tex.size
            self.water_refl_fbo.use()
            ctx.viewport = (0, 0, rw, rh)
            ctx.disable(moderngl.DEPTH_TEST)
            ctx.disable(moderngl.CULL_FACE)
            ctx.disable(moderngl.BLEND)
            ctx.depth_mask = False
            self._set_azure_sky_uniforms(forward, right, up, tan_x, tan_y, reflected=True)
            self.sky_vao.render(moderngl.TRIANGLES, vertices=3)

            # 2. Copy opaque world color and depth for Azure's refraction/absorption.
            ctx.screen.use()
            ctx.viewport = (0, 0, w, h)
            ctx.copy_framebuffer(self.water_scene_fbo, ctx.screen)
            ctx.depth_mask = True
            ctx.enable(moderngl.DEPTH_TEST)
            ctx.enable(moderngl.CULL_FACE)

            # 3. Azure Water's actual fragment shader on the voxel world's water tops.
            wp = self.azure_water_prog
            wp["u_view_proj"].write(vp_bytes)
            wp["u_refl_view_proj"].write(upload_mat(reflected_vp))
            wp["u_cam_xz"].value = (float(cam[0]), float(cam[2]))
            wp["u_cam_pos"].value = tuple(float(v) for v in cam)
            wp["u_screen"].value = (float(w), float(h))
            wp["u_near"].value = 0.05
            wp["u_far"].value = 420.0
            wp["u_time"].value = float(self.time)
            wp["u_sun_dir"].value = tuple(float(v) for v in SUN_DIR)
            wp["u_sun_color"].value = (1.0, 0.86, 0.68)
            wp["u_sun_intensity"].value = 3.2  # Azure Water default sunlight intensity
            wp["u_deep_color"].value = (0.012, 0.075, 0.14)
            wp["u_absorb"].value = (0.36, 0.10, 0.055)
            wp["u_foam_threshold"].value = 0.625
            wp["u_foam_amount"].value = float(WATER_SETTINGS["foam_amount"])
            wp["u_detail_amp"].value = float(WATER_SETTINGS["detail_strength"])
            wp["u_roughness"].value = float(WATER_SETTINGS["roughness"])
            wp["u_refl_distort"].value = 0.0018
            wp["u_refract_distort"].value = 0.008
            wp["u_fog_k"].value = 0.0045
            wp["u_fog_end"].value = 560.0
            wind = np.array([0.78, 0.62], dtype=np.float32)
            wind /= max(float(np.linalg.norm(wind)), 1e-6)
            wp["u_wind_dir"].value = (float(wind[0]), float(wind[1]))
            lambdas = np.array([64.0, 41.0, 26.0, 16.5, 10.5, 6.7, 4.3, 2.8], dtype=np.float32) * WATER_SETTINGS["wave_spacing"]
            ks = 2.0 * math.pi / lambdas
            amps = 0.22 * (lambdas / lambdas[0]) ** 0.85 * WATER_SETTINGS["wave_strength"]
            amps[WATER_SETTINGS["wave_count"]:] = 0.0
            angles = math.atan2(float(wind[0]), float(wind[1])) + np.radians(np.linspace(-26.0, 26.0, 8))
            dirs = np.stack((np.sin(angles), np.cos(angles)), axis=1).astype(np.float32)
            omegas = np.sqrt(9.81 * ks) * WATER_SETTINGS["wave_speed"]
            qs = np.zeros_like(amps)
            np.divide(0.85, ks * amps * 8.0, out=qs, where=amps > 1e-6)
            qs = np.minimum(qs, 1.0)
            wp["u_wave_dir"].write(dirs.tobytes())
            wp["u_wave_k"].write(ks.astype(np.float32).tobytes())
            wp["u_wave_amp"].write(amps.astype(np.float32).tobytes())
            wp["u_wave_q"].write(qs.astype(np.float32).tobytes())
            wp["u_wave_omega"].write(omegas.astype(np.float32).tobytes())
            wp["u_amp_total"].value = float(amps.sum())

            self.water_scene_tex.use(0)
            self.water_scene_depth.use(1)
            self.water_refl_tex.use(2)
            wp["u_scene"].value = 0
            wp["u_scene_depth"].value = 1
            wp["u_refl"].value = 2
            ctx.enable(moderngl.DEPTH_TEST)
            ctx.disable(moderngl.BLEND)
            ctx.depth_mask = False
            ctx.disable(moderngl.CULL_FACE)
            for mesh in water_surfaces:
                key = id(mesh)
                vao = self.azure_water_vaos.get(key)
                if vao is None:
                    vao = ctx.vertex_array(
                        wp, [(mesh.vbo, "3f 12x 1f", "in_pos", "in_flex")],
                        index_buffer=self.quad_ibo)
                    self.azure_water_vaos[key] = vao
                vao.render(moderngl.TRIANGLES, vertices=mesh.count)
            ctx.depth_mask = True
            ctx.enable(moderngl.CULL_FACE)

        if "u_anim_mode" in prog:
            prog["u_anim_mode"].value = 0

        # Legacy blocky cloud geometry is intentionally not rendered; the
        # Azure Water procedural sky shader supplies animated layered clouds.

        # Remote players (simple blocky avatars + screen-space name tags).
        self.remote_labels = []
        if game.remote_players:
            ctx.enable(moderngl.DEPTH_TEST)
            ctx.disable(moderngl.CULL_FACE)
            ctx.depth_mask = True
            self.solid_prog["u_vp"].write(vp_bytes)
            for rp in game.remote_players.values():
                if not rp.has_pos:
                    continue
                x, y, z = (float(rp.pos[0]), float(rp.pos[1]),
                           float(rp.pos[2]))
                if (x - cam[0]) ** 2 + (z - cam[2]) ** 2 > 160.0 ** 2:
                    continue
                player_skin = rp.skin_tex
                if player_skin is not None:
                    player_skin.use(0)
                    self.skin_prog["u_vp"].write(vp_bytes)
                    # Render classic block body/head/arms/legs using the supplied PNG.
                    parts = (
                        ("head", (x, y + 1.50, z), (0.50, 0.50, 0.50)),
                        ("torso", (x, y + 0.88, z), (0.50, 0.75, 0.25)),
                        ("arm", (x - 0.38, y + 0.88, z), (0.25, 0.75, 0.25)),
                        ("arm", (x + 0.38, y + 0.88, z), (0.25, 0.75, 0.25)),
                        ("leg", (x - 0.13, y + 0.25, z), (0.25, 0.75, 0.25)),
                        ("leg", (x + 0.13, y + 0.25, z), (0.25, 0.75, 0.25)),
                    )
                    for part, center, scale in parts:
                        self.skin_prog["u_center"].value = center
                        self.skin_prog["u_scale"].value = scale
                        self.skin_meshes[part].render(moderngl.TRIANGLES)
                else:
                    self.solid_prog["u_color"].value = rp.color
                    self.solid_prog["u_center"].value = (x, y + 0.42, z)
                    self.solid_prog["u_scale"].value = (0.52, 0.84, 0.32)
                    self.solid_vao.render(moderngl.TRIANGLES)
                    self.solid_prog["u_center"].value = (x, y + 1.12, z)
                    self.solid_prog["u_scale"].value = (0.62, 0.62, 0.38)
                    self.solid_vao.render(moderngl.TRIANGLES)
                    self.solid_prog["u_center"].value = (x, y + 1.64, z)
                    self.solid_prog["u_scale"].value = (0.50, 0.50, 0.50)
                    self.solid_vao.render(moderngl.TRIANGLES)

                clip = vp @ np.array([x, y + 2.18, z, 1.0], dtype=np.float32)
                if clip[3] > 0.05:
                    ndc = clip[:3] / clip[3]
                    sx = int((float(ndc[0]) * 0.5 + 0.5) * w)
                    sy = int((1.0 - (float(ndc[1]) * 0.5 + 0.5)) * h)
                    if -300 < sx < w + 300 and -100 < sy < h + 100:
                        self.remote_labels.append((rp.name, sx, sy))
            ctx.enable(moderngl.CULL_FACE)

        # Local player in third-person view.
        if game.state == "playing" and getattr(game, "third_person", False):
            x, y, z = (float(game.player.pos[0]), float(game.player.pos[1]),
                      float(game.player.pos[2]))
            ctx.enable(moderngl.DEPTH_TEST)
            ctx.disable(moderngl.CULL_FACE)
            ctx.depth_mask = True
            if self.skin_tex is not None:
                self.skin_tex.use(0)
                self.skin_prog["u_vp"].write(vp_bytes)
                self.skin_prog["u_yaw"].value = float(game.player.yaw) + math.pi
                yaw = float(game.player.yaw) + math.pi
                c = math.cos(yaw); s = math.sin(yaw)
                def rot(cx, cy, cz):
                    dx = cx - x; dz = cz - z
                    return (x + dx * c + dz * s, cy, z - dx * s + dz * c)
                parts = (
                    ("head", rot(x, y + 1.50, z), (0.50, 0.50, 0.50)),
                    ("torso", rot(x, y + 0.88, z), (0.50, 0.75, 0.25)),
                    ("arm", rot(x - 0.38, y + 0.88, z), (0.25, 0.75, 0.25)),
                    ("arm", rot(x + 0.38, y + 0.88, z), (0.25, 0.75, 0.25)),
                    ("leg", rot(x - 0.13, y + 0.25, z), (0.25, 0.75, 0.25)),
                    ("leg", rot(x + 0.13, y + 0.25, z), (0.25, 0.75, 0.25)),
                )
                for part, center, scale in parts:
                    self.skin_prog["u_center"].value = center
                    self.skin_prog["u_scale"].value = scale
                    self.skin_meshes[part].render(moderngl.TRIANGLES)
            ctx.enable(moderngl.CULL_FACE)

        # Targeted block outline.
        if game.state == "playing" and game.target is not None:
            pos = game.target[0]
            ctx.enable(moderngl.BLEND)
            ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA)
            ctx.disable(moderngl.CULL_FACE)
            ctx.depth_mask = False
            self.line_prog["u_vp"].write(vp_bytes)
            self.line_prog["u_center"].value = (pos[0] + 0.5, pos[1] + 0.5,
                                                pos[2] + 0.5)
            self.line_prog["u_color"].value = (0.02, 0.02, 0.02, 0.75)
            try:
                ctx.line_width = 2.0
            except Exception:
                pass
            self.line_vao.render(moderngl.LINES)
            ctx.depth_mask = True
            ctx.disable(moderngl.BLEND)
            ctx.enable(moderngl.CULL_FACE)

    # -- immediate UI helpers ----------------------------------------------

    def rect_now(self, x, y, w, h, color):
        pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
        self._scratch_quad(pts, [(0.0, 0.0)] * 4, color, 0)

    # -- screens ------------------------------------------------------------

    def draw_button(self, x, y, w, h, label, key):
        hover = pygame.Rect(x, y, w, h).collidepoint(pygame.mouse.get_pos())
        bg = col(74, 74, 74, 225) if hover else col(34, 34, 34, 200)
        border = col(255, 255, 255, 220) if hover else col(145, 145, 145, 190)
        self.rect(x, y, w, h, bg)
        self.outline(x, y, w, h, 2, border)
        self.rect(x + 2, y + 2, w - 4, 2, col(255, 255, 255, 55))
        self.text(label, x + w // 2, y + (h - 16) // 2, scale=2,
                  align="center")
        self.hotspots[key] = pygame.Rect(x, y, w, h)

    def draw_menu(self, game: "Game") -> None:
        w, h = self.width, self.height
        if self.panorama_tex is not None:
            t = self.time
            zoom = 1.045 + 0.012 * math.sin(t * 0.055)
            scale = max(w / 1024.0, h / 1024.0) * zoom
            dw, dh = 1024 * scale, 1024 * scale
            px = (w - dw) * 0.5 + math.sin(t * 0.047) * 18
            py = (h - dh) * 0.5 + math.cos(t * 0.038) * 12
            self.texture_quad(self.panorama_tex, px, py, dw, dh)
            self.rect_now(0, 0, w, h, col(0, 0, 0, 62))
        else:
            self.rect_now(0, 0, w, h, col(55, 85, 130))
            for i in range(18):
                c = col(55 + i * 3, 85 + i * 5, 130 + i * 5, 255)
                self.rect_now(0, h * i / 18, w, h / 18 + 1, c)
            self.rect_now(0, 0, w, h, col(0, 0, 0, 55))

        if self.title_tex is not None:
            tw = min(int(w * 0.62), 820)
            th = int(tw * self.title_size[1] / self.title_size[0])
            tx = (w - tw) // 2
            ty = int(h * 0.055)
            self.texture_quad(self.title_tex, tx, ty, tw, th)
            logo_bottom = ty + int(th * 0.70)
        else:
            self.text("PYCRAFT", w // 2, int(h * 0.13), scale=8,
                      align="center")
            logo_bottom = int(h * 0.13) + 66
        self.text("PYTHON EDITION", w // 2, logo_bottom + 4, scale=2,
                  color=col(255, 240, 80), align="center")
        self.text("REAL MINECRAFT BLOCK TEXTURES", w // 2, logo_bottom + 32,
                  scale=2, color=col(210, 220, 230), align="center")

        bw = min(440, int(w * 0.38))
        bh = 52
        bx = (w - bw) // 2
        by = int(h * 0.50)
        self.draw_button(bx, by, bw, bh, "SINGLEPLAYER", "play")
        self.draw_button(bx, by + bh + 14, bw, bh, "MULTIPLAYER", "multiplayer")
        self.draw_button(bx, by + (bh + 14) * 2, bw, bh, "QUIT GAME", "quit")

        self.text("WASD MOVE   SPACE JUMP   SHIFT SPRINT   F FLY",
                  w // 2, h - 76, scale=2, align="center",
                  color=col(225, 225, 225))
        self.text("LMB BREAK   RMB PLACE   E INVENTORY   T CHAT   ESC PAUSE",
                  w // 2, h - 50, scale=2, align="center",
                  color=col(225, 225, 225))
        self.text(f"PyCraft  -  {N_BLOCKS} blocks  -  {N_ITEMS} items  -  "
                  f"real Assets textures",
                  w - 18, 14, scale=1, align="right", shadow=True,
                  color=col(235, 235, 235, 200))

    def draw_world_select(self, game: "Game") -> None:
        w, h = self.width, self.height
        self.rect_now(0, 0, w, h, col(10, 16, 24, 235))
        self.text("SELECT WORLD", w // 2, 54, scale=6, align="center")
        self.text("YOUR WORLDS", w // 2, 112, scale=2, align="center",
                  color=col(190, 220, 245))
        worlds = game.list_saved_worlds()
        bw, bh = min(680, w - 100), 62
        bx = (w - bw) // 2
        by = 158
        visible = worlds[:6]
        if not visible:
            self.text("No worlds yet. Create your first world!", w // 2, 250,
                      scale=2, align="center", color=col(205, 215, 225))
        for i, item in enumerate(visible):
            yy = by + i * (bh + 10)
            delete_w = 104
            self.draw_button(bx, yy, bw - delete_w - 10, bh,
                             f"{item['name']}   |   SEED {item['seed']}", f"world:{i}")
            self.draw_button(bx + bw - delete_w, yy, delete_w, bh,
                             "DELETE", f"world_delete:{i}")
        create_y = min(h - 118, by + max(1, len(visible)) * (bh + 10) + 12)
        self.draw_button(bx, create_y, bw, 50, "CREATE NEW WORLD", "create_world")
        self.draw_button(bx, create_y + 62, bw, 44, "BACK", "world_back")
        if game.world_status:
            self.text(game.world_status, w // 2, h - 20, scale=1,
                      align="center", color=col(255, 150, 130))

    def draw_delete_world_confirm(self, game: "Game") -> None:
        w, h = self.width, self.height
        self.rect_now(0, 0, w, h, col(0, 0, 0, 205))
        pw, ph = 560, 220
        px, py = (w - pw) // 2, (h - ph) // 2
        self.rect(px, py, pw, ph, col(28, 31, 38, 250))
        self.outline(px, py, pw, ph, 2, col(210, 100, 90, 240))
        self.text("DELETE WORLD?", w // 2, py + 34, scale=4, align="center",
                  color=col(255, 190, 175))
        self.text(game.delete_world_name, w // 2, py + 94, scale=2, align="center")
        self.text("This permanently deletes the world save.", w // 2, py + 124,
                  scale=1, align="center", color=col(210, 215, 225))
        self.draw_button(px + 35, py + 160, 225, 42, "DELETE WORLD", "delete_confirm_yes")
        self.draw_button(px + 300, py + 160, 225, 42, "CANCEL", "delete_confirm_no")

    def draw_host_world_select(self, game: "Game") -> None:
        w, h = self.width, self.height
        self.rect_now(0, 0, w, h, col(10, 16, 24, 242))
        self.text("CHOOSE HOST WORLD", w // 2, 64, scale=5, align="center")
        self.text("Select a saved world for your multiplayer server", w // 2, 122,
                  scale=2, align="center", color=col(190, 220, 245))
        worlds = game.list_saved_worlds()
        bw, bh = min(650, w - 100), 58
        bx, by = (w - bw) // 2, 170
        visible = worlds[:6]
        if not visible:
            self.text("No saved worlds. Create one first.", w // 2, 260,
                      scale=2, align="center", color=col(220, 220, 220))
        for i, item in enumerate(visible):
            yy = by + i * (bh + 9)
            marker = "  [SELECTED]" if game.selected_host_world == item["path"] else ""
            self.draw_button(bx, yy, bw, bh,
                             f"{item['name']}   |   SEED {item['seed']}{marker}",
                             f"host_world:{i}")
        bottom = min(h - 112, by + max(1, len(visible)) * (bh + 9) + 12)
        self.draw_button(bx, bottom, bw, 44, "CREATE A WORLD", "host_world_create")
        self.draw_button(bx, bottom + 54, bw, 40, "BACK", "host_world_back")

    def draw_create_world(self, game: "Game") -> None:
        w, h = self.width, self.height
        self.rect_now(0, 0, w, h, col(10, 16, 24, 240))
        self.text("CREATE NEW WORLD", w // 2, 100, scale=5, align="center")
        pw, ph = 650, 340
        px, py = (w - pw) // 2, 205
        self.rect(px, py, pw, ph, col(24, 29, 37, 235))
        self.outline(px, py, pw, ph, 2, col(135, 155, 175, 220))
        self.text("WORLD NAME", px + 35, py + 35, scale=2)
        self.rect(px + 32, py + 66, pw - 64, 48, col(8, 12, 18, 245))
        self.outline(px + 32, py + 66, pw - 64, 48, 2,
                     col(255, 220, 90) if game.world_form_focus == "name" else col(100, 115, 130))
        self.text(game.world_name_input + ("_" if game.world_form_focus == "name" else ""),
                  px + 46, py + 82, scale=2)
        self.hotspots["world_name"] = pygame.Rect(px + 32, py + 66, pw - 64, 48)
        self.text("SEED (LEAVE EMPTY FOR RANDOM)", px + 35, py + 137, scale=2)
        self.rect(px + 32, py + 168, pw - 64, 48, col(8, 12, 18, 245))
        self.outline(px + 32, py + 168, pw - 64, 48, 2,
                     col(255, 220, 90) if game.world_form_focus == "seed" else col(100, 115, 130))
        self.text(game.world_seed_input + ("_" if game.world_form_focus == "seed" else ""),
                  px + 46, py + 184, scale=2)
        self.hotspots["world_seed"] = pygame.Rect(px + 32, py + 168, pw - 64, 48)
        self.text("TAB TO SWITCH FIELDS", w // 2, py + 232, scale=1,
                  align="center", color=col(175, 190, 205))
        self.draw_button(px + 32, py + 270, 280, 48, "CREATE WORLD", "world_create")
        self.draw_button(px + 338, py + 270, 280, 48, "CANCEL", "world_cancel")
        if game.world_status:
            self.text(game.world_status, w // 2, h - 34, scale=1,
                      align="center", color=col(255, 145, 125))

    def draw_multiplayer(self, game: "Game") -> None:
        w, h = self.width, self.height
        if self.panorama_tex is not None:
            self.texture_quad(self.panorama_tex, 0, 0, w, h)
            self.rect_now(0, 0, w, h, col(0, 0, 0, 150))
        else:
            self.rect_now(0, 0, w, h, col(32, 46, 66))
            self.rect_now(0, 0, w, h, col(0, 0, 0, 80))
        self.text("MULTIPLAYER", w // 2, 64, scale=6, align="center")
        self.text("LAN WORLD  -  HOST OR JOIN", w // 2, 132, scale=2,
                  align="center", color=col(190, 235, 255))

        pw, ph = 640, 370
        px = (w - pw) // 2
        py = 190
        self.rect(px, py, pw, ph, col(22, 24, 28, 225))
        self.outline(px, py, pw, ph, 2, col(160, 170, 185, 210))
        self.rect(px + 2, py + 2, pw - 4, 2, col(255, 255, 255, 40))

        self.draw_button(px + 28, py + 28, 272, 54, "HOST GAME", "host")
        self.draw_button(px + 340, py + 28, 272, 54, "JOIN GAME", "join")

        self.text("SERVER ADDRESS", px + 28, py + 108, scale=2,
                  color=col(205, 215, 225))
        field = pygame.Rect(px + 28, py + 134, pw - 56, 44)
        self.rect(field.x, field.y, field.w, field.h, col(12, 14, 18, 235))
        border = col(255, 235, 90, 240) if game.mp_focus else \
            col(130, 140, 155, 210)
        self.outline(field.x, field.y, field.w, field.h, 2, border)
        shown = game.mp_address + ("_" if game.mp_focus else "")
        self.text(shown or "_", field.x + 12, field.y + 12, scale=2,
                  color=col(240, 245, 250), shadow=False)
        self.hotspots["address"] = field

        # Name field.
        self.text("PLAYER NAME", px + 28, py + 196, scale=2,
                  color=col(205, 215, 225))
        name_field = pygame.Rect(px + 28, py + 222, pw - 56, 40)
        self.rect(name_field.x, name_field.y, name_field.w, name_field.h,
                  col(12, 14, 18, 235))
        border = col(255, 235, 90, 240) if game.mp_name_focus else \
            col(130, 140, 155, 210)
        self.outline(name_field.x, name_field.y, name_field.w, name_field.h, 2,
                     border)
        self.text(game.name + ("_" if game.mp_name_focus else ""),
                  name_field.x + 12, name_field.y + 10, scale=2,
                  color=col(240, 245, 250), shadow=False)
        self.hotspots["name"] = name_field

        # Skin preview.
        if self.skin_tex is not None:
            self.text("SKIN (skin.png)", px + pw - 150, py + 196, scale=2,
                      color=col(205, 215, 225))
            self.texture_quad(self.skin_tex, px + pw - 150, py + 222, 120, 120)

        info_y = py + 270
        self.text(f"YOUR LAN IP  {local_ip()}    PORT  {DEFAULT_PORT}",
                  px + 28, info_y, scale=2, color=col(190, 200, 215))
        self.text("JOIN FORMAT  ip:port   (default port 25565)",
                  px + 28, info_y + 24, scale=1, color=col(175, 185, 200))
        pass

        if game.mp_status:
            status_col = (col(255, 130, 120) if "failed" in game.mp_status.lower()
                          or "could not" in game.mp_status.lower()
                          else col(180, 255, 160))
            self.text(game.mp_status, px + 28, py + 282, scale=2,
                      color=status_col)

        self.draw_button(px + 28, py + 310, 170, 42, "BACK", "back")
        self.text("T = CHAT   ESC = BACK", px + pw - 28, py + 324,
                  scale=1, align="right", color=col(200, 205, 215))
        self.text("The host owns the world; blocks, chat and players sync live.",
                  w // 2, h - 52, scale=2, align="center",
                  color=col(225, 230, 240))

    def draw_hotbar(self, game: "Game") -> None:
        w, h = self.width, self.height
        slot = 54
        bar_w = slot * 9 + 8
        x0 = (w - bar_w) // 2
        y0 = h - slot - 22
        self.rect(x0, y0, bar_w, slot + 8, col(0, 0, 0, 118))
        self.outline(x0, y0, bar_w, slot + 8, 1, col(255, 255, 255, 45))
        for i, block_id in enumerate(game.hotbar):
            sx = x0 + 4 + i * slot
            sy = y0 + 4
            self.rect(sx, sy, slot, slot, col(25, 25, 25, 115))
            if i == game.slot:
                self.outline(sx, sy, slot, slot, 3, col(255, 255, 255, 235))
            else:
                self.outline(sx, sy, slot, slot, 1, col(255, 255, 255, 45))
            self.draw_entry_icon(block_id, sx + 7, sy + 6, slot - 14)
            self.text(str(i + 1), sx + 4, sy + 2, scale=1,
                      color=col(235, 235, 235, 170), shadow=True)
        label = entry_label(game.hotbar[game.slot])
        self.text(label, w // 2, y0 - 25, scale=2, align="center")
        if game.toast_timer > 0.0 and game.toast:
            self.text(game.toast, w // 2, y0 - 51, scale=2, align="center",
                      color=col(205, 255, 170))

    def draw_crosshair(self) -> None:
        cx, cy = self.width // 2, self.height // 2
        self.rect(cx - 11, cy - 2, 22, 4, col(0, 0, 0, 150))
        self.rect(cx - 2, cy - 11, 4, 22, col(0, 0, 0, 150))
        self.rect(cx - 9, cy - 1, 18, 2, col(255, 255, 255, 235))
        self.rect(cx - 1, cy - 9, 2, 18, col(255, 255, 255, 235))

    def draw_debug(self, game: "Game") -> None:
        p = game.player
        quads = sum(m.count for layers in game.world.meshes.values()
                    for m in layers.values()) // 6
        target_name = "-"
        if game.target is not None:
            target_name = BLOCKS[game.target[2]].label
        net_line = "Singleplayer"
        if game.net is not None:
            role = "HOST" if game.net.is_host else "CLIENT"
            net_line = (f"{role}  {len(game.remote_players) + 1} players  "
                        f"{'connected' if game.net.connected else 'offline'}")
        lines = [
            f"PyCraft  {game.last_fps:5.1f} FPS",
            f"XYZ  {p.pos[0]:.2f} / {p.pos[1]:.2f} / {p.pos[2]:.2f}",
            f"Chunk  {int(p.pos[0]) // CHUNK}, {int(p.pos[2]) // CHUNK}",
            f"Faces  {quads}   Chunks  {getattr(game, 'drawn_chunks', 0)}"
            f"/{len(game.world.meshes)}",
            f"Target  {target_name}",
            f"Fly  {'ON' if p.fly else 'OFF'}   Water  {'YES' if p.in_water else 'NO'}",
            f"Net  {net_line}",
            f"Content  {N_BLOCKS} blocks  /  {N_ITEMS} items",
        ]
        bw, bh = 390, len(lines) * 18 + 18
        self.rect(8, 8, bw, bh, col(0, 0, 0, 150))
        self.outline(8, 8, bw, bh, 1, col(255, 255, 255, 40))
        for i, line in enumerate(lines):
            self.text(line, 18, 16 + i * 18, scale=2,
                      color=col(235, 240, 245))

    def draw_playing_hud(self, game: "Game") -> None:
        w, h = self.width, self.height
        if game.player.underwater:
            self.rect(0, 0, w, h, col(18, 65, 145, 62))

        # Remote player name tags (positions come from draw_world).
        for name, sx, sy in game.remote_labels:
            tw = self.measure_text(name, 2)
            self.rect(sx - tw // 2 - 4, sy - 2, tw + 8, 20, col(0, 0, 0, 120))
            self.text(name, sx, sy, scale=2, align="center",
                      color=col(255, 255, 255))

        # Chat log.
        if game.chat_messages:
            shown = game.chat_messages[-8:]
            base_y = h - 222
            for i, (name, text, ttl) in enumerate(shown):
                line = f"<{name}> {text}"
                alpha = int(255 * max(0.0, min(1.0, ttl / 2.0)))
                if name == "System":
                    line = text
                tw = self.measure_text(line, 2)
                self.rect(10, base_y + i * 20, min(tw + 10, w // 2),
                          18, col(0, 0, 0, int(alpha * 0.45)))
                self.text(line, 15, base_y + i * 20, scale=2,
                          color=col(235, 240, 245, alpha))

        # Held item / block in the lower-right corner.
        entry = game.hotbar[game.slot]
        bob = math.sin(game.player.walk_phase) * 5.0
        self.draw_entry_icon(entry, w - 154, h - 170 + bob, 118)
        self.text(entry_label(entry), w - 20, h - 44, scale=1, align="right",
                  color=col(235, 240, 245, 210))

        self.draw_hotbar(game)
        if game.chat_open:
            bw = min(620, w - 80)
            bx = (w - bw) // 2
            by = h - 146
            self.rect(bx, by, bw, 34, col(0, 0, 0, 195))
            self.outline(bx, by, bw, 34, 2, col(255, 235, 90, 220))
            self.text("> " + game.chat_text + "_", bx + 10, by + 9,
                      scale=2, color=col(255, 255, 255), shadow=False)
            self.text("ENTER SEND   ESC CANCEL", bx + bw - 10, by - 18,
                      scale=1, align="right", color=col(210, 215, 225))
        self.draw_crosshair()
        if game.debug:
            self.draw_debug(game)

    def draw_pause(self, game: "Game") -> None:
        w, h = self.width, self.height
        self.rect(0, 0, w, h, col(0, 0, 0, 155))
        self.text("GAME PAUSED", w // 2, int(h * 0.24), scale=5,
                  align="center")
        bw = min(430, int(w * 0.37))
        bh = 52
        bx = (w - bw) // 2
        by = int(h * 0.41)
        self.draw_button(bx, by, bw, bh, "BACK TO GAME", "resume")
        self.draw_button(bx, by + (bh + 14), bw, bh, "QUIT TO TITLE", "title")
        self.draw_button(bx, by + (bh + 14) * 2, bw, bh, "QUIT GAME", "quit")
        if game.net is not None:
            role = "HOST" if game.net.is_host else "CLIENT"
            self.text(f"Multiplayer {role}  -  "
                      f"{len(game.remote_players) + 1} players  -  T chat",
                      w // 2, h - 70, scale=2, align="center",
                      color=col(180, 225, 255))
        self.text("AUTOSAVE ENABLED  -  YOUR WORLD IS SAVED AUTOMATICALLY",
                  w // 2, h - 42, scale=2, align="center",
                  color=col(160, 220, 170))

    def draw_inventory(self, game: "Game") -> None:
        w, h = self.width, self.height
        self.rect(0, 0, w, h, col(0, 0, 0, 165))
        cell = INV_CELL
        cols, rows = INV_COLS, INV_ROWS
        grid_w = cols * cell
        grid_h = rows * cell
        panel_w = grid_w + 30
        panel_h = grid_h + 154
        px = (w - panel_w) // 2
        py = max(28, (h - panel_h) // 2 - 8)
        self.rect(px, py, panel_w, panel_h, col(28, 28, 28, 240))
        self.outline(px, py, panel_w, panel_h, 2, col(175, 175, 175, 220))
        self.rect(px + 2, py + 2, panel_w - 4, 2, col(255, 255, 255, 45))
        self.text("CREATIVE INVENTORY", px + panel_w // 2, py + 10,
                  scale=2, align="center")
        self.text("E / ESC TO CLOSE", px + panel_w - 12, py + 12,
                  scale=1, align="right", color=col(205, 205, 205))

        tab_y = py + 36
        for i, (label, key) in enumerate((("BLOCKS", "inv_blocks"),
                                          ("ITEMS", "inv_items"))):
            tx = px + 15 + i * 148
            tw = 138
            active = game.inv_tab == i
            bg = col(80, 130, 190, 230) if active else col(48, 48, 52, 220)
            self.rect(tx, tab_y, tw, 26, bg)
            self.outline(tx, tab_y, tw, 26, 2,
                         col(255, 255, 255, 210) if active
                         else col(110, 110, 115, 180))
            self.text(label, tx + tw // 2, tab_y + 5, scale=2, align="center")
            self.hotspots[key] = pygame.Rect(tx, tab_y, tw, 26)

        entries = inventory_entries(game.inv_tab)
        per_page = cols * rows
        pages = inventory_page_count(game.inv_tab)
        game.inv_page = max(0, min(pages - 1, game.inv_page))
        start = game.inv_page * per_page
        page_entries = entries[start:start + per_page]

        gx = px + 15
        gy = py + 74
        hovered = None
        mouse = pygame.mouse.get_pos()
        selected = game.hotbar[game.slot]
        for i, entry in enumerate(page_entries):
            cx = gx + (i % cols) * cell
            cy = gy + (i // cols) * cell
            sr = pygame.Rect(cx + 2, cy + 2, cell - 4, cell - 4)
            self.rect(sr.x, sr.y, sr.w, sr.h, col(55, 55, 55, 150))
            self.outline(sr.x, sr.y, sr.w, sr.h, 1, col(20, 20, 20, 210))
            if sr.collidepoint(mouse):
                self.outline(sr.x, sr.y, sr.w, sr.h, 2, col(255, 255, 255, 235))
                hovered = entry
            if entry == selected:
                self.outline(sr.x - 1, sr.y - 1, sr.w + 2, sr.h + 2, 1,
                             col(255, 235, 90, 210))
            self.draw_entry_icon(entry, sr.x + 6, sr.y + 5, sr.w - 12)
            self.inventory_cells.append((sr, entry))

        bottom = gy + grid_h + 8
        self.draw_button(px + 15, bottom, 46, 30, "<", "inv_prev")
        self.draw_button(px + panel_w - 61, bottom, 46, 30, ">", "inv_next")
        tab_name = "BLOCKS" if game.inv_tab == 0 else "ITEMS"
        self.text(f"{tab_name}  {game.inv_page + 1}/{pages}   "
                  f"({len(entries)} total)", px + panel_w // 2, bottom + 8,
                  scale=2, align="center", color=col(205, 220, 235))
        if hovered is not None:
            label = entry_label(hovered)
        else:
            label = "Click an entry to put it in the selected slot"
        self.text(label, px + panel_w // 2, bottom + 36, scale=2,
                  align="center", color=col(255, 245, 190))
        self.text("TAB SWITCH   WHEEL / ARROWS PAGE", px + panel_w // 2,
                  bottom + 58, scale=1, align="center",
                  color=col(190, 195, 205))
        self.draw_hotbar(game)

    def draw_loading(self, progress: float, message: str) -> None:
        w, h = self.width, self.height
        self.ctx.viewport = (0, 0, w, h)
        self.ctx.clear(0.16, 0.28, 0.42, 1.0)
        self._begin_ui()
        for i in range(24):
            t = i / 23.0
            c = col(int(35 + 45 * t), int(65 + 55 * t), int(105 + 55 * t))
            self.rect(0, h * i / 24, w, h / 24 + 1, c)
        self.rect(0, 0, w, h, col(0, 0, 0, 45))
        self.text("PYCRAFT", w // 2, int(h * 0.26), scale=8, align="center")
        self.text("PYTHON EDITION", w // 2, int(h * 0.26) + 72, scale=2,
                  align="center", color=col(255, 238, 90))
        bw = 470
        bx = (w - bw) // 2
        by = int(h * 0.56)
        self.rect(bx, by, bw, 18, col(0, 0, 0, 165))
        self.outline(bx, by, bw, 18, 2, col(210, 210, 210, 200))
        fill = int((bw - 4) * max(0.0, min(1.0, progress)))
        if fill > 0:
            self.rect(bx + 2, by + 2, fill, 14, col(120, 210, 110))
        self.text(message, w // 2, by + 28, scale=2, align="center")
        self.text(f"{int(progress * 100)}%", w // 2, by + 50, scale=2,
                  align="center", color=col(255, 255, 255, 200))
        self._flush_ui()
        pygame.display.flip()
        pygame.event.pump()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                raise SystemExit

    # -- frame dispatch -----------------------------------------------------

    def draw(self, game: "Game") -> None:
        # Use elapsed time, not the large absolute performance-counter value.
        # This preserves float precision in GLSL sin/cos animation inputs.
        self.time = time.perf_counter() - self.start_time
        if game.state in ("menu", "multiplayer", "world_select", "create_world",
                          "delete_world_confirm", "host_world_select"):
            self.ctx.viewport = (0, 0, self.width, self.height)
            self.ctx.clear(0.10, 0.16, 0.24, 1.0)
            self._begin_ui()
            if game.state == "menu":
                self.draw_menu(game)
            elif game.state == "multiplayer":
                self.draw_multiplayer(game)
            elif game.state == "world_select":
                self.draw_world_select(game)
            elif game.state == "create_world":
                self.draw_create_world(game)
            elif game.state == "delete_world_confirm":
                self.draw_delete_world_confirm(game)
            else:
                self.draw_host_world_select(game)
            self._flush_ui()
            return
        self.draw_world(game)
        self._begin_ui()
        if game.state == "playing":
            self.draw_playing_hud(game)
        elif game.state == "paused":
            self.draw_pause(game)
        elif game.state == "inventory":
            self.draw_inventory(game)
        self._flush_ui()


# ----------------------------------------------------------------------------
# Self test / main
# ----------------------------------------------------------------------------

def _worker_count() -> int:
    return max(2, min(8, (os.cpu_count() or 4)))


def selftest(seed: int) -> None:
    print(f"PyCraft selftest - seed {seed}")
    print(f"  Assets: {ASSET_DIR}")
    print(f"  Textures packed: {len(TEX.tiles)} tiles, atlas {ATLAS_IMAGE.shape[1]}x{ATLAS_IMAGE.shape[0]}")
    print(f"  Blocks: {N_BLOCKS} ({len(PLACEABLE)} placeable)")
    if TEX.warnings:
        print("  WARNINGS: " + ", ".join(TEX.warnings))
    world = World(seed)
    t0 = time.perf_counter()
    world.generate()
    t1 = time.perf_counter()
    sx, sy, sz = world.spawn
    below = world.get(int(sx), int(sy) - 1, int(sz))
    print(f"  World generated in {t1 - t0:.2f}s, size {WX}x{WY}x{WZ}")
    print(f"  Spawn {sx:.1f}/{sy:.1f}/{sz:.1f}, ground={BLOCKS[below].label}")

    total_faces = 0
    total_verts = 0
    t0 = time.perf_counter()
    coords = [(cx, cz) for cx in range(WX // CHUNK) for cz in range(WZ // CHUNK)]
    with ThreadPoolExecutor(max_workers=_worker_count()) as ex:
        for arrays, faces, _ymax in ex.map(lambda c: world.mesh_arrays(*c), coords):
            total_faces += faces
            total_verts += sum(a.shape[0] for a in arrays.values())
    t1 = time.perf_counter()
    print(f"  Meshed {len(coords)} chunks in {t1 - t0:.2f}s ({_worker_count()} threads)")
    print(f"  Faces: {total_faces}, vertices: {total_verts} (indexed quads)")
    if total_faces < 1000:
        raise SystemExit("selftest failed: too few faces")

    player = Player(world)
    hit = world.raycast(player.eye_pos(), np.array([0.0, -1.0, 0.0]), 5.0)
    print(f"  Down raycast: {hit}")
    if hit is None:
        raise SystemExit("selftest failed: no block under spawn")
    for _ in range(120):
        player.update(1.0 / 60.0, 0.0, 0.0, False, False, False)
    print(f"  Physics settled at y={player.pos[1]:.3f}, on_ground={player.on_ground}")
    if not player.on_ground:
        raise SystemExit("selftest failed: player did not land")

    bx, by, bz = int(player.pos[0]) + 2, int(player.pos[1]) + 3, int(player.pos[2])
    world.set_block(bx, by, bz, GLOWSTONE)
    if world.get(bx, by, bz) != GLOWSTONE:
        raise SystemExit("selftest failed: set_block")
    if not world.break_block(bx, by, bz) or world.get(bx, by, bz) != AIR:
        raise SystemExit("selftest failed: break_block")
    print("  Build/break OK")

    # Frustum plane sanity check: a point straight ahead is inside, one
    # behind the camera is outside.
    cam = player.eye_pos()
    f = player.forward()
    up = normalize(np.cross(player.right(), f))
    vp = perspective(player.fov, 16 / 9, 0.05, 420.0) @ look_at(cam, cam + f, up)
    planes = frustum_planes(vp)

    def inside(p):
        return bool((planes[:, :3] @ p + planes[:, 3] >= 0).all())

    if not inside(cam + f * 10) or inside(cam - f * 10):
        raise SystemExit("selftest failed: frustum planes")
    print("  Frustum culling OK")
    print("SELFTEST OK")


def create_window():
    pygame.init()
    pygame.display.set_caption("PyCraft - Minecraft-style voxel sandbox")
    pygame.key.set_repeat(0)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK,
                                    pygame.GL_CONTEXT_PROFILE_CORE)
    pygame.display.gl_set_attribute(pygame.GL_DEPTH_SIZE, 24)
    pygame.display.gl_set_attribute(pygame.GL_DOUBLEBUFFER, 1)
    try:
        pygame.display.set_mode((WINDOW_W, WINDOW_H),
                                pygame.OPENGL | pygame.DOUBLEBUF, vsync=1)
    except Exception:
        pygame.display.set_mode((WINDOW_W, WINDOW_H),
                                pygame.OPENGL | pygame.DOUBLEBUF)
    ctx = moderngl.create_context()
    ctx.enable(moderngl.DEPTH_TEST | moderngl.CULL_FACE)
    fw, fh = ctx.screen.size
    return ctx, fw, fh


def main() -> None:
    parser = argparse.ArgumentParser(description="PyCraft - a single-file Minecraft-like voxel sandbox")
    parser.add_argument("--selftest", action="store_true",
                        help="validate assets, world generation, meshing and physics")
    parser.add_argument("--screenshot", metavar="FILE", default=None,
                        help="render a screenshot and exit")
    parser.add_argument("--record", metavar="FRAME_DIR", default=None,
                        help="render a short world video as numbered PNG frames")
    parser.add_argument("--record-seconds", type=int, default=10,
                        help="duration for --record (default: 10 seconds)")
    parser.add_argument("--scene", default="world",
                        choices=["world", "menu", "pause", "inventory"],
                        help="scene to use with --screenshot")
    parser.add_argument("--seed", type=int, default=2026, help="world seed")
    parser.add_argument("--coast-test", action="store_true", help="aim the test camera at the nearest beach")
    args = parser.parse_args()

    if args.selftest:
        selftest(args.seed)
        return

    os.environ.setdefault("SDL_VIDEO_CENTERED", "1")
    ctx, width, height = create_window()
    try:
        renderer = Renderer(ctx, width, height)
        renderer.draw_loading(0.02, "GENERATING TERRAIN")
        world = World(args.seed)
        world.generate()

        chunks = [(cx, cz) for cx in range(WX // CHUNK)
                  for cz in range(WZ // CHUNK)]
        total = len(chunks)
        last_ui = 0.0
        # Mesh on worker threads (numpy releases the GIL); GL upload stays on
        # the main thread.  Chunks near the spawn are meshed first.
        sx, _, sz = world.spawn
        chunks.sort(key=lambda c: (c[0] * CHUNK + 8 - sx) ** 2 +
                                  (c[1] * CHUNK + 8 - sz) ** 2)
        with ThreadPoolExecutor(max_workers=_worker_count()) as ex:
            futures = [ex.submit(world.mesh_arrays, cx, cz) for cx, cz in chunks]
            for i, ((cx, cz), fut) in enumerate(zip(chunks, futures)):
                world.upload_chunk(renderer, cx, cz, fut.result())
                futures[i] = None          # free the CPU-side arrays early
                now = time.perf_counter()
                if now - last_ui > 0.12 or i == total - 1:
                    progress = 0.10 + 0.90 * (i + 1) / total
                    renderer.draw_loading(progress,
                                          f"BUILDING CHUNKS  {i + 1}/{total}")
                    last_ui = now
        renderer.draw_loading(1.0, "READY")

        player = Player(world)
        if args.coast_test:
            # Seed-2026 shoreline test position: stand on the beach and face the sea.
            player.pos[:] = (98.5, 33.0, 93.5)
            player.yaw = math.pi / 2.0
            player.pitch = -0.24
            player.fly = True
        game = Game(renderer, world, player)
        if args.screenshot:
            game.auto_screenshot = args.screenshot
            game.auto_scene = args.scene
        if args.record:
            game.auto_record = args.record
            game.record_seconds = max(2, min(args.record_seconds, 30))
            game.auto_scene = args.scene
        game.run()
    finally:
        pygame.quit()


if __name__ == "__main__":
    main()
