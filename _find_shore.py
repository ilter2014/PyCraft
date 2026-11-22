import app, numpy as np
w=app.World(2026); w.generate()
pairs=[]
for dx,dz in ((-1,0),(1,0),(0,-1),(0,1)):
 xs,zs=np.where((w.blocks[:,app.SEA_LEVEL,:]==app.SAND) & (np.roll(w.blocks[:,app.SEA_LEVEL,:],shift=(dx,dz),axis=(0,1))==app.WATER))
 for x,z in zip(xs,zs):
  pairs.append((int(x),int(z),dx,dz,int(w.heights[x,z])))
sx,_,sz=w.spawn
pairs.sort(key=lambda q:(q[0]-sx)**2+(q[1]-sz)**2)
print("spawn",w.spawn,"nearest shore",pairs[:8])
