# -*- coding: utf-8 -*-
"""控制台编码与日志小工具。

不要用 `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, ...)`：
那样会替换掉解释器自带的 stdout，包装器被回收时会连带关掉底层流，
在多模块互相 import 或输出被管道提前关闭时报 "I/O operation on closed file"。
统一用 reconfigure。
"""
import sys


def fix_console():
    """让 Windows 控制台按 UTF-8 输出中文。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    return sys.stdout
