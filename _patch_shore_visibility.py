from pathlib import Path
p=Path(r"C:\Users\İlter\Desktop\PyCraft\app.py")
s=p.read_text(encoding="utf-8")
s=s.replace(
'            ctx.depth_mask = False\n            ctx.enable(moderngl.CULL_FACE)\n            prog["u_cutout"].value = 0\n            prog["u_alpha"].value = 1.0\n            for mesh in shore:',
'            ctx.depth_mask = False\n            ctx.disable(moderngl.CULL_FACE)\n            prog["u_cutout"].value = 0\n            prog["u_alpha"].value = 1.0\n            for mesh in shore:',1)
s=s.replace(
'            ctx.depth_mask = True\n            ctx.disable(moderngl.BLEND)\n            prog["u_cutout"].value = 1\n        if "u_anim_mode" in prog:',
'            ctx.depth_mask = True\n            ctx.disable(moderngl.BLEND)\n            ctx.enable(moderngl.CULL_FACE)\n            prog["u_cutout"].value = 1\n        if "u_anim_mode" in prog:',1)
p.write_text(s,encoding="utf-8")
q=Path(r"C:\Users\İlter\Desktop\PyCraft\Assets\shaders\terrain.vert")
v=q.read_text(encoding="utf-8").replace(
'return primary * 0.030 + secondary * 0.013 + shortWave * 0.006;',
'return primary * 0.043 + secondary * 0.019 + shortWave * 0.008;')
q.write_text(v,encoding="utf-8")
f=Path(r"C:\Users\İlter\Desktop\PyCraft\Assets\shaders\terrain.frag")
t=f.read_text(encoding="utf-8").replace(
'vec3 shallowWater = vec3(0.10, 0.27, 0.27);',
'vec3 shallowWater = vec3(0.075, 0.25, 0.26);')
t=t.replace('float alpha = wet * 0.25 + foam * 0.62;',
            'float alpha = wet * 0.34 + foam * 0.78;')
t=t.replace('return primary * 0.030 + secondary * 0.013 + shortWave * 0.006;',
            'return primary * 0.043 + secondary * 0.019 + shortWave * 0.008;')
f.write_text(t,encoding="utf-8")
print("Refined shore pass culling and increased controlled swell amplitude.")
