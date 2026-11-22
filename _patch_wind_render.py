from pathlib import Path
p = Path(r"C:\Users\İlter\Desktop\PyCraft\app.py")
s = p.read_text(encoding="utf-8")
# Preserve interpolation across each shore strip rather than assigning one
# distance to all four corners.
s = s.replace(
"        verts[:, :, 6] = d1\n        parts.append(verts.reshape(-1, 7))",
"        if water_dx:\n            verts[:, :, 6] = np.array([d0, d1, d1, d0], dtype=np.float32)[None, :]\n        else:\n            verts[:, :, 6] = np.array([d1, d1, d0, d0], dtype=np.float32)[None, :]\n        parts.append(verts.reshape(-1, 7))", 1)

# Cache sea-level water candidates once, not once for each cardinal direction.
s = s.replace(
"        water_cells = np.argwhere(water_src)\n        if water_cells.size:\n            for sdx, sdz in ((-1, 0), (1, 0), (0, -1), (0, 1)):\n                sea_mask = water_src[:, :, :] & (np.indices(water_src.shape)[1] == SEA_LEVEL)\n                candidates = np.argwhere(sea_mask)\n                if not len(candidates):\n                    continue",
"        candidates = np.argwhere(water_src & (np.arange(yh, dtype=np.int32)[None, :, None] == SEA_LEVEL))\n        if len(candidates):\n            for sdx, sdz in ((-1, 0), (1, 0), (0, -1), (0, 1)):", 1)

# Shared wind vector uniform.
s = s.replace(
'        prog["u_sun_dir"].value = tuple(float(v) for v in SUN_DIR)\n        prog["u_time"].value = float(self.time)',
'        prog["u_sun_dir"].value = tuple(float(v) for v in SUN_DIR)\n        prog["u_wind_dir"].value = (0.78, 0.62)\n        prog["u_time"].value = float(self.time)', 1)

# Animate plants with the same field; their bottom vertices remain anchored.
s = s.replace(
'        # Flowers and thin-stem plants stay rooted; only leaf canopies sway.\n        if "u_anim_mode" in prog:\n            prog["u_anim_mode"].value = 0\n        # Cutout plants (two crossed quads, no back-face culling).',
'        # Flowers, grass and thin stems flex from their rooted bases.\n        if "u_anim_mode" in prog:\n            prog["u_anim_mode"].value = 1\n        # Cutout plants (two crossed quads, no back-face culling).', 1)

# Add swash pass after offshore water. It is a separate shallow sheet over
# the sand, with depth writes disabled so the underlying beach remains solid.
needle = '            prog["u_cutout"].value = 1\n        if "u_anim_mode" in prog:\n            prog["u_anim_mode"].value = 0\n\n        # Slow, blocky cloud layer high above the world.'
replacement = '''            prog["u_cutout"].value = 1

        # Shoreline swash: advances over beach sand, breaks into a foam edge,
        # then retreats. It is geometry, not a screen-space highlight.
        shore = [layers["shore"] for layers in reversed(visible)
                 if "shore" in layers]
        if shore:
            if "u_anim_mode" in prog:
                prog["u_anim_mode"].value = 4
            ctx.enable(moderngl.BLEND)
            ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA)
            ctx.depth_mask = False
            ctx.enable(moderngl.CULL_FACE)
            prog["u_cutout"].value = 0
            prog["u_alpha"].value = 1.0
            for mesh in shore:
                mesh.vao.render(tri, vertices=mesh.count)
            ctx.depth_mask = True
            ctx.disable(moderngl.BLEND)
            prog["u_cutout"].value = 1
        if "u_anim_mode" in prog:
            prog["u_anim_mode"].value = 0

        # Slow, blocky cloud layer high above the world.'''
if needle not in s:
    raise SystemExit("renderer insertion point not found")
s = s.replace(needle, replacement, 1)
p.write_text(s, encoding="utf-8")
print("PATCHED: shared wind, plant sway, shoreline swash render pass")
