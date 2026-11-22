from PIL import Image, ImageChops
from pathlib import Path
a=Image.open(r"PyCraft_Coastal_Physics_Frames\frame_00000.png").convert("RGB")
b=Image.open(r"PyCraft_Coastal_Physics_Frames\frame_00120.png").convert("RGB")
diff=ImageChops.difference(a,b)
print("frame diff bbox",diff.getbbox(),"mean",sum(diff.convert("L").getdata())/(a.width*a.height))
