import app, numpy as np, time
w=app.World(2026); w.generate()
total=0; chunks=0
for cx in range(app.WX//app.CHUNK):
 for cz in range(app.WZ//app.CHUNK):
  layers,faces,ymax=w.mesh_arrays(cx,cz)
  n=len(layers["shore"])
  if n: chunks+=1; total+=n
print("SHORE_VERTICES",total,"SHORE_QUADS",total//4,"CHUNKS",chunks)
print("WATER_BLOCKS",int(np.count_nonzero(w.blocks==app.WATER)))
print("SAND_BLOCKS_AT_SEA",int(np.count_nonzero(w.blocks[:,app.SEA_LEVEL,:]==app.SAND)))
