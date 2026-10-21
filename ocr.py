# -*- coding: utf-8 -*-
"""截图 OCR：把画面文字读出来。

引擎用 RapidOCR（onnxruntime 后端，体积小、无需 paddle）。
首次运行会自动下载/使用内置的 PP-OCRv4/v5 移动端模型。

用法：python ocr.py <图片路径> [--raw]
"""
import io
import os
import re
import sys

from console import fix_console; fix_console()

_OCR = None


def engine():
    """延迟加载 RapidOCR。"""
    global _OCR
    if _OCR is None:
        from rapidocr import RapidOCR
        _OCR = RapidOCR()
    return _OCR


def _flatten(res):
    """兼容 rapidocr 新老两种返回结构，统一成 [(text, score, box)]。"""
    out = []
    if res is None:
        return out
    # v3: 属性对象 boxes/txts/scores
    if hasattr(res, "boxes") and hasattr(res, "txts"):
        boxes = res.boxes if res.boxes is not None else []
        txts = res.txts if res.txts is not None else []
        scores = res.scores if res.scores is not None else []
        for box, t, s in zip(boxes, txts, scores):
            out.append((t, float(s), box))
        return out
    # v3: (result_list, elapse) 元组
    if isinstance(res, tuple) and len(res) == 2 and isinstance(res[0], (list, tuple)):
        res = res[0]
    for item in (res or []):
        # v1/v2: [box, (text, score)]
        if isinstance(item, (list, tuple)) and len(item) == 2 and isinstance(item[1], (list, tuple)):
            box, (t, s) = item
            out.append((t, float(s), box))
        elif isinstance(item, (list, tuple)) and len(item) == 3:
            box, t, s = item
            out.append((t, float(s), box))
    return out


def read(path):
    """返回 [(text, conf, x1, y1, x2, y2), ...]，坐标已转成左上原点像素。"""
    ocr = engine()
    try:
        res = ocr(path)
    except TypeError:
        res = ocr.predict(path)
    items = []
    for t, s, box in _flatten(res):
        try:
            pts = list(box)
            if len(pts) == 4 and not hasattr(pts[0], "__len__"):
                # [x1,y1,x2,y2] 形式
                x1, y1, x2, y2 = pts
            else:
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
        except Exception:  # noqa: BLE001
            x1 = y1 = x2 = y2 = 0
        items.append((t, s, float(x1), float(y1), float(x2), float(y2)))
    return items


NUM = re.compile(r"(\d+)")


def parse_battle(items):
    """从整屏文字里挑出战斗关键字段。"""
    d = {"hp_pairs": [], "levels": [], "turns": [], "dmg": [], "texts": [],
         "names_top": [], "skill_cells": []}
    for t, s, x1, y1, x2, y2 in items:
        d["texts"].append((t, round(s, 2), int(x1), int(y1)))
        y = int(y1)
        m = re.search(r"(\d+)\s*/\s*(\d+)", t)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a <= b:
                # 顶部血条区（y<200）才是体力；底部 y>440 的是技能次数，排除
                if y < 200:
                    d["hp_pairs"].append((a, b, int(x1), y))
                else:
                    d["skill_cells"].append(("pp", a, b, int(x1), y))
        if "Lv" in t or "LV" in t:
            d["names_top"].append((t, int(x1), y))
            m2 = re.search(r"(\d+)", t)
            if m2:
                d["levels"].append((int(m2.group(1)), t, int(x1), y))
        m = re.search(r"第\s*(\d+)\s*回合", t)
        if m:
            d["turns"].append((int(m.group(1)), int(x1), y))
        # 飘字：可带「克制/微弱」前缀，如 克制-285 / 微弱-88 / +551
        m = re.search(r"([+-])\s*(\d{2,4})\s*$", t.strip())
        if m:
            tag = ""
            for k in ("克制", "微弱", "普通"):
                if k in t:
                    tag = k
            d["dmg"].append((m.group(1), int(m.group(2)), tag, int(x1), y))
        # 底部技能名（y 在 420~475 之间）：名字里通常没有「次数/威力」
        if 420 <= y <= 475 and "次数" not in t and "威力" not in t:
            d["skill_cells"].append(("name", t, round(s, 2), int(x1), y))
    return d


def parse_pp(items):
    """次数 x/y 与技能名的配对（按 x 坐标就近）。"""
    d = parse_battle(items)
    names = [x for x in d["skill_cells"] if x[0] == "name"]
    pps = [x for x in d["skill_cells"] if x[0] == "pp"]
    out = []
    for kind, t, conf, x, y in names:
        best, bd = None, 1e9
        for _, a, b, px, py in pps:
            if abs(py - y) > 60:
                continue
            dist = abs(px - x)
            if dist < bd:
                best, bd = (a, b), dist
        out.append({"name": t, "conf": conf, "x": x, "pp": best})
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("用法: python ocr.py <图片> [--raw]")
    path = sys.argv[1]
    items = read(path)
    print(f"共 {len(items)} 个文字块")
    if "--raw" in sys.argv:
        for t, s, x1, y1, x2, y2 in items:
            print(f"  {s:.2f}  ({int(x1):>4},{int(y1):>4})-({int(x2):>4},{int(y2):>4})  {t}")
    else:
        d = parse_battle(items)
        print("体力:", d["hp_pairs"])
        print("等级:", d["levels"])
        print("回合:", d["turns"])
        print("伤害数字:", d["dmg"])
        print("技能格:")
        for c in parse_pp(items):
            print("   ", c)
