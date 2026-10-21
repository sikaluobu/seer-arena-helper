# -*- coding: utf-8 -*-
"""路径解析：源码运行和打包成 exe 之后都能找到数据。

打包（PyInstaller）之后有两套目录，必须分清楚：

- `APP_DIR`    —— exe 自己所在的目录。**可写**，日志/缓存/窗口选择记录放这里，
                 用户也能把 `data/seer.db` 放在这儿覆盖打包进去的那份。
- `BUNDLE_DIR` —— 打包时塞进 exe 里的只读资源，运行时会解压到一个临时目录
                 （onefile 模式就是 `sys._MEIPASS`）。数据文件在这里面。

`resource()` 先看 exe 旁边有没有，没有才用打包进去的 —— 这样用户想换精灵库
时直接往旁边放一份就行，不用重新打包。
"""
import os
import sys

FROZEN = bool(getattr(sys, "frozen", False))

if FROZEN:
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

BUNDLE_DIR = getattr(sys, "_MEIPASS", None) or APP_DIR


def resource(*parts):
    """只读资源：exe 旁边优先，其次用打包进去的。"""
    p = os.path.join(APP_DIR, *parts)
    return p if os.path.exists(p) else os.path.join(BUNDLE_DIR, *parts)


def writable(*parts):
    """可写路径（会顺手把父目录建出来）。"""
    p = os.path.join(APP_DIR, *parts)
    d = os.path.dirname(p)
    if d:
        os.makedirs(d, exist_ok=True)
    return p


def describe():
    return (f"源码/打包: {'打包 exe' if FROZEN else '源码'}\n"
            f"  程序目录: {APP_DIR}\n"
            f"  资源目录: {BUNDLE_DIR}")
