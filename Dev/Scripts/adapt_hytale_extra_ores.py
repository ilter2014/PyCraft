from pathlib import Path
from zipfile import ZipFile
from PIL import Image
import io, json, shutil, math, colorsys

ROOT=Path(r"C:\Users\İlter\Desktop\PyCraft")
BLOCKS=ROOT/"Assets"/"block"
ARCHIVE=Path(r"C:\Users\İlter\AppData\Roaming\Hytale\install\release\package\game\latest\Assets.zip")
BACKUP=ROOT/"Hytale_Extra_Ores_Backup_20261122"

# (ore-bearing source, matching mask host, displayed host, mineral style)
BASE={
 "coal":("Rock_Basalt_Iron_Cracks.png","Rock_Basalt.png","coal"),
 "iron":("Rock_Basalt_Iron_Cracks02.png","Rock_Basalt.png","iron"),
 "copper":("Rock_Basalt_Iron_Cracks03.png","Rock_Basalt.png","copper"),
 "gold":("Soil_Mud_Dry_Thorium_Cracks02.png","Soil_Mud_Dry.png","gold"),
 "diamond":("Rock_Slate_Cobalt_Cracks03.png","Rock_Slate.png","diamond"),
 "lapis":("Rock_Slate_Cobalt_Cracks02.png","Rock_Slate.png","lapis"),
 "emerald":("Soil_Mud_Dry_Thorium_Cracks.png","Soil_Mud_Dry.png","emerald"),
 "redstone":("Rock_Magma_Cooled_Adamantite_Cracks02.png","Rock_Magma_Cooled.png","redstone"),
}
MAPPING={}
for kind,(ore,mask,style) in BASE.items():
    MAPPING[f"deepslate_{kind}_ore.png"]=(f"Common/BlockTextures/{ore}",f"Common/BlockTextures/{mask}","Common/BlockTextures/Rock_Slate.png",style)
MAPPING["nether_gold_ore.png"]=("Common/BlockTextures/Soil_Mud_Dry_Thorium_Cracks02.png","Common/BlockTextures/Soil_Mud_Dry.png","Common/BlockTextures/Rock_Magma_Cooled.png","gold")
MAPPING["nether_quartz_ore.png"]=("Common/BlockTextures/Rock_Basalt_Iron_Cracks02.png","Common/BlockTextures/Rock_Basalt.png","Common/BlockTextures/Rock_Magma_Cooled.png","iron")

def recolor(kind,rgb):
    r,g,b=rgb
    h,s,v=colorsys.rgb_to_hsv(r/255,g/255,b/255)
    if kind=="coal": return (max(8,int(r*.22)),max(8,int(g*.22)),max(8,int(b*.24)))
    if kind=="iron": return (min(255,int(160+v*70)),min(255,int(165+v*65)),min(255,int(155+v*65)))
    if kind=="copper": return (min(255,int(165+v*70)),min(255,int(76+v*52)),min(255,int(35+v*28)))
    if kind=="gold": return (min(255,int(190+v*60)),min(255,int(135+v*70)),min(255,int(25+v*28)))
    if kind=="diamond": return (min(255,int(60+v*70)),min(255,int(190+v*60)),min(255,int(205+v*50)))
    if kind=="lapis": return (min(255,int(28+v*40)),min(255,int(65+v*65)),min(255,int(165+v*85)))
    if kind=="emerald": return (min(255,int(30+v*35)),min(255,int(145+v*85)),min(255,int(75+v*65)))
    if kind=="redstone": return (min(255,int(175+v*75)),min(255,int(28+v*32)),min(255,int(22+v*25)))
    return rgb

if not ARCHIVE.is_file() or not BLOCKS.is_dir(): raise SystemExit("Assets missing")
if BACKUP.exists(): raise SystemExit(f"Backup exists: {BACKUP}")
BACKUP.mkdir(parents=True)
changed=[]
with ZipFile(ARCHIVE) as z:
    available=set(z.namelist())
    for name,(ore_path,mask_path,host_path,style) in MAPPING.items():
        target=BLOCKS/name
        if not target.is_file(): continue
        if any(p not in available for p in (ore_path,mask_path,host_path)):
            print("MISSING SOURCE",name); continue
        shutil.copy2(target,BACKUP/name)
        ore=Image.open(io.BytesIO(z.read(ore_path))).convert("RGB")
        mask_host=Image.open(io.BytesIO(z.read(mask_path))).convert("RGB")
        host=Image.open(io.BytesIO(z.read(host_path))).convert("RGB")
        if mask_host.size!=ore.size: mask_host=mask_host.resize(ore.size,Image.Resampling.BILINEAR)
        if host.size!=ore.size: host=host.resize(ore.size,Image.Resampling.BILINEAR)
        op,hp=ore.load(),mask_host.load()
        out=host.copy(); dst=out.load()
        for y in range(ore.height):
            for x in range(ore.width):
                a,b=op[x,y],hp[x,y]
                diff=math.sqrt(sum((a[i]-b[i])**2 for i in range(3)))
                if diff >= (42 if style=="coal" else 30):
                    dst[x,y]=recolor(style,a)
        out.resize((16,16),Image.Resampling.LANCZOS).save(target,"PNG",optimize=True)
        changed.append({"target":name,"style":style,"output":"16x16","display_host":host_path})
report={"changed":len(changed),"files":changed,"backup":str(BACKUP)}
(ROOT/"Hytale_Extra_Ores_Report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(report,ensure_ascii=False,indent=2))
