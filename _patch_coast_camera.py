from pathlib import Path
p=Path(r"C:\Users\İlter\Desktop\PyCraft\app.py")
s=p.read_text(encoding="utf-8")
s=s.replace(
'    parser.add_argument("--seed", type=int, default=2026, help="world seed")',
'    parser.add_argument("--seed", type=int, default=2026, help="world seed")\n    parser.add_argument("--coast-test", action="store_true", help="aim the test camera at the nearest beach")',1)
s=s.replace(
'        player = Player(world)\n        game = Game(renderer, world, player)',
'        player = Player(world)\n        if args.coast_test:\n            # Seed-2026 shoreline test position: stand on the beach and face the sea.\n            player.pos[:] = (101.5, 34.0, 93.5)\n            player.yaw = -math.pi / 2.0\n            player.pitch = -0.24\n            player.fly = True\n        game = Game(renderer, world, player)',1)
p.write_text(s,encoding="utf-8")
print("Added optional coast-test camera.")
