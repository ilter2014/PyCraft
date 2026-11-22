from pathlib import Path
import re
p=Path(r"C:\Users\İlter\Desktop\PyCraft\app.py")
s=p.read_text(encoding="utf-8")
# The old beach overlay was a detached transparent sheet; disable its generation.
start=s.find("        # Build a shallow, animated swash sheet over beach sand blocks")
end=s.find("        # Sparse individual leaflets detach", start)
if start < 0 or end < 0:
    raise SystemExit("Could not locate the old swash mesh generation block")
s=s[:start]+s[end:]
# Remove the fake shoreline overlay draw pass.
start=s.find("        # Shoreline swash: advances over beach sand")
end=s.find("        if \"u_anim_mode\" in prog:\n            prog[\"u_anim_mode\"].value = 0", start)
if start < 0 or end < 0:
    raise SystemExit("Could not locate the old swash render pass")
s=s[:start]+s[end:]
p.write_text(s,encoding="utf-8")
print("Removed detached shoreline sheet; water now uses continuous wave surface.")
