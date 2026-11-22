from PIL import Image, ImageDraw, ImageFilter
import random, math, os
random.seed(42)
S=1024
im=Image.new("RGB",(S,S))
p=im.load()
# Deep teal dawn sky, gently illuminated near horizon
for y in range(S):
    t=y/(S-1)
    for x in range(S):
        glow=max(0,1-abs(x/S-.68)*1.7)*max(0,1-abs(t-.56)*2.2)
        p[x,y]=(int(18+22*t+28*glow),int(42+52*t+42*glow),int(55+42*t+24*glow))
d=ImageDraw.Draw(im,"RGBA")
# soft sun and halo
d.ellipse((690,285,850,445),fill=(242,210,145,25))
d.ellipse((720,315,820,415),fill=(255,224,160,220))
# blocky distant peaks
d.polygon([(0,570),(0,465),(105,385),(165,445),(255,330),(345,430),(435,360),(535,465),(650,350),(745,440),(850,365),(1024,470),(1024,660)],fill=(57,104,105,255))
d.polygon([(0,570),(105,465),(165,505),(255,395),(345,500),(435,430),(535,530),(650,420),(745,510),(850,435),(1024,535),(1024,670)],fill=(42,83,83,255))
# snow/stone caps
for poly in [[(105,465),(165,385),(205,440),(165,425),(145,450)],[(255,395),(255,330),(300,390),(280,375)],[(650,420),(650,350),(700,415),(675,395)],[(850,435),(850,365),(900,425),(875,405)]]:
    d.polygon(poly,fill=(169,190,165,220))
# far forest silhouettes
for x in range(-20,1060,34):
    base=650+random.randint(-30,40)
    h=random.randint(90,190)
    c=random.choice([(27,73,61,255),(31,85,66,255),(38,94,72,255)])
    d.rectangle((x-7,base-h*.45,x+7,base),fill=(75,58,42,255))
    for k in range(4):
        yy=base-h+k*h*.20
        half=(k+1)*13
        d.polygon([(x,yy-30),(x-half,yy+20),(x+half,yy+20)],fill=c)
# winding river / valley
d.polygon([(440,1024),(590,1024),(535,875),(620,780),(570,700),(640,650),(560,625),(475,700),(505,790),(430,870)],fill=(48,126,133,255))
d.polygon([(500,1024),(555,1024),(535,880),(600,790),(560,720),(605,670),(565,665),(520,730),(550,800),(470,890)],fill=(91,174,166,190))
# foreground rolling blocky hills
d.polygon([(0,700),(150,660),(285,700),(420,660),(540,720),(700,650),(850,700),(1024,650),(1024,1024),(0,1024)],fill=(37,91,58,255))
d.polygon([(0,790),(180,735),(340,785),(470,735),(650,800),(820,735),(1024,780),(1024,1024),(0,1024)],fill=(29,72,48,255))
# large stylized voxel trees framing edges
def tree(x,base,scale=1.0,shade=0):
    trunkw=int(20*scale); th=int(100*scale)
    d.rectangle((x-trunkw//2,base-th,x+trunkw//2,base),fill=(91,61,39,255))
    greens=[(35,105,62,255),(42,125,70,255),(54,139,76,255)]
    for j,(w,h,dy) in enumerate([(115,68,0),(90,65,48),(62,60,95)]):
        yy=base-th+dy
        c=greens[(j+shade)%len(greens)]
        d.rectangle((x-w//2,yy-h,x+w//2,yy),fill=c)
        d.rectangle((x-w//2,yy-h,x+w//2,yy-h+9),fill=(74,158,87,255))
        d.rectangle((x-w//2,yy-h,x-w//2+10,yy),fill=(26,86,53,255))
for args in [(-15,900,1.7,0),(90,830,1.15,1),(1000,900,1.8,2),(910,820,1.2,0),(250,870,.8,1),(780,865,.9,2)]:
    tree(*args)
# chunky grass ledges foreground
for x in range(-40,1080,90):
    y= random.randint(900,1000)
    d.rectangle((x,y,x+random.randint(45,95),y+24),fill=(62,126,65,255))
    d.rectangle((x,y,x+random.randint(45,95),y+5),fill=(104,166,78,255))
# firefly pixels and clouds
for _ in range(90):
    x=random.randint(0,S-1); y=random.randint(100,800)
    if random.random()<.35:
        d.rectangle((x,y,x+2,y+2),fill=(225,226,160,100))
# subtle pixel grain, then mild vignette
im=im.convert("RGBA")
overlay=Image.new("RGBA",(S,S),(0,0,0,0)); od=ImageDraw.Draw(overlay)
for y in range(S):
    for x in range(S):
        dist=math.sqrt(((x-S/2)/(S*.72))**2+((y-S/2)/(S*.72))**2)
        a=int(max(0,min(105,(dist-.48)*125)))
        if a: od.point((x,y),fill=(5,15,15,a))
im=Image.alpha_composite(im,overlay).convert("RGB")
out=r"C:\Users\İlter\Desktop\PyCraft\Assets\gui\title\background\pycraft_panorama.png"
os.makedirs(os.path.dirname(out),exist_ok=True)
im.save(out,quality=95)
print(out, im.size)
