# -*- coding: utf-8 -*-
"""查询层：给判断引擎用的数据访问。

对外只暴露"精灵卡"与"技能"两种结构，避免上层直接接触 SQL。
"""
import difflib
import functools
import re

import db

# OCR 常见误识别字符：·  ・ 和空格统一抹掉再比对
_SEP = re.compile(r"[·・\.\s\-—_()（）\[\]【】]")
# OCR 易混字对（左为可能是错的，右为正确候选），用于二次匹配
CONFUSE = {"镟": "璇", "璇": "镟", "曜": "耀", "耀": "曜", "曦": "羲",
           "巳": "己", "己": "巳", "氏": "氐", "氐": "氏", "祇": "袛"}


def norm(s):
    return _SEP.sub("", (s or "").strip())


@functools.lru_cache(maxsize=1)
def _all_names():
    c = db.connect()
    rows = [(r["id"], r["name"], norm(r["name"])) for r in
            c.execute("SELECT id, name FROM spirits WHERE name IS NOT NULL")]
    c.close()
    return rows


@functools.lru_cache(maxsize=1)
def _norm_index():
    return {n: (sid, name) for sid, name, n in _all_names()}


def match_spirit(text, cutoff=0.62, topk=3):
    """把 OCR 出来的名字对到精灵表。

    返回 [(spirit_id, name, score), ...]，按分数降序；空表示没匹配上。
    """
    if not text:
        return []
    q = norm(text)
    if not q:
        return []
    idx = _norm_index()
    exact = idx.get(q)
    if exact:
        return [(exact[0], exact[1], 1.0)]

    cands = {}
    # 1) 去掉 Lv.100 之类的杂质后再试
    q2 = norm(re.sub(r"Lv\.?\s*\d+", "", text, flags=re.I))
    if q2 and q2 != q and q2 in idx:
        sid, nm = idx[q2]
        return [(sid, nm, 1.0)]

    # 2) 前缀/包含匹配（走索引，快）
    c = db.connect()
    for probe in {q, q[:4], q[:3], q[:2]}:
        if len(probe) < 2:
            continue
        for r in c.execute("SELECT id, name FROM spirits WHERE name LIKE ? LIMIT 60",
                           (probe + "%",)):
            cands[r["id"]] = r["name"]
        for r in c.execute("SELECT id, name FROM spirits WHERE name LIKE ? LIMIT 60",
                           ("%" + probe + "%",)):
            cands[r["id"]] = r["name"]
        if len(cands) >= 8:
            break
    c.close()

    pool = [(sid, nm, norm(nm)) for sid, nm in cands.items()] or \
        [(sid, nm, n) for sid, nm, n in _all_names()]
    scored = []
    for sid, nm, n in pool:
        sc = difflib.SequenceMatcher(None, q, n).ratio()
        # 包含关系加权：OCR 多字或少字时更稳
        if q and (q in n or n in q):
            sc = max(sc, 0.86 * min(len(q), len(n)) / max(len(q), len(n)) + 0.14)
        if sc >= cutoff:
            scored.append((sid, nm, round(sc, 4)))
    scored.sort(key=lambda x: (-x[2], len(x[1])))
    return scored[:topk]


def _effects_text(ids):
    if not ids:
        return ""
    c = db.connect()
    qs = ",".join("?" * len(ids))
    rows = c.execute(f"SELECT effect_text FROM skills WHERE id IN ({qs})", ids).fetchall()
    c.close()
    return " | ".join(r["effect_text"] for r in rows if r["effect_text"])


def _role_of(tail):
    """把 wiki 技能位的 tail 字段归一成角色名。

    wiki 的 {{精灵}} 模板里，技能字段写作 `技能ID-学习等级-角色`，
    第三个值就是官方给的定位标签，取值实测有：
      第五 / 先手 / 制敌 / 防御 / 强化 / 辅助 / 觉醒 / 自爆 / 追加 / 1
    归一化后剥掉连字符后缀（`先手-1` → `先手`，`追加第五` → `追加第五`）。
    """
    if not tail:
        return None
    t = str(tail).strip()
    if t.isdigit():
        return None
    return t.split("-")[0]


# 实战配招用到的角色标签。用户口径：一个强化 + 一个弹控 + 一个先手 + 一个大招 + 一个第五。
# 对应到 wiki 的标签体系：强化=强化、弹控=防御、大招=制敌、第五=第五。
ROLE_TAGS = ("强化", "防御", "先手", "制敌", "第五")
ROLE_CN = {"强化": "强化", "防御": "弹控", "先手": "先手",
           "制敌": "大招", "第五": "第五",
           "辅助": "辅助", "觉醒": "觉醒", "自爆": "自爆"}


def common_skills(spirit_id):
    """取实战常用配招。

    优先按 wiki 角色标签挑（ROLE_TAGS）；某只精灵没有标签数据时，
    退化成"学习等级最高的 5 个技能"——实测这与标签法结果高度一致，
    因为赛尔号的高威力/功能性技能都排在最后几个学习等级上。

    按学习等级升序返回，与游戏里技能面板的顺序读感一致。
    """
    rows = get_skills(spirit_id)
    tagged = [r for r in rows if _role_of(r.get("tail")) in ROLE_TAGS]
    if tagged:
        tagged.sort(key=lambda r: (r["learn_level"] or 0, r["slot"]))
        return tagged
    rows.sort(key=lambda r: (r["learn_level"] or 0, r["slot"]))
    return rows[-5:]


def get_skills(spirit_id, front5_only=False, limit=None):
    """取某精灵的技能列表（按 wiki 字段顺序）。

    front5_only: 只要实战常用配招（见 common_skills）。
    """
    c = db.connect()
    sql = """SELECT s.id, s.name, s.stype, s.element, s.power, s.pp, s.priority,
                    s.accuracy, s.effect_ids, s.effect_text, ss.slot, ss.learn_level, ss.tail
             FROM spirit_skills ss JOIN skills s ON s.id = ss.skill_id
             WHERE ss.spirit_id = ? ORDER BY ss.slot"""
    rows = [dict(r) for r in c.execute(sql, (spirit_id,))]
    c.close()
    for r in rows:
        r["role"] = _role_of(r.get("tail"))
    if front5_only:
        rows = common_skills(spirit_id)
    if limit:
        rows = rows[:limit]
    return rows


def match_skill(spirit_id, text, cutoff=0.6):
    """把 OCR 出来的技能名对到这只精灵自己的技能表上。

    只在这只精灵的技能里找，所以「黎阳圣耀」对上「裂阳圣耀」这种
    一个一个字的误识别也能靠相似度救回来。
    返回 (skill_dict, score) 或 (None, 0)。
    """
    if not text or not spirit_id:
        return None, 0.0
    q = norm(text)
    if not q:
        return None, 0.0
    skills = get_skills(spirit_id)
    best, bs = None, 0.0
    for s in skills:
        n = norm(s["name"])
        if not n:
            continue
        if n == q:
            return s, 1.0
        sc = difflib.SequenceMatcher(None, q, n).ratio()
        # 单字误识别的兜底：去掉错字后前缀一致（雷·裂阳圣耀 vs 雷·黎阳圣耀）
        if len(q) >= 3 and len(n) >= 3 and q[-2:] == n[-2:]:
            sc = max(sc, 0.72)
        if sc > bs:
            best, bs = s, sc
    if bs >= cutoff:
        best = dict(best)
        best["match_score"] = round(bs, 3)
        return best, bs
    return None, 0.0


def get_soul(spirit_id):
    """取精灵魂印文本（含减伤/增伤描述）。"""
    c = db.connect()
    rows = c.execute("""SELECT so.id, so.text, so.effect_ids FROM spirit_souls ss
                        JOIN souls so ON so.id = ss.soul_id WHERE ss.spirit_id = ?""",
                     (spirit_id,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_spirit(spirit_id):
    c = db.connect()
    r = c.execute("SELECT * FROM spirits WHERE id = ?", (spirit_id,)).fetchone()
    c.close()
    return dict(r) if r else None


def card(spirit_id, front5_only=True):
    """精灵卡：判断引擎的基本输入。"""
    sp = get_spirit(spirit_id)
    if not sp:
        return None
    sp["skills"] = get_skills(spirit_id, front5_only=front5_only)
    sp["souls"] = get_soul(spirit_id)
    return sp


def search_skill(name, limit=5):
    c = db.connect()
    rows = c.execute("SELECT id,name,stype,element,power,pp,priority,effect_text "
                     "FROM skills WHERE name LIKE ? LIMIT ?", (f"%{name}%", limit)).fetchall()
    c.close()
    return [dict(r) for r in rows]


def stats(species, level=100, ev=255, iv=31, nature=1.0, 异能加成=1.0):
    """由种族值折算实际面板。

    公式出处（[[培养机制]] wiki 原文）：
      攻/防/特攻/特防/速度：
        [ (种族×2 + 个体 + 学习力÷4 × 异能加成系数) × 等级 ÷ 100 + 5 ] × 性格修正，向下取整
      体力：
        [ (体力种族值×2 + 个体 + 学习力÷4) × 等级 ÷ 100 + 10 + 等级 ]，向下取整

    参数默认取"满级 + 满个体 + 满学习力"，这是巅峰之战的常见配置。
    nature 只作用于两攻（性格修正），需要时传入 1.1 / 0.9。

    实测校验（截图满血值）：
      万霆神律·雷伊 种族体力 176 → [(352+31+63)×100/100 + 10 + 100] = 556
      对应截图 1093/1093 —— 差 537，说明额外有约 96% 的加成（套装/刻印/魂印）。
      因此本函数给出的是**裸面板**，绝对数值需要按实测锚点做整体缩放，
      缩放系数见 game_scale()。
    """
    def core(base):
        return (base * 2 + iv + (ev // 4) * 异能加成) * level / 100

    def stat(base, nat=1.0):
        return int((core(base) + 5) * nat)

    return {
        "hp": int(core(species.get("hp") or 0) + 10 + level),
        "atk": stat(species.get("atk") or 0, nature),
        "def_": stat(species.get("def_") or 0),
        "spatk": stat(species.get("spatk") or 0, nature),
        "spdef": stat(species.get("spdef") or 0),
        "speed": stat(species.get("speed") or 0),
    }


def game_scale(spirit_id_or_card, observed_hp):
    """实战口径的整体缩放系数 = 实测满血 ÷ 裸面板体力。

    巅峰之战里精灵身上有套装/刻印/魂印的百分比加成，
    把这些统一压成一个整体系数，比逐件建模靠谱。
    """
    bare = stats(spirit_id_or_card if isinstance(spirit_id_or_card, dict)
                 else get_spirit(spirit_id_or_card))
    return observed_hp / max(1, bare["hp"])


# 实战体力量级相对裸面板的整体缩放（套装/刻印/魂印没逐件建模）。
# 由 calibrate.hp_scale() 反推：雷伊 1093/556 ≈ 1.97。
# 只用于"画面上读不到数字时"的兜底估值；读得到就一律用画面值。
HP_SCALE = 2.0


def hp_max(spirit_id_or_card, level=100, scale=None):
    """便捷入口：种族值 → 实际最大体力（可选整体缩放）。

    scale=None 时用 HP_SCALE。要裸面板就显式传 scale=1.0。
    """
    if isinstance(spirit_id_or_card, int):
        sp = get_spirit(spirit_id_or_card)
    else:
        sp = spirit_id_or_card
    if not sp:
        return None
    return int(stats(sp, level)["hp"] * (HP_SCALE if scale is None else scale))


def verify_stats():
    """用截图里能读到的真实数值校验体力公式。"""
    checks = [(3010, None), (4946, 1093), (4872, 1132)]
    out = []
    for sid, observed in checks:
        sp = get_spirit(sid)
        if not sp:
            continue
        bare = stats(sp)["hp"]
        out.append({"id": sid, "name": sp["name"], "species_hp": sp["hp"],
                    "bare": bare, "observed": observed,
                    "scale": round(observed / bare, 4) if observed else None})
    return out

