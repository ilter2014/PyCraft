from pathlib import Path
p=Path("app.py"); s=p.read_text(encoding="utf-8")
old='''        if k == pygame.K_ESCAPE:
            if self.state == "playing":
                self.pause()'''
new='''        if k == pygame.K_ESCAPE:
            if self.state == "settings" and self.rebind_action:
                self.rebind_action = None
                return
            if self.state == "playing":
                self.pause()'''
if old not in s: raise SystemExit("ESC anchor missing")
s=s.replace(old,new,1)
old='''        if player.underwater:
            prog["u_fog"].value = (0.045, 0.16, 0.28)
            prog["u_fog_range"].value = (3.0, 34.0)
        else:
            prog["u_fog"].value = SKY_HORIZON
            prog["u_fog_range"].value = (FOG_START, FOG_END)'''
new='''        fog_start = min(FOG_START, game.render_distance * 0.58)
        fog_end = min(FOG_END, game.render_distance)
        if player.underwater:
            prog["u_fog"].value = (0.045, 0.16, 0.28)
            prog["u_fog_range"].value = (3.0, 34.0)
        else:
            prog["u_fog"].value = SKY_HORIZON
            prog["u_fog_range"].value = (fog_start, fog_end)'''
if old not in s: raise SystemExit("fog anchor missing")
s=s.replace(old,new,1)
p.write_text(s,encoding="utf-8")
print("POLISH_OK")
