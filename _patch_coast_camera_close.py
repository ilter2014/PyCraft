from pathlib import Path
p=Path(r"C:\Users\İlter\Desktop\PyCraft\app.py")
s=p.read_text(encoding="utf-8")
s=s.replace('player.pos[:] = (101.5, 34.0, 93.5)','player.pos[:] = (99.5, 34.0, 93.5)',1)
p.write_text(s,encoding="utf-8")
print("Moved coast test camera to the actual sand-water edge.")
