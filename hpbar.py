# -*- coding: utf-8 -*-
"""血条读数：画面不给对方血量数字，只能从血条长度读比例。

关键点：血条 = **已填充段 + 空槽段**。只找"亮色"会把空槽丢掉，
于是比例永远是 1.0（血少了还会直接找不到）。所以先找**整条血条的矩形**，
再在矩形里测已填充的长度。

做法（不依赖具体分辨率）：
  1. 只在**顶部带**（y < 22%h）里找，那里只有双方血条和名字。
  2. 每行的"背景色"取该行中位数（屏幕底色占绝大多数），
     偏离背景色足够多的像素算"不是背景"，其中最长连续段超过画面宽 1/5
     的就是一条血条（名字文字的连续段很短，会被这条规则排除）。
  3. 在血条矩形里取中间行，从左边起数**亮且有色**的连续像素 = 已填充长度。
  4. 比例 = 已填充长度 / 血条总长。

已知局限：带护盾/多段高亮的血条比例会偏一点，调用方应把结果当**估算**展示。
"""
import numpy as np

MIN_BAR_FRAC = 0.18      # 整条血条至少占画面宽度的 18%
BG_TOL = 14              # 与整带背景色的差异阈值（RGB 三通道平均差）
BRIGHT = 85              # 填充色亮度下限
SAT = 0.15               # 填充色饱和度下限（排除灰色/暗色）


def _band_bg(band):
    """顶部带的背景色：取整带的**众数**颜色。

    不能按行取中位数 —— 血条常常占该行一半以上的像素，
    中位数会变成血条色，于是"空槽"被当成背景丢掉（血少时整条都找不到）。
    整带里血条只占几行，底色仍然占绝对多数，众数才稳。
    """
    flat = band.reshape(-1, 3).astype(np.uint8)
    q = (flat >> 3).astype(np.int32)          # 粗量化，避免浮点噪声碎成一片
    key = q[:, 0] * 65536 + q[:, 1] * 256 + q[:, 2]
    vals, counts = np.unique(key, return_counts=True)
    k = vals[counts.argmax()]
    # 用该量化桶内像素的均值还原真实颜色
    sel = flat[key == k]
    return sel.mean(axis=0)


def _not_bg_mask(row, bg, tol=BG_TOL):
    diff = np.abs(row.astype(np.int16) - bg).mean(axis=1)
    return diff > tol


def _fill_mask(row):
    """亮且有色 → 血条已填充部分。"""
    a = row.astype(np.int16)
    mx = a.max(axis=1)
    mn = a.min(axis=1)
    sat = (mx - mn) / np.maximum(mx, 1)
    return (mx > BRIGHT) & (sat > SAT)


def _runs(mask, min_len=1):
    """返回该行所有长度 ≥ min_len 的连续 True 段 [(start, end), ...]。

    注意不能只取最长的一段：屏幕上同时有左右两条血条，
    长的那条会把短的那条挤掉（左血条就是这么丢的）。
    """
    if not mask.any():
        return []
    idx = np.flatnonzero(mask)
    segs = np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1)
    return [(int(s[0]), int(s[-1]) + 1) for s in segs if len(s) >= min_len]


def _longest_run(mask, min_len=1):
    """返回最长连续 True 段的 (start, end)；没有就 (None, None)。"""
    r = _runs(mask, min_len)
    if not r:
        return None, None
    return max(r, key=lambda se: se[1] - se[0])


def find_bars(img, top_frac=0.22, side=None):
    """找出顶部带里的血条。

    side: "left" / "right" / None（两边都找）。
    返回 [{"side","left","right","top","bottom","ratio","filled"}]，按 y 排序。
    """
    arr = np.asarray(img.convert("RGB"))
    h, w = arr.shape[:2]
    band = arr[: max(1, int(h * top_frac))]
    min_len = int(w * MIN_BAR_FRAC)
    bg = _band_bg(band)

    boxes = []
    for y in range(band.shape[0]):
        row = band[y]
        for s, e in _runs(_not_bg_mask(row, bg), min_len):
            hit = None
            for b in boxes:
                # 与已有框横向重叠够多就认为是同一条血条
                ov = min(b["right"], e) - max(b["left"], s)
                if ov > 0.6 * min(b["right"] - b["left"], e - s):
                    hit = b
                    break
            if hit is None:
                boxes.append({"left": s, "right": e, "top": y, "bottom": y, "n": 1})
            else:
                hit["left"] = min(hit["left"], s)
                hit["right"] = max(hit["right"], e)
                hit["bottom"] = y
                hit["n"] += 1

    out = []
    for b in boxes:
        cx = (b["left"] + b["right"]) / 2.0
        key = "left" if cx < w / 2 else "right"
        if side and key != side:
            continue
        ymid = (b["top"] + b["bottom"]) // 2
        row = band[ymid]
        seg = row[b["left"]:b["right"]]
        fm = _fill_mask(seg)
        total = fm.size
        # 从左边数连续填充（血条从右往左掉，所以填充一定贴着左边）
        filled = 0
        for v in fm:
            if v:
                filled += 1
            else:
                break
        # 用总亮像素数兜底：万一左端有描边导致第一格不是亮色
        bright_total = int(fm.sum())
        ratio = (filled or bright_total) / total if total else 0.0
        out.append({"side": key, "left": b["left"], "right": b["right"],
                    "top": b["top"], "bottom": b["bottom"],
                    "filled": filled, "bright_all": bright_total,
                    "ratio": round(float(ratio), 4), "rows": b["n"]})
    out.sort(key=lambda d: d["top"])
    return out


def ratio_of(img, side):
    """某一侧的血条比例（0~1）。读不到返回 None。"""
    bars = find_bars(img, side=side)
    return bars[0]["ratio"] if bars else None


def foe_ratio(img):
    return ratio_of(img, "right")


def my_ratio(img):
    return ratio_of(img, "left")


def _selftest():
    from PIL import Image, ImageDraw
    W, H = 1000, 200
    im = Image.new("RGB", (W, H), (10, 8, 30))
    d = ImageDraw.Draw(im)
    # 左条：总长 300，填 70%
    d.rectangle([40, 40, 340, 60], fill=(18, 52, 28))
    d.rectangle([40, 40, 250, 60], fill=(90, 230, 110))
    # 右条：总长 360，填 35%
    d.rectangle([600, 40, 960, 60], fill=(58, 18, 24))
    d.rectangle([600, 40, 726, 60], fill=(240, 180, 60))
    d.text((45, 8), "Lv.100 测试精灵", fill=(240, 240, 240))
    d.text((610, 8), "Lv.100 对手名字更长一点", fill=(240, 240, 240))
    print("期望 左≈0.700 右≈0.350")
    for b in find_bars(im):
        print("   ", b)


if __name__ == "__main__":
    import sys

    from console import fix_console; fix_console()

    if len(sys.argv) > 1:
        from PIL import Image
        im = Image.open(sys.argv[1])
        print("血条:", find_bars(im))
    else:
        _selftest()
