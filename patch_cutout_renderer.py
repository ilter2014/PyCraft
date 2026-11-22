from pathlib import Path
import shutil, json

root = Path(r"C:\Users\İlter\Desktop\PyCraft")
app = root / "app.py"
backup = root / "app_before_cutout_renderer_20261122.py"
if not app.is_file():
    raise SystemExit("app.py missing")
if backup.exists():
    raise SystemExit("Backup already exists; refusing to overwrite")
source = app.read_text(encoding="utf-8")

old = '''        cube_parts, water_parts, plant_parts = [], [], []
        face_total = 0

        cube_src = IS_CUBE[src]
        water_src = IS_WATER[src]
        for di, (dx, dy, dz) in enumerate(DIRS):
            nb = region[1 + dx:17 + dx, 1 + dy:1 + yh + dy, 1 + dz:17 + dz]
            free = ~IS_OPAQUE[nb] & (nb != src)
            for src_mask, parts in ((cube_src, cube_parts), (water_src, water_parts)):
                mask = src_mask & free
'''
new = '''        cube_parts, cutout_parts, water_parts, plant_parts = [], [], [], []
        face_total = 0

        # Opaque cubes and alpha-cutout cubes are meshed separately.
        # Cutout blocks (leaves, glass-like masks, etc.) must not be drawn
        # in the opaque front-to-back pass before their alpha is evaluated.
        cube_src = IS_CUBE[src] & IS_OPAQUE[src]
        cutout_src = IS_CUBE[src] & ~IS_OPAQUE[src]
        water_src = IS_WATER[src]
        for di, (dx, dy, dz) in enumerate(DIRS):
            nb = region[1 + dx:17 + dx, 1 + dy:1 + yh + dy, 1 + dz:17 + dz]
            free = ~IS_OPAQUE[nb] & (nb != src)
            for src_mask, parts in ((cube_src, cube_parts),
                                    (cutout_src, cutout_parts),
                                    (water_src, water_parts)):
                mask = src_mask & free
'''
if old not in source:
    raise SystemExit("Mesher block not found; no changes made")

oldret = '''        return ({"cube": cat(cube_parts), "water": cat(water_parts),
                 "plant": cat(plant_parts)}, face_total, ymax)'''
newret = '''        return ({"cube": cat(cube_parts), "cutout": cat(cutout_parts),
                 "water": cat(water_parts), "plant": cat(plant_parts)},
                face_total, ymax)'''
if oldret not in source:
    raise SystemExit("Mesher return block not found; no changes made")

oldrender = '''        # Cutout plants (two crossed quads, no back-face culling).
        ctx.disable(moderngl.CULL_FACE)
        for layers in visible:
            mesh = layers.get("plant")
            if mesh:
                mesh.vao.render(tri, vertices=mesh.count)
'''
newrender = '''        # Alpha-cutout cube blocks (especially leaves).
        # Render after opaque geometry with depth testing AND depth writes on.
        # The fragment shader discards transparent texels, so they never hide
        # geometry behind them; visible texels still occlude farther surfaces.
        ctx.enable(moderngl.CULL_FACE)
        ctx.depth_mask = True
        prog["u_cutout"].value = 1
        prog["u_alpha"].value = 1.0
        for layers in visible:
            mesh = layers.get("cutout")
            if mesh:
                mesh.vao.render(tri, vertices=mesh.count)

        # Cutout plants (two crossed quads, no back-face culling).
        ctx.disable(moderngl.CULL_FACE)
        for layers in visible:
            mesh = layers.get("plant")
            if mesh:
                mesh.vao.render(tri, vertices=mesh.count)
        ctx.enable(moderngl.CULL_FACE)
'''
if oldrender not in source:
    raise SystemExit("Renderer plant block not found; no changes made")

source = source.replace(old, new, 1).replace(oldret, newret, 1).replace(oldrender, newrender, 1)
shutil.copy2(app, backup)
app.write_text(source, encoding="utf-8", newline="\n")
compile(source, str(app), "exec")
print(json.dumps({
    "patched": True,
    "backup": str(backup),
    "changes": [
        "Separate opaque cubes from alpha-cutout cubes",
        "Render cutout cubes after opaque terrain",
        "Preserve depth test and depth writes while discarding transparent texels",
        "Apply to all non-opaque cube blocks, not leaves only"
    ]
}, ensure_ascii=False, indent=2))
