import app, numpy as np
w=app.World(2026); w.generate(); b=w.blocks; out=[]
for x in range(2,app.WX-2):
 for z in range(2,app.WZ-2):
  if b[x,app.SEA_LEVEL,z]!=app.SAND: continue
  for dx,dz in ((-1,0),(1,0),(0,-1),(0,1)):
   if b[x+dx,app.SEA_LEVEL,z+dz]!=app.WATER: continue
   water_run=0
   for k in range(1,15):
    xx,zz=x+dx*k,z+dz*k
    if b[xx,app.SEA_LEVEL,zz]==app.WATER: water_run+=1
    else: break
   land_run=0
   for k in range(1,5):
    xx,zz=x-dx*k,z-dz*k
    if b[xx,app.SEA_LEVEL,z-dz*k] in (app.SAND,app.GRASS): land_run+=1
    else: break
   # prefer long water view and gentle land behind
   out.append((water_run,land_run,x,z,dx,dz,int(w.heights[x,z])))
out.sort(reverse=True)
print("best shore candidates",out[:25])
