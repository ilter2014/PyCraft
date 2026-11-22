import cv2, time, ctypes
from ctypes import wintypes
from PIL import ImageGrab
from pathlib import Path
user32 = ctypes.windll.user32
EnumWindows = user32.EnumWindows
CALLBACK = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
EnumWindows.argtypes = [CALLBACK, wintypes.LPARAM]
GetWindowTextLength = user32.GetWindowTextLengthW
GetWindowText = user32.GetWindowTextW
IsWindowVisible = user32.IsWindowVisible
found = []
@CALLBACK
def cb(hwnd, lparam):
    if IsWindowVisible(hwnd):
        n = GetWindowTextLength(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        GetWindowText(hwnd, buf, n + 1)
        if "PyCraft - Minecraft-style voxel sandbox" in buf.value:
            found.append(hwnd)
    return True
EnumWindows(cb, 0)
if not found: raise RuntimeError("PyCraft window not found")
hwnd = found[0]
user32.ShowWindow(hwnd, 3)
user32.SetForegroundWindow(hwnd)
time.sleep(1.5)
out = Path(r"C:\Users\İlter\Desktop\PyCraft\PyCraft_Wave_Iteration.mp4")
fps, seconds = 24, 10
first = ImageGrab.grab().convert("RGB")
w, h = first.size
w, h = w - (w % 2), h - (h % 2)
writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
if not writer.isOpened(): raise RuntimeError("MP4 VideoWriter could not be opened")
start = time.perf_counter()
frames = 0
while time.perf_counter() - start < seconds:
    frame = ImageGrab.grab(bbox=(0, 0, w, h)).convert("RGB")
    writer.write(cv2.cvtColor(__import__("numpy").array(frame), cv2.COLOR_RGB2BGR))
    frames += 1
    target = start + frames / fps
    delay = target - time.perf_counter()
    if delay > 0: time.sleep(delay)
writer.release()
print("RECORDED", out, "frames=", frames, "size=", w, "x", h, "bytes=", out.stat().st_size)
