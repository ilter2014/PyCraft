from pathlib import Path
p=Path(r"C:\Users\İlter\Desktop\PyCraft\app.py")
s=p.read_text(encoding="utf-8").replace("player.yaw = -math.pi / 2.0","player.yaw = math.pi / 2.0",1)
p.write_text(s,encoding="utf-8")
print("Adjusted test camera toward the open-water side.")
