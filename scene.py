# -*- coding: utf-8 -*-
"""战斗画面 → 结构化局面。

输入是 OCR 出来的文字块（ocr.read 的返回值），输出是一个 state 字典，
正好可以喂给 decide.analyze。

版面（按用户提供的实战截图归纳，全部用**相对坐标**判定，不写死像素）：
  顶部带（y < 22%h）
      左半：`Lv.100 我方精灵名` + `当前血/上限血`
      中央：`第N回合`
      右半：`Lv.100 对方精灵名`（**对方没有明文血量**）
  底部带（y > 68%h）：四个技能格，每格 = 技能名 / `次数 x/y` / `威力 n`
  飘字（画面中部）：`克制-285` / `微弱-88` / `+551` / `-259`

刻意**不猜**的东西：
  · 对方的技能 PP、对方当前血量数值（画面不给，只能靠血条比例 + 推算上限）
  · 对方这回合用了什么（要点开才看得见，一律交给玩家手动标记）
"""
import re

import ocr

HP = re.compile(r"(\d{1,5})\s*[/|]\s*(\d{1,5})")
LV = re.compile(r"[Ll][Vv]\.?\s*(\d{1,3})")
TURN = re.compile(r"第\s*(\d{1,3})\s*回合")
# 名字里可能夹带等级前缀；中文名允许 · 连接
NAME_TAIL = re.compile(r"[Ll][Vv]\.?\s*\d{1,3}\s*([\u4e00-\u9fff·・A-Za-z0-9]{2,20})")


def _bands(items, h):
    """按纵向位置把文字块分到 顶/中/底 三带。"""
    top, mid, bot = [], [], []
    for it in items:
        t, s, x1, y1, x2, y2 = it
        yc = (y1 + y2) / 2.0
        (top if yc < 0.22 * h else bot if yc > 0.68 * h else mid).append(it)
    return top, mid, bot


def _img_h(items, default=520):
    ys = [it[5] for it in items]
    return max(ys) * 1.06 if ys else default


def parse(items, my_name_hint=None):
    """文字块 → 局面。

    返回:
      {
        "my":   {"name", "hp", "hp_max", "level"},
        "foe":  {"name", "level", "hp_ratio"},   # 对方血量只有比例
        "turn": int|None,
        "skills": [{"name","pp","pp_max","power","x"}] ,   # 底部四格（我方的）
        "floats": [{"sign","value","tag","x","y"}],        # 飘字
        "uncertain": [...],                                # 需要玩家确认的点
      }
    """
    h = _img_h(items)
    w = max([it[4] for it in items] or [1040]) * 1.04
    top, mid, bot = _bands(items, h)
    uncertain = []

    # ---- 名字与等级：从顶部带里找 Lv 后缀，左半是我方、右半是对方
    named = []
    for it in top:
        t, s, x1, y1, x2, y2 = it
        m = NAME_TAIL.search(t)
        lv = LV.search(t)
        if m:
            named.append({"name": m.group(1), "level": int(lv.group(1)) if lv else 100,
                          "x": x1, "conf": s})
        elif lv:
            # 只识别到 Lv.100，名字被切到隔壁块 —— 记下来交给上层按 x 就近拼
            named.append({"name": "", "level": int(lv.group(1)), "x": x1, "conf": s,
                          "bare_lv": True})
    named.sort(key=lambda n: n["x"])
    my, foe = None, None
    if named:
        my = named[0]
        foe = named[-1] if len(named) > 1 else None
    if my and not my["name"]:
        my["name"] = _name_near(items, my["x"], h)
        uncertain.append("我方精灵名是从「Lv」旁边拼出来的，请核对")
    if foe and not foe["name"]:
        foe["name"] = _name_near(items, foe["x"], h)
        uncertain.append("对方精灵名是从「Lv」旁边拼出来的，请核对")

    # ---- 我方血量：顶部带里的 a/b（a<=b）
    hp_pairs = []
    for it in top:
        t, s, x1, y1, x2, y2 = it
        for m in HP.finditer(t):
            a, b = int(m.group(1)), int(m.group(2))
            if a <= b and b >= 50:
                hp_pairs.append((a, b, x1, y1))
    hp_pairs.sort(key=lambda p: p[2])
    my_hp = my_hp_max = None
    if hp_pairs:
        my_hp, my_hp_max = hp_pairs[0][0], hp_pairs[0][1]
        if len(hp_pairs) > 1 and hp_pairs[1][2] > 0.55 * w:
            uncertain.append("画面右上出现了明文血量（通常对方没有），已忽略")

    # ---- 回合
    turn = None
    for it in list(top) + list(mid):
        m = TURN.search(it[0])
        if m:
            turn = int(m.group(1))
            break

    # ---- 底部：左下的圆形详情面板 + 四个技能格
    detail, skills = _split_bottom(bot, w, uncertain)

    # ---- 飘字
    floats = []
    for it in mid:
        t = it[0]
        m = re.search(r"([+-])\s*(\d{2,4})", t)
        if m:
            tag = ""
            for k in ("克制", "微弱", "普通"):
                if k in t:
                    tag = k
            floats.append({"sign": m.group(1), "value": int(m.group(2)),
                           "tag": tag, "x": it[2], "y": it[3]})

    return {
        "my": {"name": (my or {}).get("name"), "level": (my or {}).get("level", 100),
               "hp": my_hp, "hp_max": my_hp_max},
        "foe": {"name": (foe or {}).get("name"), "level": (foe or {}).get("level", 100)},
        "turn": turn,
        "skills": skills,
        "detail": detail,
        "floats": floats,
        "uncertain": uncertain,
    }


def _parse_detail_panel(items, w, h, x_frac=0.30, y_frac=0.58):
    """（保留旧入口）解析左下角的圆形技能详情面板。"""
    region = [it for it in items
              if it[4] <= x_frac * w and it[3] >= y_frac * h]
    return _detail_from(region)


def _split_bottom(bot, w, uncertain):
    """把底部带切成「左下圆形详情面板」和「技能格」。

    不能用固定的 x 分界线，也不适合按间隙切 —— 面板最右边的数字（次数/威力
    的数值）会贴到第一个技能格的左边，两者横向重叠。
    可靠的分界点是**第二个「次数」标签的左边**：面板的次数在最左，
    往左退一点就是面板与技能格的分界。
    """
    pp_items = sorted([it for it in bot if "次数" in it[0]], key=lambda it: it[2])
    split_at = None
    # 判据有两个，缺一不可：
    #   ① 最左边那个「次数」贴得很靠左（面板在画面最左下角，技能格的次数
    #      至少从 18% 宽度处才开始）—— 只看间隙的话，没有面板时第一格
    #      自己就会被误判成面板；
    #   ② 它和第二个「次数」之间有明显空档。
    if (len(pp_items) >= 3 and pp_items[0][2] < 0.13 * w
            and (pp_items[1][2] - pp_items[0][2]) > 0.09 * w):
        split_at = pp_items[1][2] - 0.06 * w

    if split_at is None:
        detail, cell_items = {}, bot
    else:
        # 按**左边缘**分边：面板最右边的数字（160）右边缘会越过分界，
        # 用右边缘判断会把它切给技能格。
        detail = _detail_from([it for it in bot if it[2] <= split_at])
        cell_items = [it for it in bot if it[2] > split_at]

    skills = _parse_skill_cells(cell_items, w, uncertain)
    if detail.get("name"):
        known = [s["name"] for s in skills]
        detail["slot"] = ("bottom" if any(k and detail["name"].endswith(k)
                                          for k in known) else "fifth")
    return detail, skills


def _value_right_of(region, row, pattern, dx_frac=0.16, img_w=1040):
    """数值和标签被 OCR 切成了两块时，去标签右边同一行找数值。"""
    best, bd = None, 1e9
    for it in region:
        if it is row:
            continue
        if abs(it[3] - row[3]) > 14:          # 不在同一行
            continue
        d = it[2] - row[4]                     # 只往右找
        if d < 0 or d > dx_frac * img_w:
            continue
        m = re.match(pattern, it[0].strip())
        if m and d < bd:
            best, bd = m, d
    return best


def _detail_from(region):
    """在给定文字块里解析圆形详情面板。

    用户强调过两次的排版规则：**「次数」这一行上方的所有文字全部属于技能名**
    （技能名会折行成两行，比如「帕诺」+「七星阵列」= 帕诺七星阵列，
    不要拆开乱猜）。下方是「次数 x/y」和「威力 n」。
    """
    if not region:
        return {}
    pp_row = None
    for it in sorted(region, key=lambda i: i[3]):
        if "次数" in it[0]:
            pp_row = it
            break
    out = {}
    if pp_row:
        m = HP.search(pp_row[0]) or _value_right_of(region, pp_row, r"(\d{1,5})[/|](\d{1,5})")
        if m:
            out["pp"], out["pp_max"] = int(m.group(1)), int(m.group(2))
        above = [it for it in region if it[5] <= pp_row[3]]
        above.sort(key=lambda it: it[3])
        name = "".join(it[0].strip() for it in above
                       if re.search(r"[\u4e00-\u9fff]", it[0]))
        if name:
            out["name"] = name
    y0 = pp_row[3] if pp_row else 0
    for it in sorted(region, key=lambda i: i[3]):
        if it[3] < y0:
            continue
        mp = re.search(r"威力\s*(\d{1,3})", it[0]) or \
            (_value_right_of(region, it, r"(\d{1,3})") if "威力" in it[0] else None)
        if mp:
            out["power"] = int(mp.group(1))
            break
    return out


def _name_near(items, lv_x, h, dx=260):
    """名字块被切开时，取同一行、离 Lv 最近的文字块当名字。"""
    best, bd = "", 1e9
    for t, s, x1, y1, x2, y2 in items:
        if y1 > 0.22 * h:
            continue
        if LV.search(t) or HP.search(t) or TURN.search(t):
            continue
        if not re.search(r"[\u4e00-\u9fff]", t):
            continue
        d = abs(x1 - lv_x)
        if d < bd and d <= dx:
            best, bd = t.strip(), d
    return best


def _parse_skill_cells(bot, w, uncertain):
    """底部四个技能格：技能名 + 次数 + 威力，按 x 就近配对。"""
    names, pps, powers = [], [], []
    for t, s, x1, y1, x2, y2 in bot:
        m = HP.search(t)
        if "次数" in t or (m and "威力" not in t):
            if m:
                pps.append({"pp": int(m.group(1)), "pp_max": int(m.group(2)),
                            "x": x1, "y": y1, "conf": s})
            continue
        mp = re.search(r"威力\s*(\d{1,3})", t)
        if mp:
            powers.append({"power": int(mp.group(1)), "x": x1, "y": y1})
            continue
        if re.search(r"[\u4e00-\u9fff]", t) and len(t) >= 2:
            names.append({"name": t.strip(), "x": x1, "y": y1, "conf": s})

    # 一格里名字在左、次数/威力在同一格下方 —— 按横向最近的 x 配对
    out = []
    for n in sorted(names, key=lambda d: d["x"]):
        p = _nearest(pps, n["x"], tol=0.14 * w)
        pw = _nearest(powers, n["x"], tol=0.14 * w)
        out.append({"name": n["name"], "pp": (p or {}).get("pp"),
                    "pp_max": (p or {}).get("pp_max"),
                    "power": (pw or {}).get("power"),
                    "x": n["x"], "conf": n["conf"]})
    if len(out) not in (4, 5):
        uncertain.append(f"底部识别到 {len(out)} 个技能格（通常 4~5 个），可能读漏")
    for s in out:
        if s["pp"] is None:
            uncertain.append(f"技能「{s['name']}」没读到次数")
    return out


def _nearest(rows, x, tol):
    best, bd = None, 1e9
    for r in rows:
        d = abs(r["x"] - x)
        if d < bd and d <= tol:
            best, bd = r, d
    return best


def read_image(path, my_name_hint=None):
    return parse(ocr.read(path), my_name_hint=my_name_hint)


def read_screen(win=None, client_only=True):
    """抓游戏窗口 → OCR → 局面。找不到窗口返回 (None, None)。"""
    import capture
    img = capture.grab_game(client_only=client_only) if win is None else \
        capture.grab(capture.client_rect(win.hwnd) or win.bbox)
    if img is None:
        return None, None
    tmp = _tmp_path()
    img.save(tmp)
    try:
        return parse(ocr.read(tmp)), img
    finally:
        try:
            import os
            os.remove(tmp)
        except OSError:
            pass


def _tmp_path():
    import os
    import tempfile
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "tmp")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "screen.png")


def describe(st):
    """给人看的摘要（命令行调试用）。"""
    if not st:
        return "(没有识别到画面)"
    my, foe = st["my"], st["foe"]
    hp = f"{my['hp']}/{my['hp_max']}" if my.get("hp") is not None else "血量未识别"
    lines = [f"第{st['turn']}回合" if st.get("turn") else "回合未识别",
             f"我：{my.get('name')} Lv.{my.get('level')}  {hp}",
             f"敌：{foe.get('name')} Lv.{foe.get('level')}  （画面无明文血量）"]
    if st["skills"]:
        lines.append("技能格：")
        for s in st["skills"]:
            pp = f"{s['pp']}/{s['pp_max']}" if s["pp"] is not None else "?/?"
            lines.append(f"   {s['name']}  次数{pp}  威力{s['power']}")
    if st["floats"]:
        lines.append("飘字：" + "  ".join(
            f"{f['tag']}{f['sign']}{f['value']}" for f in st["floats"]))
    d = st.get("detail") or {}
    if d.get("name"):
        lines.append(f"左下详情：{d['name']}  次数{d.get('pp')}/{d.get('pp_max')} "
                     f"威力{d.get('power')}  [{d.get('slot')}]")
    if st["uncertain"]:
        lines.append("需确认：")
        lines += [f"   ⚠ {u}" for u in st["uncertain"]]
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        st = read_image(sys.argv[1])
    else:
        st, _ = read_screen()
    print(describe(st))
