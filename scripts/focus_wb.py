import ctypes
import sys
import time
from ctypes import wintypes

user32 = ctypes.windll.user32

EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

targets = []


def cb(hwnd, lparam):
    if not user32.IsWindowVisible(hwnd):
        return True
    n = user32.GetWindowTextLengthW(hwnd)
    if n == 0:
        return True
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    t = buf.value
    if "MySQL Workbench" in t or "Workbench" in t:
        targets.append((hwnd, t))
    return True


user32.EnumWindows(EnumWindowsProc(cb), 0)
for h, t in targets:
    print("FOUND", h, t)

if not targets:
    print("NO_WINDOW")
    sys.exit(1)

hwnd = targets[0][0]
SW_RESTORE = 9
user32.ShowWindow(hwnd, SW_RESTORE)
time.sleep(0.4)
user32.BringWindowToTop(hwnd)
user32.SetForegroundWindow(hwnd)
time.sleep(1.2)
print("ACTIVATED", user32.GetForegroundWindow(), "target", hwnd)
