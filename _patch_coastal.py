from pathlib import Path
p = Path(r"C:\Users\İlter\Desktop\PyCraft\app.py")
s = p.read_text(encoding="utf-8")
backup = p.with_name("app_before_coastal_physics_20261122.py")
if not backup.exists():
    backup.write_text(s, encoding="utf-8")

needle = "\n\nclass World:\n"
helper = r'''

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
        verts[:, :, 6] = d1
        parts.append(verts.reshape(-1, 7))
    return np.concatenate(parts, axis=0)
'''
if "_shore_wash_quads" not in s:
    s = s.replace(needle, helper + needle, 1)

s = s.replace(
"cube_parts, foliage_parts, water_parts, plant_parts, falling_leaf_parts = [], [], [], [], []",
"cube_parts, foliage_parts, water_parts, plant_parts, falling_leaf_parts, shore_parts = [], [], [], [], [], []", 1)

needle = "        # Sparse individual leaflets detach from the canopy and drift down.\n"
shore = r'''        # Build a shallow, animated swash sheet over beach sand blocks that
        # directly border the sea. The shader advances and retreats this sheet.
        water_cells = np.argwhere(water_src)
        if water_cells.size:
            for sdx, sdz in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                sea_mask = water_src[:, :, :] & (np.indices(water_src.shape)[1] == SEA_LEVEL)
                candidates = np.argwhere(sea_mask)
                if not len(candidates):
                    continue
                lx, ly, lz = candidates.T
                adjacent = region[lx + 1 + sdx, ly + 1, lz + 1 + sdz]
                sand_ok = adjacent == SAND
                if not np.any(sand_ok):
                    continue
                chosen = candidates[sand_ok].astype(np.float32)
                chosen[:, 0] += ox + sdx
                chosen[:, 2] += oz + sdz
                # sand_pos is the lower corner of the sand block; the helper
                # places the sheet exactly on its top face.
                uv = np.repeat(TILE_UVS[FACE_TILE[3][WATER]][None, :], len(chosen), axis=0)
                shore_parts.append(_shore_wash_quads(chosen, uv, 0.96, sdx, sdz, segments=6))

'''
if "Build a shallow, animated swash sheet" not in s:
    s = s.replace(needle, shore + needle, 1)

s = s.replace(
'"water": cat(water_parts), "plant": cat(plant_parts),\n                 "leaf_fall": cat(falling_leaf_parts)},',
'"water": cat(water_parts), "plant": cat(plant_parts),\n                 "leaf_fall": cat(falling_leaf_parts), "shore": cat(shore_parts)},', 1)

p.write_text(s, encoding="utf-8")
print("PATCHED: shore mesh generation added")
