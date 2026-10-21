# -*- coding: utf-8 -*-
"""伤害公式校准：用截图里能读到的真实数字反推全局常数 K。

公式（[[赛尔号PVE概论]] 红伤计算公式）：
    ((等级×0.4+2) × 威力 × 攻 ÷ 防 ÷ 50 + 2) × 本系 × 克制 × 随机 × 暴击
面板换算（[[培养机制]]）已落在 repo.stats，公式里的攻/防取**实际面板**。

K 是唯一没建模的那部分：套装 / 刻印 / 魂印 / 能力等级带来的整体倍率。
用法：
    python calibrate.py            # 跑全部锚点，打印反推的 K
把打印出来的 K 写回 damage.K 即可。

锚点来源：用户提供的 bilibili 实战截图（可读到的伤害浮字）。
"""
import sys

from console import fix_console; fix_console()

sys.path.insert(0, ".")

import damage
import repo
import rules

# 每个锚点：攻方精灵名、技能名（部分匹配即可）、守方精灵名、画面读到的伤害、
# 以及画面/SkillEffect 里已知的额外乘数（不确定就留空，别瞎填）。
ANCHORS = [
    {
        "atk_spirit": "万霆神律·雷伊",
        "skill": "裂阳圣耀",
        "def_spirit": "妙时天女",
        "observed": 285,
        "tag": "截图3「克制-285」，顶部倍率条 克制 1.25",
        "mults": [],
        "note": "雷伊此时可能处于强化状态，反推的 K 是上界",
    },
]


def _spirit(name):
    rows = [r for r in repo._all_names() if r[1] == name]
    return repo.get_spirit(rows[0][0]) if rows else None


def _skill(spirit_id, frag):
    for s in repo.get_skills(spirit_id):
        if frag in (s["name"] or ""):
            return s
    return None


def solve(verbose=True):
    """对每个锚点反推 K，返回列表。"""
    out = []
    for a in ANCHORS:
        atk = _spirit(a["atk_spirit"])
        dfn = _spirit(a["def_spirit"])
        if not atk or not dfn:
            if verbose:
                print(f"  [跳过] 库里找不到 {a['atk_spirit']} 或 {a['def_spirit']}")
            continue
        sk = _skill(atk["id"], a["skill"])
        if not sk:
            if verbose:
                print(f"  [跳过] {a['atk_spirit']} 没有含「{a['skill']}」的技能")
            continue

        ap = repo.stats(atk)
        dp = repo.stats(dfn)
        uses_atk = rules.uses_atk_stat(sk.get("stype"))
        att = ap["atk"] if uses_atk else ap["spatk"]
        dfv = dp["def_"] if uses_atk else dp["spdef"]
        stab = damage.is_stab(atk["element"], sk["element"])
        coef = rules.elem_coef(sk["element"], dfn["element"])
        extra = 1.0
        for m in a["mults"]:
            extra *= m
        k = damage.solve_k(sk["power"], att, dfv, a["observed"],
                           coef=coef, stab=stab, mults=a["mults"],
                           random_used=(damage.RANDOM_MIN + damage.RANDOM_MAX) / 2)
        rec = {"anchor": a, "spirit": atk["name"], "skill": sk["name"],
               "power": sk["power"], "atk_stat": att, "def_stat": dfv,
               "stab": stab, "coef": coef, "observed": a["observed"], "K": k,
               "model_at_K1": damage.damage_range(
                   100, sk["power"], att, dfv, coef=coef, stab=stab,
                   mults=a["mults"], k=1.0)}
        out.append(rec)
        if verbose:
            lo, mid, hi = rec["model_at_K1"]
            print(f"  {atk['name']} 「{sk['name']}」(威力{sk['power']}) → {dfn['name']}")
            print(f"     攻 {att}  防 {dfv}  本系 {stab}  克制 ×{coef}  "
                  f"（{a['tag']}）")
            print(f"     K=1 时模型给 {lo}~{hi}(期望 {mid})，画面读到 {a['observed']}")
            print(f"     ⇒ 反推 K = {k:.3f}   {a['note']}")
    return out


def report():
    print("=== 伤害校准 ===")
    res = solve()
    if not res:
        print("  没有可用锚点")
        return
    ks = [r["K"] for r in res]
    print()
    print(f"  样本 K: {['%.3f' % k for k in ks]}")
    lo, hi = min(ks), max(ks)
    print(f"  建议写入 damage.K_LO = {lo:.3f}   damage.K_HI = {hi:.3f}"
          f"   （当前 {damage.K_LO} / {damage.K_HI}）")
    print("  锚点唯一时 K_LO 取 1.0（无任何额外加成的下界），避免单点过拟合。")


def hp_scale():
    """体力量级校准：裸面板 → 实战满血 的整体缩放。"""
    print()
    print("=== 体力量级校准（套装/刻印的整体缩放）===")
    # observed 是画面上能直接读到的满血/当前血数字。只有确实读到的才写进来。
    anchors = [
        ("万霆神律·雷伊", 1093, "截图3/4 左上角 1033/1093"),
        ("妙时天女", 1132, "截图4 右上角血条（数值需复核）"),
    ]
    vals = []
    for name, observed, src in anchors:
        sp = _spirit(name)
        if not sp:
            continue
        bare = repo.stats(sp)["hp"]
        r = observed / bare
        vals.append(r)
        print(f"  {name:<12} 种族体力{sp['hp']:>4} 裸面板 {bare:>4} "
              f"画面 {observed:>5} ⇒ 缩放 ×{r:.3f}   [{src}]")
    if vals:
        print(f"  ⇒ 建议 HP_SCALE ≈ {sum(vals) / len(vals):.2f}（仅用于读不到数字时的兜底）")
    print("  说明：两侧缩放不一致说明 wiki 种族值对应的形态/皮肤不同，"
          "或双方刻印配置不同。\n        实战里以画面读到的数字为准，"
          "估算只在读不到时兜底。")


if __name__ == "__main__":
    report()
    hp_scale()
