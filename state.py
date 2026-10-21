# -*- coding: utf-8 -*-
"""画面状态采集：把截图变成结构化的"当前局面"。

分工原则：
- 血量条比例、技能属性图标 → 读**像素**（OCR 读不出来）
- 精灵名、等级、体力数字、回合、技能名、次数 → 读**文字**（ocr.py）
- 推断对方面板值 → repo.stats()，并标注清晰/不清晰

坐标按 1040x520 左右的战斗画面比例给出，运行时按实际分辨率缩放。
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))

# 参照分辨率（bilibili 视频截图实测）
BASE_W, BASE_H = 1040, 520

# 血条区域（比例坐标 x1,y1,x2,y2），左右两条
HP_BAR = {
    "mine": (0.030, 0.016, 0.300, 0.043),
    "foe": (0.762, 0.016, 0.985, 0.043),
}
# 技能属性图标（底部四格左侧的六边形），比例坐标
ELEM_ICON = {
    "mine": [(0.175, 0.930, 0.205, 0.975), (0.362, 0.930, 0.392, 0.975),
             (0.552, 0.930, 0.582, 0.975), (0.740, 0.930, 0.770, 0.975)],
}

# 本机元素色卡（RGB），用于把画面上属性图标的颜色对回属性名。
# 初值是量级占位，真正落地前需要用游戏内属性图标取样校准（tools/sample_elem.py）。
ELEM_COLOR = {
    "火": (230, 90, 60), "水": (70, 140, 240), "草": (90, 200, 90),
    "电": (250, 220, 80), "飞行": (170, 200, 240), "地面": (200, 160, 100),
    "机械": (170, 180, 190), "冰": (140, 220, 240), "超能": (230, 130, 200),
    "战斗": (220, 120, 80), "光": (250, 240, 180), "暗影": (120, 110, 170),
    "神秘": (180, 150, 220), "龙": (200, 120, 140), "圣灵": (250, 230, 140),
    "混沌": (140, 90, 160), "自然": (140, 220, 140), "远古": (200, 190, 150),
    "王": (240, 200, 120), "邪灵": (170, 110, 150), "虚空": (110, 90, 130),
    "轮回": (190, 180, 220), "神灵": (250, 250, 220), "虫": (180, 210, 120),
}


def _load_pil():
    from PIL import Image
    return Image


class Frame:
    """一帧截图 + 比例换算。"""

    def __init__(self, path):
        Image = _load_pil()
        self.img = Image.open(path).convert("RGB")
        self.w, self.h = self.img.size
        self.path = path

    def box(self, rel):
        """比例坐标 → 像素坐标 (x1,y1,x2,y2)。"""
        x1, y1, x2, y2 = rel
        return (int(x1 * self.w), int(y1 * self.h),
                int(x2 * self.w), int(y2 * self.h))

    def crop(self, rel):
        return self.img.crop(self.box(rel))

    def avg_rgb(self, rel):
        c = self.crop(rel)
        px = list(c.getdata())
        if not px:
            return (0, 0, 0)
        n = len(px)
        return tuple(sum(p[i] for p in px) // n for i in range(3))


def hp_bar_ratio(frame, side="foe", green_min=(60, 140, 60), red_min=(120, 40, 40)):
    """按血条里"有色像素"的横向延伸算血量比例。

    游戏血条是渐变的红/绿/黄，做法：在血条中线扫一行，找最右端的着色像素。
    返回 0~1；无法判断返回 None。
    """
    x1, y1, x2, y2 = frame.box(HP_BAR[side])
    band = frame.img.crop((x1, y1, x2, y2))
    w, h = band.size
    rows = [h // 3, h // 2, 2 * h // 3]
    best = 0
    for ry in rows:
        last = -1
        for x in range(w):
            r, g, b = band.getpixel((x, ry))
            mx, mn = max(r, g, b), min(r, g, b)
            colored = (mx - mn) > 40 and mx > 60   # 有饱和度且不暗 = 血量部分
            if colored:
                last = x
        if last >= 0:
            best = max(best, last + 1)
    if best == 0:
        return None
    return round(best / w, 4)


def nearest_element(rgb):
    """颜色 → 属性名（最近的色卡）。返回 (属性名, 距离)。"""
    if not rgb:
        return None, 1e9
    best, bd = None, 1e9
    for name, ref in ELEM_COLOR.items():
        d = sum((rgb[i] - ref[i]) ** 2 for i in range(3)) ** 0.5
        if d < bd:
            best, bd = name, d
    return best, round(bd, 1)


def read_elements(frame, side="mine"):
    """读底部技能格的属性图标颜色。"""
    out = []
    for i, rel in enumerate(ELEM_ICON.get(side, [])):
        rgb = frame.avg_rgb(rel)
        name, dist = nearest_element(rgb)
        out.append({"slot": i, "rgb": rgb, "element": name, "dist": dist})
    return out


LV_RE = re.compile(r"Lv\.?\s*(\d+)", re.I)


def build_state(frame, ocr_read, own_card=None, foe_card=None):
    """把一帧截图 + OCR 结果组装成局面。

    ocr_read: 可调用对象，签名 (path) -> [(text,conf,x1,y1,x2,y2)]；传 ocr.read。
    own_card / foe_card: repo.card(...) 的结果，可为 None（未识别出来）。
    返回 dict，字段见下方注释。
    """
    items = ocr_read(frame.path)
    import ocr as ocr_mod
    d = ocr_mod.parse_battle(items)
    slots = ocr_mod.parse_pp(items)

    st = {
        "turn": d["turns"][0][0] if d["turns"] else None,
        "round_text": d["texts"],
        "own": {"name": None, "level": None, "hp": None, "hp_max": None,
                "hp_ratio": hp_bar_ratio(frame, "mine"), "card": own_card,
                "skills": []},
        "foe": {"name": None, "level": None, "hp": None, "hp_max": None,
                "hp_ratio": hp_bar_ratio(frame, "foe"), "card": foe_card,
                "skills": []},
        "damage_float": d["dmg"],
        "elements": read_elements(frame),
        "warnings": [],
    }

    # 顶部左右两条名字/等级：x 较小的属己方
    tops = sorted(d["names_top"], key=lambda t: t[1])
    if tops:
        lv = LV_RE.search(tops[0][0])
        st["own"]["level"] = int(lv.group(1)) if lv else None
        nm = LV_RE.sub("", tops[0][0]).strip()
        st["own"]["name"] = nm or None
    if len(tops) > 1:
        lv = LV_RE.search(tops[-1][0])
        st["foe"]["level"] = int(lv.group(1)) if lv else None
        nm = LV_RE.sub("", tops[-1][0]).strip()
        st["foe"]["name"] = nm or None

    # 体力数字：x 较小一组是己方
    hps = sorted(d["hp_pairs"], key=lambda t: t[2])
    if hps:
        st["own"]["hp"], st["own"]["hp_max"] = hps[0][0], hps[0][1]
    if len(hps) > 1:
        st["foe"]["hp"], st["foe"]["hp_max"] = hps[1][0], hps[1][1]

    # 对方没有明文数字，用血条比例 × 推算体力上限
    if st["foe"]["hp"] is None and foe_card:
        fmax = repo_hp_max(foe_card, st["foe"]["level"] or 100)
        if fmax and st["foe"]["hp_ratio"] is not None:
            st["foe"]["hp_max"] = fmax
            st["foe"]["hp"] = int(round(fmax * st["foe"]["hp_ratio"]))
            st["warnings"].append("对方体力为血条比例推算值，存在误差")

    # 技能格 → 对上精灵卡里的技能
    for side, card in (("own", own_card), ("foe", foe_card)):
        for s in slots:
            st[side]["skills"].append(s)
    return st


def repo_hp_max(card, level):
    import repo
    return repo.stats(card, level).get("hp") if card else None


def sample_icons(path, outdir=None):
    """把一张截图里的属性图标裁出来存盘，人工标注用。"""
    f = Frame(path)
    outdir = outdir or os.path.join(HERE, "data", "icons")
    os.makedirs(outdir, exist_ok=True)
    saved = []
    for i, rel in enumerate(ELEM_ICON["mine"]):
        p = os.path.join(outdir, f"icon_{i}.png")
        f.crop(rel).resize((64, 64)).save(p)
        saved.append(p)
    return saved
