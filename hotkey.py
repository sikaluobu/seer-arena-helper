# -*- coding: utf-8 -*-
"""全局热键（Windows）。

用 user32 的 RegisterHotKey/WM_HOTKEY，不装任何第三方库。
**只读取按键，绝不向游戏发送任何按键** —— 按键永远由玩家自己按。

默认 F8：避开游戏自带的 F1（帮助）。要改就改 DEFAULT_KEY。
"""
import ctypes
import ctypes.wintypes as wt
import threading

from console import fix_console; fix_console()

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

# 虚拟键码
VK = {"F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73, "F5": 0x74, "F6": 0x75,
      "F7": 0x76, "F8": 0x77, "F9": 0x78, "F10": 0x79, "F11": 0x7A, "F12": 0x7B,
      "INSERT": 0x2D, "HOME": 0x24, "END": 0x23, "PAGEUP": 0x21, "PAGEDOWN": 0x22,
      "`": 0xC0, "CAPSLOCK": 0x14}

DEFAULT_KEY = "F8"
DEFAULT_MODS = 0


def vk_of(name):
    n = (name or "").strip().upper()
    if n in VK:
        return VK[n]
    if len(n) == 1:
        return ord(n)
    raise ValueError(f"不认识的按键: {name}")


class Hotkey(threading.Thread):
    """在后台线程里等待热键，按下时调用 callback。

    Windows 的 RegisterHotKey 要求注册与 GetMessage 在同一个线程，
    所以整个循环都放在这个线程里跑。
    """

    def __init__(self, callback, key=DEFAULT_KEY, mods=DEFAULT_MODS, hk_id=1):
        super().__init__(daemon=True)
        self.callback = callback
        self.key = key
        self.mods = mods
        self.hk_id = hk_id
        self.ready = threading.Event()
        self.error = None
        self._stop = False

    def run(self):
        vk = vk_of(self.key)
        # MOD_NOREPEAT：按住不放不会连触发
        if not _user32.RegisterHotKey(None, self.hk_id, self.mods | MOD_NOREPEAT, vk):
            self.error = ctypes.get_last_error()
            self.ready.set()
            return
        self.ready.set()
        msg = wt.MSG()
        try:
            while not self._stop:
                # PeekMessage 让线程能定期检查 _stop，而不是卡死在 GetMessage
                r = _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1)
                if r:
                    if msg.message == WM_HOTKEY and msg.wParam == self.hk_id:
                        try:
                            self.callback()
                        except Exception:  # noqa: BLE001
                            pass
                    _user32.TranslateMessage(ctypes.byref(msg))
                    _user32.DispatchMessageW(ctypes.byref(msg))
                else:
                    threading.Event().wait(0.03)
        finally:
            _user32.UnregisterHotKey(None, self.hk_id)

    def stop(self):
        self._stop = True

    def wait_ready(self, timeout=2.0):
        self.ready.wait(timeout)
        return self.error is None


def demo():
    import time
    pressed = []

    def on_hotkey():
        pressed.append(time.time())
        print("热键命中", len(pressed))

    hk = Hotkey(on_hotkey)
    hk.start()
    if not hk.wait_ready():
        raise SystemExit(f"注册热键失败，错误码 {hk.error}（可能被别的程序占了）")
    print(f"已注册 {hk.key}，按 3 秒内按几次试试…")
    time.sleep(3)
    hk.stop()
    print("共命中", len(pressed), "次")


if __name__ == "__main__":
    demo()
