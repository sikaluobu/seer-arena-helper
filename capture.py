# -*- coding: utf-8 -*-
"""屏幕捕获：找到游戏窗口 → 截取它的画面 → 交给 OCR。

只做"看"，不注入任何输入（这是硬约束：按键永远由玩家按）。

两种抓法：
  1. 按窗口矩形直接抓屏（PIL.ImageGrab）—— 要求游戏窗口可见、没被遮挡。
  2. PrintWindow 抓后台窗口 —— 允许窗口被遮挡，但部分游戏用 GPU 直绘，
     PrintWindow 会抓到黑屏，所以默认还是用第 1 种，第 2 种留作备选。

窗口矩形通过 ctypes 调 user32（不需要额外依赖）。
"""
import ctypes
import ctypes.wintypes as wt
import json
import os as _os
from dataclasses import dataclass

from console import fix_console; fix_console()

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_dwmapi = None
try:
    _dwmapi = ctypes.WinDLL("dwmapi")
except OSError:  # 非 Windows 或没有 dwm
    _dwmapi = None

# 别用"标题里含 赛尔号"自动认窗口 —— 浏览器标签页、本项目的对话窗口
# 都可能带着这几个字，会认错。改成：让用户挑一次，把标题片段存下来复用。
TITLE_HINTS = ("赛尔号", "巅峰之战", "Seer", "SEER")

DWMWA_EXTENDED_FRAME_BOUNDS = 9

_TARGET_PATH = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                             "data", "capture.json")
try:                        # 打包后必须写到 exe 旁边，不能写只读的解压目录
    from paths import writable as _writable
    _TARGET_PATH = _writable("data", "capture.json")
except Exception:           # noqa: BLE001
    pass


@dataclass
class Win:
    hwnd: int
    title: str
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self):
        return self.right - self.left

    @property
    def height(self):
        return self.bottom - self.top

    @property
    def bbox(self):
        return (self.left, self.top, self.right, self.bottom)


def _enum_windows():
    """枚举所有可见的顶层窗口，返回 [(hwnd, title)]。"""
    out = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def _cb(hwnd, _lparam):
        if not _user32.IsWindowVisible(hwnd):
            return True
        n = _user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        _user32.GetWindowTextW(hwnd, buf, n + 1)
        out.append((hwnd, buf.value))
        return True

    _user32.EnumWindows(_cb, 0)
    return out


def candidates(hints=TITLE_HINTS):
    """列出可作为目标的窗口：先给标题命中关键词的，再给所有其它有标题的。"""
    fg = _user32.GetForegroundWindow()
    hits, others = [], []
    for hwnd, title in _enum_windows():
        if not title.strip():
            continue
        w = window_rect(hwnd, title)
        if w is None or w.width < 200 or w.height < 150:
            continue          # 太小的多半是工具条/浮动面板，不是游戏
        item = (w, hwnd == fg)
        (hits if any(h in title for h in hints) else others).append(item)
    hits.sort(key=lambda x: (not x[1], -x[0].width * x[0].height))
    others.sort(key=lambda x: (not x[1], -x[0].width * x[0].height))
    return [w for w, _ in hits] + [w for w, _ in others]


def load_target():
    """读上次保存的目标（标题片段 + 可选固定矩形）。"""
    try:
        with open(_TARGET_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_target(title, hwnd=None):
    tgt = {"title": title}
    if hwnd:
        tgt["hwnd"] = hwnd
    _os.makedirs(_os.path.dirname(_TARGET_PATH), exist_ok=True)
    with open(_TARGET_PATH, "w", encoding="utf-8") as f:
        json.dump(tgt, f, ensure_ascii=False, indent=2)
    return tgt


def find_window(hints=TITLE_HINTS, saved=None):
    """按保存的标题片段找窗口。

    **不做关键词自动匹配**：浏览器标签页、本项目的对话窗口都可能带
    "赛尔号" 三个字，自动匹配会认错窗口。必须先 `python capture.py pick`
    选一次，把标题片段存进 data/capture.json。

    返回 Win 或 None。
    """
    saved = saved if saved is not None else load_target()
    frag = (saved or {}).get("title")
    if not frag:
        return None
    wins = [(h, t) for h, t in _enum_windows() if t.strip()]
    hit = [(h, t) for h, t in wins if frag in t]
    rects = [r for r in (window_rect(h, t) for h, t in hit) if r]
    if not rects:
        return None
    # 片段命中多个时，优先选窗口更大的那个（浏览器可能开多个同标题标签）
    return max(rects, key=lambda r: r.width * r.height)


def _title_of(hwnd):
    n = _user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    _user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def window_rect(hwnd, title=""):
    """取窗口的**可见**矩形。

    普通 GetWindowRect 会把 Windows 10+ 的隐形阴影边框算进去，
    这里优先读 DWM 的扩展边框（拿不到就退回 GetWindowRect）。
    """
    left = top = right = bottom = 0
    got = False
    if _dwmapi is not None:
        r = wt.RECT()
        try:
            hr = _dwmapi.DwmGetWindowAttribute(
                wt.HWND(hwnd), ctypes.c_uint(DWMWA_EXTENDED_FRAME_BOUNDS),
                ctypes.byref(r), ctypes.sizeof(r))
            if hr == 0:
                left, top, right, bottom = r.left, r.top, r.right, r.bottom
                got = True
        except Exception:  # noqa: BLE001
            got = False
    if not got:
        r = wt.RECT()
        if not _user32.GetWindowRect(wt.HWND(hwnd), ctypes.byref(r)):
            return None
        left, top, right, bottom = r.left, r.top, r.right, r.bottom
    return Win(int(hwnd), title or _title_of(hwnd), left, top, right, bottom)


def client_rect(hwnd):
    """客户区（去掉标题栏/边框）在屏幕坐标里的矩形。"""
    r = wt.RECT()
    if not _user32.GetClientRect(wt.HWND(hwnd), ctypes.byref(r)):
        return None
    pt = wt.POINT(0, 0)
    _user32.ClientToScreen(wt.HWND(hwnd), ctypes.byref(pt))
    return (pt.x, pt.y, pt.x + r.right, pt.y + r.bottom)


def grab(bbox=None):
    """截屏，返回 PIL.Image。bbox 为 (l,t,r,b)，None 表示全屏。"""
    from PIL import ImageGrab
    return ImageGrab.grab(bbox=bbox, all_screens=True)


def grab_window(win=None, use_client=True):
    """截取游戏窗口画面。win 为 None 就自动找。"""
    win = win or find_window()
    if not win:
        return None, None
    box = win.bbox
    if use_client:
        cb = client_rect(win.hwnd)
        if cb:
            box = cb
    return grab(box), win


def grab_game(client_only=True):
    """便捷入口：直接返回游戏画面（找不到窗口就返回 None）。"""
    win = find_window()
    if not win:
        return None
    box = client_rect(win.hwnd) if client_only else win.bbox
    return grab(box or win.bbox)


def pick():
    """交互式挑窗口，存下标题片段。"""
    cands = candidates()
    if not cands:
        print("没有找到合适的窗口。请先把游戏画面打开。")
        return None
    print("可选的窗口（按面积/前台排序）：")
    for i, w in enumerate(cands[:15], 1):
        print(f"  [{i:>2}] {w.width:>5}x{w.height:<5} {w.title!r}")
    print("  输入编号选择；直接回车取消。")
    try:
        s = input("> ").strip()
    except EOFError:
        return None
    if not s.isdigit():
        return None
    idx = int(s) - 1
    if not (0 <= idx < len(cands)):
        return None
    w = cands[idx]
    save_target(w.title, w.hwnd)
    print(f"已记住目标：{w.title!r}  →  {w.bbox}")
    return w


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "pick":
        pick()
    elif len(sys.argv) > 1 and sys.argv[1] == "list":
        for w in candidates():
            print(f"  {w.width:>5}x{w.height:<5} {w.title!r}")
    else:
        print("已保存的目标:", load_target())
        w = find_window()
        print("自动选中:", w)
        img = grab_game()
        print("截图尺寸:", None if img is None else img.size)
