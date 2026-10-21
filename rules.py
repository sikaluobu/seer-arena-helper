# -*- coding: utf-8 -*-
"""对战常数与机制规则，全部标注出处。

出处：data/rules/对战机制.wiki（wiki 原文，行号见注释）
     data/rules/模块_属性克制.lua（属性系数）
用户口述补充：各颜色的意思是 红=技能伤害、粉红=固定伤害/百分比伤害、白=真实伤害。
"""

# ---------------------------------------------------------------- 能力等级
# 公式（用户 m01198 口述，与 对战机制.wiki 的正等级描述一致，但补全了负等级）：
#     每有 x 级提升 → 该项属性 ×(x+2)/2
#     每有 x 级下降 → 该项属性 ×2/(2+x)
# 展开验证：
#     +1 → 1.5    +2 → 2.0    +3 → 2.5    +6 → 4.0
#     -1 → 2/3≈0.667  -2 → 0.5  -3 → 0.4  -6 → 0.25
# 老版本写的是 1 + 0.5*level，正等级对得上，**负等级完全错**：
# -2 会算成 0.0（伤害归零）、-6 算成 -2.0（负伤害）。
# 实际是"下降是除法不是减法"，永远降到 0 但不会到负。
ABILITY_STEP = 0.5
ABILITY_MIN, ABILITY_MAX = -6, 6


def ability_mult(level):
    """能力等级 → 该项属性数值的倍率（攻/防/特攻/特防/速度通用）。"""
    lv = max(ABILITY_MIN, min(ABILITY_MAX, level or 0))
    if lv >= 0:
        return (lv + 2) / 2.0
    return 2.0 / (2 + (-lv))


def atk_mult(level):
    """攻击/特攻/速度 等级 → 倍率。+2 -> 2.0，-2 -> 0.5。"""
    return ability_mult(level)


def def_mult(level):
    """防御/特防 等级 → 防御值倍率。+2 -> 2.0（受伤减半），-2 -> 0.5（受伤翻倍）。"""
    return ability_mult(level)


def speed_mult(level):
    """速度等级 → 出手速度倍率。"""
    return ability_mult(level)


# 命中：正等级每级 +50%；负等级 -1~-3 每级 -15%，-4~-6 每级 -10%
HIT_UP_STEP = 0.50
HIT_DOWN_STEPS = {1: 0.15, 2: 0.15, 3: 0.15, 4: 0.10, 5: 0.10, 6: 0.10}


def hit_mult(level):
    """命中等级 → 命中率倍率（作用于技能基础命中率）。"""
    level = max(ABILITY_MIN, min(ABILITY_MAX, level))
    if level >= 0:
        return 1.0 + HIT_UP_STEP * level
    loss = sum(HIT_DOWN_STEPS[i] for i in range(1, -level + 1))
    return max(0.0, 1.0 - loss)


# ---------------------------------------------------------------- 本系加成
# 对战机制.wiki：「如果自身系别与所使用攻击技能的系别相同，伤害会额外获得50%的本系加成」
STAB = 1.50

# ---------------------------------------------------------------- 出手顺序
# 对战机制.wiki：「先制较高的一方会优先出手，当双方先制相等时，速度值较高的一方会优先出手，
#                若速度值也相同，则随机出手」
# 先制是技能先制（叠加精灵先制/魂印/状态修正），比较大小。

# ---------------------------------------------------------------- 致命一击
# 技能页 暴击概率=1/16 为基准；致命一击倍率按 2.0（常规设定，待用实战伤害回验）
CRIT_MULT = 2.0
CRIT_RATE_DEFAULT = 1 / 16

# ---------------------------------------------------------------- 技能类型
ATK_TYPES = ("物理攻击", "特殊攻击")
STATUS_TYPE = "属性攻击"


def is_attack(stype):
    return stype in ATK_TYPES


def uses_atk_stat(stype):
    """物理攻击看攻击值/防御值，特殊攻击看特攻值/特防值。"""
    return stype == "物理攻击"


# ---------------------------------------------------------------- 属性克制
# 数据来源：data/coef.json（由 parse_lua_coef.py 从 wiki 模块:属性克制 解析）
import json as _json
import os as _os

_COEF_PATH = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                           "data", "coef.json")
try:                                    # 打包成 exe 后要走 paths.resource()
    from paths import resource as _resource
    _COEF_PATH = _resource("data", "coef.json")
except Exception:                       # noqa: BLE001
    pass
_coef_data = None


def _load_coef():
    global _coef_data
    if _coef_data is None:
        with open(_COEF_PATH, encoding="utf-8") as f:
            _coef_data = _json.load(f)
    return _coef_data


def norm_element(name):
    """把 OCR/录入的属性名规范成数据表里的键（单属性或 'A·B'）。"""
    if not name:
        return ""
    d = _load_coef()
    s = name.strip().replace("・", "·").replace(" ", "").replace("/", "·")
    if s in d["aliases"]:
        return d["aliases"][s]
    if s in d["coef"]:
        return s
    if "·" in s:
        parts = [p for p in s.split("·") if p]
        if len(parts) == 2:
            key = "".join(parts)
            if key in d["aliases"]:
                return d["aliases"][key]
            if parts[0] in d["coef"] and parts[1] in d["coef"]:
                return f"{parts[0]}·{parts[1]}"
        return s
    # 拼接型（如"机械地面"）尝试拆成两个单属性
    for a in d["single"]:
        if s.startswith(a):
            rest = s[len(a):]
            if rest in d["single"]:
                return d["aliases"].get(a + rest, f"{a}·{rest}")
    return s


def coef_of(attack_element, defense_element):
    """单属性 vs 单属性，走 coef 表的 attack/defense 子表。"""
    d = _load_coef()
    a = norm_element(attack_element)
    b = norm_element(defense_element)
    if a in d["coef"] and b in d["coef"]:
        return float(d["coef"][a]["attack"].get(b, 1.0))
    return None


def elem_coef(atk_element, def_element):
    """攻击方属性 → 防御方属性的克制系数（支持双属性）。

    双属性规则（模块_属性克制.lua 原文注释）：
      双 A·B vs 单 C：取 a=coef(A,C), b=coef(B,C)
        两者都 2 → 4；任一 0 → (a+b)/4；否则 (a+b)/2
      双 vs 双：分别按上面算出两个系数再取平均
      单 vs 双：同样两两算，取平均
    """
    d = _load_coef()
    A = norm_element(atk_element)
    B = norm_element(def_element)
    parts_a = A.split("·") if "·" in A else [A]
    parts_b = B.split("·") if "·" in B else [B]
    # 表里只有单属性的键；双属性必须拆开逐个查，不能拿整串去查表
    for p in parts_a + parts_b:
        if p not in d["coef"]:
            return 1.0
    if len(parts_a) == 1 and len(parts_b) == 1:
        v = coef_of(parts_a[0], parts_b[0])
        return 1.0 if v is None else v
    if len(parts_a) == 2 and len(parts_b) == 1:
        a = coef_of(parts_a[0], parts_b[0])
        b = coef_of(parts_a[1], parts_b[0])
        return _merge(a, b)
    if len(parts_a) == 1 and len(parts_b) == 2:
        a = coef_of(parts_a[0], parts_b[0])
        b = coef_of(parts_a[0], parts_b[1])
        return _merge(a, b)
    # 双 vs 双
    v1 = _merge(coef_of(parts_a[0], parts_b[0]), coef_of(parts_a[1], parts_b[0]))
    v2 = _merge(coef_of(parts_a[0], parts_b[1]), coef_of(parts_a[1], parts_b[1]))
    return round((v1 + v2) / 2, 4)


def _merge(a, b):
    if a is None or b is None:
        return 1.0
    if a == 2.0 and b == 2.0:
        return 4.0
    if a == 0.0 or b == 0.0:
        return round((a + b) / 4.0, 4)
    return round((a + b) / 2.0, 4)
