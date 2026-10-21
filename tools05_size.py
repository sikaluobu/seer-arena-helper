# -*- coding: utf-8 -*-
"""看一眼打包出来的 exe 里到底塞了些什么，哪个最占体积。

用法：
    python tools05_size.py            # 看默认的 build/build/Analysis-00.toc
"""
from console import fix_console; fix_console()

import ast
import collections
import os
import sys

TOC = sys.argv[1] if len(sys.argv) > 1 else "build/build/Analysis-00.toc"


def main():
    with open(TOC, encoding="utf-8", errors="replace") as f:
        data = ast.literal_eval(f.read())

    # Analysis-00.toc 是个大 tuple，里面每一段是不同类型的 TOC
    # （binaries / datas / pure / zipfiles…），元素都是 (name, path, typecode)
    groups = []
    if isinstance(data, tuple):
        for g in data:
            if isinstance(g, list) and g and isinstance(g[0], (list, tuple)):
                groups.append(g)
    else:
        groups = [data]

    agg = collections.Counter()
    files = []
    total = 0
    seen = set()
    for g in groups:
        for it in g:
            if len(it) < 3:
                continue
            name, path, typ = str(it[0]), it[1], str(it[2])
            if path in seen:
                continue
            seen.add(path)
            try:
                sz = os.path.getsize(path) if path and os.path.exists(path) else 0
            except OSError:
                sz = 0
            top = name.replace("\\", "/").split("/")[0]
            agg[top] += sz
            total += sz
            files.append((sz, name))

    print(f"合计 {total / 1e6:.1f} MB / {len(seen)} 项")
    print("-" * 56)
    for k, v in agg.most_common(25):
        print(f"{v / 1e6:8.1f} MB  {k}")
    print("-" * 56)
    print("最大的单个文件：")
    for sz, name in sorted(files, reverse=True)[:20]:
        print(f"{sz / 1e6:8.1f} MB  {name}")


if __name__ == "__main__":
    main()
