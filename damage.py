# -*- coding: utf-8 -*-
"""伤害计算引擎。

公式出处（data/rules/赛尔号PVE概论.wiki「伤害计算和BOSS出招逻辑 → 红伤计算公式」原文）：
  ((攻击方实际等级×0.4+2)×技能威力×攻击方攻击÷防御方防御÷50+2)×本系加成×克制系数×随机系数×暴击系数
计算出来的是裸伤（基准值）。

**入参必须是实际面板，不是种族值。** 面板换算见 repo.stats（公式出处 [[培养机制]]）。
早期版本直接把种族值代进「攻击÷防御」，那是错的：分母太小，伤害会系统性地偏小。
正确口径是双方都取满级满学习力的实际能力值。

- 本系加成：1.5（技能属性属于自身任一属性即算本系）
- 随机系数：217~255 除以 255（只有整数），即 0.85098~1.0
- 克制系数：见 rules.elem_coef（0 / 0.25 / 0.5 / 1 / 2 / 4）
- 暴击系数：按 2.0（wiki 该页未写明，待实战回验）

**待校准**：公式本身是 PVE 口径，PVP 里精灵身上还挂着套装/刻印/魂印的
百分比加成，这些没有逐件建模，统一压成一个整体比例常数 K。
`calibrate.py` 用实测伤害反推 K（observed ≈ K × theoretical），
把结果写回下面的 K 即可。K 未定前，输出**相对大小可信、绝对数值待定**。
"""
import rules as R

# ------------------------------------------------------------------ 公式参数
LEVEL = 100
RANDOM_NUM_MIN, RANDOM_NUM_MAX = 217, 255
RANDOM_MIN = RANDOM_NUM_MIN / RANDOM_NUM_MAX
RANDOM_MAX = 1.0
# ---- 全局校准常数 K ----
# 唯一没建模的部分：套装 / 刻印 / 魂印 / 能力等级带来的整体倍率。
# 反推锚点（bilibili 实战截图 3）：
#   万霆神律·雷伊 「雷·裂阳圣耀」威力90 本系 克制×1.25 → 妙时天女
#   模型 K=1 给期望 161，画面读到红字 285 ⇒ K ≈ 1.76
# 但该回合雷伊可能已处于强化状态（会虚高 K），所以不能只取一个点。
# 折中做法：把 K 当区间用，区间下沿 1.0（无任何额外加成）→ 上沿 1.76。
# 引擎因此输出"伤害区间"，用于击杀判定时天然偏保守。
K_LO = 1.0
K_HI = 1.76
K = (K_LO + K_HI) / 2.0      # 点估计（用于打分排序）

def stab_mult():
    return R.STAB


# ------------------------------------------------------------------ 属性
def is_stab(spirit_element, skill_element):
    """本系判断：技能属性属于自身任一属性即算本系。

    双边都可能是双属性（如 圣灵·电 的精灵用 圣灵·电 的技能），
    所以两边都拆开，取交集非空即本系。
    """
    if not spirit_element or not skill_element:
        return False
    se = R.norm_element(spirit_element)
    ke = R.norm_element(skill_element)
    sparts = set(se.split("·")) if "·" in se else {se}
    kparts = set(ke.split("·")) if "·" in ke else {ke}
    return bool(sparts & kparts)


# ------------------------------------------------------------------ 伤害
def base_damage(level, power, atk, dfn):
    """裸伤公式（wiki 原文）。"""
    return (level * 0.4 + 2.0) * power * atk / dfn / 50.0 + 2.0


def damage_range(level, power, atk, dfn, coef=1.0, stab=False,
                 mults=(), crit=False,
                 random_low=RANDOM_MIN, random_high=RANDOM_MAX, k=None):
    """返回 (最小, 期望, 最大) 伤害。

    atk / dfn  实际面板（见模块 docstring）
    coef       属性克制系数
    stab       是否本系
    mults      其它独立乘算的增伤/减伤倍率（1.5 = +50%，0.5 = 减半）
    k          显式指定校准常数；不给就在 [K_LO, K_HI] 区间上取值，
               于是返回的 最小/最大 同时覆盖"校准不确定度"。
    """
    if power <= 0:
        return (0, 0, 0)
    m = 1.0
    if stab:
        m *= R.STAB
    m *= coef
    for x in mults:
        m *= x
    if crit:
        m *= R.CRIT_MULT
    if k is None:
        k_lo, k_hi = K_LO, K_HI
        k_mid = K
    else:
        k_lo = k_hi = k_mid = k
    base = base_damage(level, power, atk, dfn)
    lo = int(base * m * k_lo * random_low)
    hi = int(base * m * k_hi * random_high)
    mid = int(base * m * k_mid * (random_low + random_high) / 2)
    return (lo, mid, hi)


def damage_span(level, power, atk_lo, atk_hi, dfn_lo, dfn_hi,
                coef_lo=1.0, coef_hi=1.0, stab=False, crit=False,
                power_hi=None, mults_lo=(), mults_hi=()):
    """区间伤害：把"攻/防/克制/K/随机/威力/增伤"各端配成最不利与最有利。

    最低 = 攻低 · 防高 · 克制低 · K 低 · 随机低 · 增伤低
    最高 = 攻高 · 防低 · 克制高 · K 高 · 随机高 · 增伤高
    这里不再用"点估计 ± 比例"，而是把已知的不确定度一个个显式列出来，
    输出可以直接拿去判断"这一招杀不杀得掉"。

    power_hi    条件型"威力提高 N 点"（如「拥有点亮的雷辰时威力提高160点」）
                只抬高端；给了它，低端仍按基础威力算。
    mults_lo/hi 额外的成组乘区（属性技的强化铺垫等），与 atk/coef 之间是连乘。
    """
    if power <= 0:
        return (0, 0, 0)
    p_hi = power if power_hi is None else max(power, power_hi)

    def one(power_used, atk, dfn, coef, k, rnd, mults):
        m = 1.0
        if stab:
            m *= R.STAB
        m *= coef
        for x in mults:
            m *= x
        if crit:
            m *= R.CRIT_MULT
        base = base_damage(level, power_used, atk, dfn)
        return base * m * k * rnd

    lo = int(one(power, max(1.0, atk_lo), max(1.0, dfn_hi), coef_lo, K_LO,
                 RANDOM_MIN, mults_lo))
    hi = int(one(p_hi, max(1.0, atk_hi), max(1.0, dfn_lo), coef_hi, K_HI,
                 RANDOM_MAX, mults_hi))
    mid = int(one((power + p_hi) / 2, max(1.0, (atk_lo + atk_hi) / 2),
                  max(1.0, (dfn_lo + dfn_hi) / 2),
                  (coef_lo + coef_hi) / 2, K, (RANDOM_MIN + RANDOM_MAX) / 2,
                  tuple((a + b) / 2 for a, b in
                        zip(mults_lo or (1.0,) * len(mults_hi),
                            mults_hi or (1.0,) * len(mults_lo))) or ()))
    return (lo, mid, max(hi, mid))


def solve_k(power, atk, dfn, observed, coef=1.0, stab=False, mults=(),
            level=LEVEL, random_used=(RANDOM_MIN + RANDOM_MAX) / 2):
    """由一组实测伤害反推 K。

    多组样本应给出接近的 K；把区间写回 K_LO / K_HI 即可完成校准。
    """
    base = base_damage(level, power, atk, dfn)
    m = (1.0 if not stab else R.STAB) * coef
    for x in mults:
        m *= x
    denom = base * m * random_used
    return (observed / denom) if denom else float("nan")
