# -*- coding: utf-8 -*-
"""技能/魂印效果文本 → 结构化要点。

设计取舍：**不做完整机制求解器**。赛尔号效果有 2193 条，逐条建模仿真不可能做对。
这里只抽两类东西：
  1) 数值型要点（增伤、减伤、先制±、回血、固定伤害、护盾、吸血…）——能直接进伤害公式，
     或折算成"大致相当于多少伤害/血量"。
  2) 标记型要点（必中、免疫、弹控、控制、消强…）——只提示"有特殊效果"，交由玩家判断。

所有抽取都保留原文出处（raw），UI 上必须能点开看原句，避免误读。
"""
import re

_BR = re.compile(r"<br\s*/?>", re.I)
_TAG = re.compile(r"<[^>]+>")
_TPL = re.compile(r"\{\{效果说明\|([^}|]+)(?:\|[^}]*)?\}\}")
_NOTE = re.compile(r"\{\{[^}]*\}\}")


def clean_text(text):
    """把 wiki 里的 <br> / HTML 标签 / {{效果说明|X}} 模板清成纯文本。

    数值解析必须走这里：原始文本混着标签会导致百分比数字取错位置。
    """
    if not text:
        return ""
    t = _BR.sub("；", text)
    t = _TPL.sub(r"\1", t)
    t = _NOTE.sub("", t)
    t = _TAG.sub("", t)
    t = t.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">")
    t = re.sub(r"[ \t\u3000]+", "", t)
    t = re.sub(r"；{2,}", "；", t)
    return t.strip("； ")

# ---------------------------------------------------------------- 规则表
# (kind, 正则, 取值函数)  —— kind 是下游认得的键
RULES = [
    # 先制（必须先制后面紧跟 +数字，避免把"自身存活于场下时"这种句子误命中——
    #       老版本用宽松的 先制\s*[+＋]?\s*(\d+) 会把「存活于场下」里的 下+… 误判）
    ("priority", re.compile(r"先制(?:等级)?\s*[+＋](\d+)"), lambda m: int(m.group(1))),
    ("priority", re.compile(r"先制等级\s*(\d+)"), lambda m: int(m.group(1))),
    ("priority_neg", re.compile(r"先制(?:等级)?\s*-\s*(\d+)"), lambda m: -int(m.group(1))),
    # 增伤：造成伤害提高 X% / 伤害提升 X%
    ("dmg_up", re.compile(r"(?:造成|造成的|使用[^，。；]*?的)?(?:攻击)?伤害(?:提高|提升|增加|上升)\s*(\d+(?:\.\d+)?)\s*%"),
     lambda m: 1 + float(m.group(1)) / 100),
    ("dmg_up", re.compile(r"(?:威力|攻击威力)(?:提高|提升|增加)\s*(\d+(?:\.\d+)?)\s*%"),
     lambda m: 1 + float(m.group(1)) / 100),
    # 减伤：受到伤害减少 X%
    ("dmg_down", re.compile(r"(?:受到[^，。；]*?)?(?<!恢复)伤害(?:减少|降低|下降)\s*(\d+(?:\.\d+)?)\s*%"),
     lambda m: 1 - float(m.group(1)) / 100),
    ("dmg_down", re.compile(r"(?:受到[^，。；]*?)?伤害(?:减为|变为)\s*(\d+(?:\.\d+)?)\s*%"),
     lambda m: float(m.group(1)) / 100),
    ("dmg_down", re.compile(r"受到的?(?:所有)?(?:攻击)?伤害减半"), lambda m: 0.5),
    # 回血
    ("heal_pct", re.compile(r"恢复(?:自身)?(?:最大)?体力(?:值的)?\s*(\d+(?:\.\d+)?)\s*%"),
     lambda m: float(m.group(1)) / 100),
    ("heal_fix", re.compile(r"恢复\s*(\d+)\s*点体力"), lambda m: int(m.group(1))),
    ("heal_pct", re.compile(r"恢复自身最大体力的?\s*(\d+(?:\.\d+)?)\s*/\s*(\d+)"),
     lambda m: float(m.group(1)) / float(m.group(2))),
    # 吸血 / 汲取 / 百分比伤害
    ("drain", re.compile(r"(?:吸取|汲取|吸血)[^，。；]*?(\d+)\s*点体力"), lambda m: int(m.group(1))),
    ("drain_pct", re.compile(r"(?:吸取|汲取)[^，。；]*?体力(?:值的)?\s*(\d+(?:\.\d+)?)\s*%"),
     lambda m: float(m.group(1)) / 100),
    ("pct_dmg", re.compile(r"百分比伤害"), lambda m: True),
    ("fixed_dmg", re.compile(r"附加\s*(\d+)\s*点固定伤害"), lambda m: int(m.group(1))),
    ("fixed_dmg", re.compile(r"固定伤害"), lambda m: True),
    ("true_dmg", re.compile(r"真实伤害"), lambda m: True),
    # 反弹/反馈（如「将对手的攻击伤害50%反馈给对手」）
    ("reflect", re.compile(r"(?:将)?(?:对手|对方)的?攻击伤害\s*(\d+(?:\.\d+)?)\s*%\s*(?:反馈|反弹|反伤)"),
     lambda m: float(m.group(1)) / 100),
    ("reflect", re.compile(r"(?:反弹|反馈|反伤)"), lambda m: True),
    # 护盾
    ("shield", re.compile(r"(?:获得|生成|增加)\s*(\d+)\s*点护盾"), lambda m: int(m.group(1))),
    # 能力等级：必须紧贴数值，避免跨句乱抓
    ("stat_up", re.compile(r"([攻击特防速命])(?:击|攻|防|度|中)?\s*[+＋](\d+)"),
     lambda m: (m.group(1), int(m.group(2)))),
    ("stat_up", re.compile(r"全属性\s*[+＋](\d+)"), lambda m: ("全", int(m.group(1)))),
    # ---- 属性技（威力0）的收益来源：下面这几条都是"不造伤但有用"的效果
    # 威力点数加成：条件型只抬高端（如「拥有点亮的雷辰时威力提高160点」）
    ("power_add", re.compile(r"威力(?:提高|提升|增加)\s*(\d+)\s*点"), lambda m: int(m.group(1))),
    ("power_add", re.compile(r"此技能威力(?:提高|提升)\s*(\d+)"), lambda m: int(m.group(1))),
    # 令对手陷入控制类异常 → 对手本回合无法行动
    ("control_foe", re.compile(r"(?:令|使|对)?对手?[^，。；]{0,6}?(麻痹|害怕|睡眠|石化|瘫痪|冰封|失神|混乱|臣服)"),
     lambda m: m.group(1)),
    # 挡伤上限：「自身下1次受到的攻击伤害不超过300」
    ("dmg_cap", re.compile(r"受到的?攻击伤害不超过\s*(\d+)"), lambda m: int(m.group(1))),
    ("dmg_cap", re.compile(r"受到的?(?:固定|百分比)?伤害(?:、[^，。；]*?)?不超过\s*(\d+)\s*点"),
     lambda m: int(m.group(1))),
    # 回合类效果的持续回合数：「4回合内免疫并反弹所有受到的异常状态」
    ("turn_fx", re.compile(r"(\d+)\s*回合内(免疫|不受|无法被消除|无法被吸取|令对手[^，。；]{0,10}?无效|反弹|闪避)"),
     lambda m: (int(m.group(1)), m.group(2))),
    ("turn_fx", re.compile(r"(\d+)\s*回合内[^；。]{0,20}?(免疫|无效)"),
     lambda m: (int(m.group(1)), m.group(2))),
]

# 标记型关键词 → 中文说明
MARKS = [
    ("must_hit", ("必中",), "必中"),
    ("sure_crit", ("必定致命", "必定暴击"), "必定致命一击"),
    ("immunity", ("免疫",), "免疫"),
    ("control", ("害怕", "麻痹", "睡眠", "石化", "瘫痪", "冰封", "失神", "混乱", "臣服"), "控制类异常"),
    ("weak", ("弱化", "命中-", "防御-", "特防-"), "弱化"),
    ("dispel", ("消除对手", "消除自身", "解除"), "消除/解除"),
    ("counter", ("反弹", "弹控", "反伤"), "反弹类"),
    ("kill", ("秒杀",), "秒杀"),
    ("switch", ("驱逐", "放逐", "替换"), "强制换人"),
    ("ignore_shield", ("无视", "穿透"), "无视/穿透"),
    ("heal_lock", ("禁疗", "无法恢复"), "禁疗"),
]


def parse_text(text, source=""):
    """把一段效果文本解析成要点列表。

    返回 {"facts": [...], "marks": [...], "raw": text, "source": source}
    每条 fact: {"kind","value","text"}，text 是命中的原句（截断到 60 字）。
    """
    facts, marks = [], []
    if not text:
        return {"facts": facts, "marks": marks, "raw": text or "", "source": source}
    text = clean_text(text)
    seen = set()
    numeric_kinds = set()
    for kind, rx, get in RULES:
        for m in rx.finditer(text):
            try:
                val = get(m)
            except Exception:  # noqa: BLE001
                continue
            # 同一 kind 已经抓到更具体的数值时，跳过纯布尔命中（"固定伤害"泛命中）
            if isinstance(val, bool) and kind in numeric_kinds:
                continue
            key = (kind, str(val))
            if key in seen:
                continue
            seen.add(key)
            if not isinstance(val, bool):
                numeric_kinds.add(kind)
            facts.append({"kind": kind, "value": val,
                          "text": _sentence(text, m.start()),
                          "cond": _is_cond(text, m.start())})
    for kind, kws, label in MARKS:
        hit = [k for k in kws if k in text]
        if hit:
            marks.append({"kind": kind, "label": label, "hit": hit[0]})
    return {"facts": facts, "marks": marks, "raw": text, "source": source}


# 条件句标记：命中句里出现这些字，说明该数值只在特定局面下成立，
# 不能当成常驻倍率乘进伤害（否则会把"若对手处于XX状态则伤害翻倍"当成永久翻倍）。
# 只用强条件词：文字里「时 / 当 / 处于」太常见，会把无条件效果也误判成条件。
_COND = re.compile(r"若|如果|一旦|否则|每有|每次|则|需要|方可")


def _is_cond(text, pos):
    return bool(_COND.search(_sentence(text, pos, width=80)))


def _sentence(text, pos, width=60):
    """取命中位置所在的分句。"""
    start = max([text.rfind(c, 0, pos) for c in "；;。\n"] + [-1]) + 1
    end = min([x for x in (text.find(c, pos) for c in "；;。\n") if x >= 0] or [len(text)])
    s = text[start:end].strip()
    return s[:width]


def parse_skill(skill):
    """技能行 → 要点。技能里"先制"字段和文本都要看。

    坑：效果文本里的「下2回合令自身所有技能先制+2」说的是**授予未来回合**的先制，
    不是这一招自己的先制。老版本把它当成本技能先制，会让一个铺垫技被排到先手，
    出手顺序整个算错。这里把"授予型"标出来，只有技能行自带的 priority 字段
    才代表本技能的先制。
    """
    out = parse_text(skill.get("effect_text"), source=f"技能:{skill.get('id')}")
    facts = []
    for f in out["facts"]:
        if f["kind"] == "priority" and _GRANT.search(f.get("text") or ""):
            f = dict(f, kind="priority_grant")
        facts.append(f)
    pr = skill.get("priority") or 0
    if pr:
        facts.insert(0, {"kind": "priority", "value": int(pr),
                         "text": f"技能先制+{pr}"})
    out["facts"] = facts
    return out


# "授予未来回合"的先制：句子里出现这些词就不是本技能的先制
_GRANT = re.compile(r"下\s*\d+\s*回合|回合内令自身|令自身所有技能")


def _blank_agg():
    # dmg_up / dmg_down 是**无条件**常驻乘区；
    # *_hi / *_lo 把条件型效果也算进来，用于给出伤害区间的另一侧。
    # stat_up / control / dmg_cap / turn_fx 是**属性技（威力0）的收益来源**：
    # 这类招不造成伤害，收益全在"这回合少挨打"和"下回合更能打"，不能按零分处理。
    return {"dmg_up": 1.0, "dmg_up_hi": 1.0, "dmg_down": 1.0, "dmg_down_lo": 1.0,
            "priority": 0, "heal": 0, "shield": 0, "reflect": 0.0,
            "pct": False, "fixed": False, "true": False, "drain": 0,
            "marks": [], "cond_notes": [],
            "stat_up": {}, "control": False, "control_kind": "",
            "dmg_cap": 0, "power_add": 0, "power_add_cond": False,
            "turn_fx": [], "turn_fx_max": 0}


def agg_from(facts, marks=()):
    """把若干 fact 合并成一个乘区集合。

    **只能合并"同时生效"的来源**：一只精灵的魂印是被动常驻，可以合并进去；
    但它的 5 个技能各自的效果只在"用那一招的那一回合"生效，
    绝对不可以并到一起 —— 并了就会把 5 招的增伤连乘，伤害虚高好几倍。

    条件型效果（句子里有 若/则/每有…）不进无条件乘区，只进 hi/lo 区间，
    并在 cond_notes 里留一条可读的说明。
    """
    agg = _blank_agg()
    for f in facts:
        k, v = f["kind"], f["value"]
        cond = bool(f.get("cond"))
        if k == "dmg_up":
            agg["dmg_up_hi"] *= v
            if cond:
                agg["cond_notes"].append(f["text"])
            else:
                agg["dmg_up"] *= v
        elif k == "dmg_down":
            agg["dmg_down_lo"] *= v
            if cond:
                agg["cond_notes"].append(f["text"])
            else:
                agg["dmg_down"] *= v
        elif k == "priority":
            agg["priority"] = max(agg["priority"], v)
        elif k == "priority_neg":
            agg["priority"] = min(agg["priority"], v)
        elif k in ("heal_fix", "heal_pct", "drain", "drain_pct"):
            agg["drain"] += v if not isinstance(v, bool) else 0
        elif k == "shield":
            agg["shield"] += v
        elif k == "reflect":
            agg["reflect"] = max(agg["reflect"], v if not isinstance(v, bool) else 1.0)
        elif k == "pct_dmg":
            agg["pct"] = True
        elif k == "fixed_dmg":
            agg["fixed"] = True
        elif k == "true_dmg":
            agg["true"] = True
        elif k == "stat_up":
            stat, lv = v
            # 同一属性取最高等级：+2 覆盖 +1，不叠加（等级是状态不是加法）
            agg["stat_up"][stat] = max(agg["stat_up"].get(stat, 0), lv)
        elif k == "control_foe":
            agg["control"] = True
            agg["control_kind"] = v
        elif k == "dmg_cap":
            # 多个挡伤取最紧的那条
            agg["dmg_cap"] = v if not agg["dmg_cap"] else min(agg["dmg_cap"], v)
        elif k == "power_add":
            agg["power_add"] = max(agg["power_add"], v)
            if cond:
                agg["power_add_cond"] = True
                agg["cond_notes"].append(f["text"])
        elif k == "turn_fx":
            turns, what = v
            agg["turn_fx"].append(f"{turns}回合：{what}")
            agg["turn_fx_max"] = max(agg["turn_fx_max"], turns)
    agg["marks"] = sorted({m["label"] for m in marks})
    agg["cond_notes"] = sorted(set(agg["cond_notes"]))
    # turn_fx 会被多条正则命中同一条原文（如「3回合：令对手使用的属性技能无效」
    # 和「3回合：无效」）。同一个回合数只保留描述最完整的那条，否则提示会重复。
    best = {}
    for s in agg["turn_fx"]:
        head, _, what = s.partition("：")
        if len(what) > len(best.get(head, "")):
            best[head] = what
    agg["turn_fx"] = sorted(f"{h}：{w}" for h, w in best.items())
    return agg


def parse_card(card):
    """精灵卡 → {"skills": {技能id: 该招自己的乘区}, "soul": 魂印的常驻乘区, ...}

    返回结构刻意把两者分开：调用方算伤害时
        攻方 = 攻方魂印 × 正在用的那一招
        守方 = 守方魂印
    这才是机制上成立的口径。
    """
    skills = {}
    for s in card.get("skills", []):
        out = parse_skill(s)
        skills[s["id"]] = dict(out, agg=agg_from(out["facts"], out["marks"]))
    soul_facts, soul_marks = [], []
    for so in card.get("souls", []):
        out = parse_text(so.get("text"), source=f"魂印:{so.get('id')}")
        soul_facts += out["facts"]
        soul_marks += out["marks"]
    soul = agg_from(soul_facts, soul_marks)
    return {"skills": skills, "soul": soul,
            "soul_facts": soul_facts, "soul_marks": soul_marks}


def parse_card_flat(card):
    """兼容旧调用：只把魂印的常驻乘区 + 所有技能的效果文本要点摊平。

    注意返回的 agg **只含魂印**，不再把 5 个技能并进来（旧版就是这么错的）。
    """
    r = parse_card(card)
    return {"skills": r["skills"], "soul": r["soul_facts"], "agg": r["soul"]}
