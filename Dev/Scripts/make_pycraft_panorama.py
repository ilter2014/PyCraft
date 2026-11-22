from PIL import Image, ImageDraw
import random, math
random.seed(24)
S=512
im=Image.new("RGB",(S,S))
p=im.load()
# dusk-to-dawn sky with restrained color variation
for y in range(S):
    t=y/S
    top=(27,43,55); mid=(83,112,116); low=(185,151,111)
    if t<.62:
        q=t/.62; a,b=top,mid
    else:
        q=(t-.62)/.38; a,b=mid,low
    c=tuple(int(a[i]*(1-q)+b[i]*q) for i in range(3))
    for x in range(S):
        n=random.choice([-2,-1,0,0,0,1,2])
        p[x,y]=tuple(max(0,min(255,v+n)) for v in c)
d=ImageDraw.Draw(im)
# distant haze and layered mountain silhouettes
d.rectangle((0,255,511,330), fill=(120,139,130))
d.polygon([(0,275),(45,214),(82,251),(140,177),(194,246),(253,194),(309,250),(370,184),(428,244),(477,205),(511,244),(511,355),(0,355)],fill=(75,101,103))
d.polygon([(0,286),(45,214),(62,235),(46,231),(37,252),(58,244),(72,263),(93,256),(140,177),(160,210),(146,202),(132,224),(153,221),(177,260),(210,245),(253,194),(274,226),(257,218),(245,239),(270,240),(298,271),(340,255),(370,184),(393,218),(378,208),(365,230),(386,226),(410,256),(446,243),(477,205),(493,229),(482,223),(471,240),(491,237),(511,258),(511,355),(0,355)], fill=(137,145,132))
# snow caps, irregular stepped facets
for poly,col in [
 ([(140,177),(128,197),(138,192),(145,204),(154,197),(164,213),(177,260),(153,225),(143,229),(133,210),(119,222)],(207,205,181)),
 ([(253,194),(240,215),(251,209),(260,224),(270,216),(283,239),(298,271),(276,242),(265,246),(255,229),(239,241)],(197,201,180)),
 ([(370,184),(357,207),(369,200),(379,215),(389,208),(402,230),(410,256),(390,226),(378,229),(365,212),(351,226)],(211,207,182)),
 ([(477,205),(465,225),(476,218),(486,234),(495,228),(511,258),(492,238),(481,242),(469,229),(457,240)],(190,198,177))]:
 d.polygon(poly,fill=col)
# sun low in sky, softened concentric pixel rings
d.ellipse((365,105,427,167),fill=(209,174,126))
d.ellipse((372,112,420,160),fill=(232,197,145))
# distant conifer forest
d.polygon([(0,320),(511,320),(511,410),(0,410)],fill=(48,77,69))
for x in range(-8,525,19):
    h=random.randint(42,86); base=random.randint(337,382); w=random.randint(11,19)
    d.rectangle((x-2,base-h//5,x+2,base+12),fill=(73,61,48))
    for j in range(4):
        yy=base-h+j*(h//5)
        ww=max(2,w-j*2)
        d.polygon([(x,yy-13),(x-ww,yy+10),(x+ww,yy+10)],fill=random.choice([(30,66,58),(35,75,63),(40,81,66)]))
# middle ground rolling grassy blocks
d.polygon([(0,373),(88,355),(162,378),(235,350),(310,375),(388,348),(511,372),(511,511),(0,511)],fill=(39,77,57))
d.polygon([(0,400),(93,380),(162,400),(239,376),(317,402),(398,377),(511,403),(511,511),(0,511)],fill=(31,66,49))
# winding river with stepped banks
d.polygon([(247,511),(279,462),(266,435),(292,411),(319,390),(345,400),(324,427),(341,449),(319,474),(302,511)],fill=(34,75,78))
d.polygon([(259,511),(287,463),(276,438),(301,414),(320,400),(337,404),(316,432),(331,450),(309,477),(291,511)],fill=(69,116,119))
for _ in range(120):
    x=random.randrange(512); y=random.randrange(365,512)
    if random.random()<.55:
        d.rectangle((x,y,x+random.randint(1,4),y+random.randint(1,2)),fill=random.choice([(47,86,59),(57,96,65),(77,104,67)]))
# foreground blocky trees, varied scale and silhouette
for x in [22,72,126,185,352,410,468]:
    base=random.randint(448,494); h=random.randint(82,130); w=random.randint(22,34)
    d.rectangle((x-5,base-15,x+5,base+13),fill=(78,58,43))
    for j in range(5):
        yy=base-h+j*(h//5)
        ww=max(4,w-j*4)
        d.polygon([(x,yy-18),(x-ww,yy+12),(x+ww,yy+12)],fill=random.choice([(22,66,51),(27,77,57),(34,86,61)]))
        d.line((x-ww+3,yy+8,x+ww-3,yy+8),fill=(46,99,66),width=2)
# scattered grass tufts and stones
for _ in range(180):
    x=random.randrange(512); y=random.randrange(390,512)
    if 245<x<350 and random.random()<.8: continue
    col=random.choice([(74,105,65),(89,111,67),(47,83,55),(101,112,72)])
    d.line((x,y,x+random.randint(-2,2),y-random.randint(2,6)),fill=col,width=1)
# tiny distant birds
for x,y in [(84,135),(102,128),(294,151),(306,145)]:
    d.line((x,y,x+4,y+2),fill=(52,68,67),width=1); d.line((x+4,y+2,x+8,y),fill=(52,68,67),width=1)
# upscale with nearest neighbor for crisp, intentional pixel-art texture
im=im.resize((1024,1024),Image.Resampling.NEAREST)
im.save(r"Assets\gui\title\background\pycraft_panorama.png", optimize=True)
print("Created handcrafted pixel-art panorama:", im.size)
