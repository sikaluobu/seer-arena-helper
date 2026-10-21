# -*- coding: utf-8 -*-
"""判断与推荐引擎。

输入：双方精灵卡 + 场面状态（血量、PP、回合、已标记的对方技能）
输出：每个候选动作的后果估算 + 一个 max-min 稳健推荐

设计取舍（必须写在代码里，避免以后误以为这是完整模拟器）：
- 只对**伤害**做数值求解；异常状态/消强/换人代价等靠提示词交给玩家判断。
- 对方的 4+1 个技能是**候选池**，默认"对方可能出其中任意一个"，除非玩家手动标记。
- 自己未知的机制（魂印里的特殊状态、隐藏增伤）一律以"不确定"呈现，不假装算得准。
"""
import itertools

import damage
import effects
import repo
import rules


# ------------------------------------------------------------------ 数值
def panel(card, level=100):
    """精灵面板：血是实际最大体力（种族×6+37），其余五项是种族值本身。

    为什么其余项不换算：wiki 伤害公式里「攻击 ÷ 防御」直接吃种族值字段，
    见 damage.py 的说明。上下两层必须用同一口径，否则伤害会差一个数量级。
    """
    return repo.stats(card, level)


def _usable(skill, pp_left=None):
    if not rules.is_attack(skill.get("stype")):
        return True
    if pp_left is None:
        return True
    return pp_left > 0


def damage_of(attacker, defender, skill, atk_panel, def_panel,
              atk_elem=None, def_elem=None,
              atk_adj_lo=1.0, atk_adj_hi=None, def_adj_lo=1.0, def_adj_hi=None,
              crit=False, power_bonus=0, atk_levels=None, def_levels=None):
    """一个技能打出去的三档伤害 (最低, 期望, 最高)。

    atk_adj_* / def_adj_* 是外部（魂印常驻、正在用的那一招）给出的乘数。
    低端用 *_lo，高端用 *_hi；不给 hi 就取与 lo 相同（该项无不确定度）。
    power_bonus 是条件型"威力提高 N 点"，只抬高端。
    atk_levels / def_levels 是双方的能力等级字典（{"atk":+1,"def":-2,...}），
    按物理/特殊分别取对应的攻防项，套 (x+2)/2 与 2/(2+x)。
    """
    if atk_adj_hi is None:
        atk_adj_hi = atk_adj_lo
    if def_adj_hi is None:
        def_adj_hi = def_adj_lo
    if not rules.is_attack(skill.get("stype")):
        return (0, 0, 0)
    power = skill.get("power") or 0
    if power <= 0:
        return (0, 0, 0)
    if rules.uses_atk_stat(skill.get("stype")):
        a = atk_panel["atk"]
        d = def_panel["def_"]
        akey, dkey = "atk", "def"
    else:
        a = atk_panel["spatk"]
        d = def_panel["spdef"]
        akey, dkey = "spatk", "spdef"
    am = rules.atk_mult((atk_levels or {}).get(akey, 0))
    dm = rules.def_mult((def_levels or {}).get(dkey, 0))
    coef = rules.elem_coef(skill.get("element"), def_elem)
    return damage.damage_span(100, power,
                              a * atk_adj_lo * am, a * atk_adj_hi * am,
                              d * def_adj_lo * dm, d * def_adj_hi * dm,
                              coef_lo=coef, coef_hi=coef,
                              stab=damage.is_stab(atk_elem, skill.get("element")),
                              crit=crit,
                              power_hi=power + max(0, power_bonus or 0))


def speed_order(me, foe, my_skill, foe_skill,
                my_levels=None, foe_levels=None):
    """返回 'me' / 'foe' / 'tie'，按先制→速度→随机。

    速度要乘上能力等级：速度+1 就是 ×1.5，会直接改变出手顺序。
    """
    mp = (my_skill.get("priority") or 0)
    fp = (foe_skill.get("priority") or 0)
    if mp != fp:
        return "me" if mp > fp else "foe"
    ms = me["speed"] * rules.speed_mult((my_levels or {}).get("speed", 0))
    fs = foe["speed"] * rules.speed_mult((foe_levels or {}).get("speed", 0))
    if ms != fs:
        return "me" if ms > fs else "foe"
    return "tie"



def status_gain(agg, my_panel):
    """属性技（威力 0）的收益折价。

    用户明确指出的口径：**配招里的两个属性技才是拿强化的手段**，
    「全属性+1」这种招本回合不造伤，但下回合伤害×1.5、受伤÷1.5，
    按"零伤害"给它打分等于把最强的招排到最后。

    这里把收益折算成"占最大体力的比例"，与伤害口径统一后一起进 max-min：
      控场（令对手麻痹/害怕…）→ 对手本回合出不了手，≈ 白赚一回合
      强化（攻/特攻/全属性+N）→ 下回合输出倍率
      强化（防/特防+N）       → 下回合受伤倍率
      挡伤上限 / 回合类免疫   → 本回合少挨的那部分
    """
    v = 0.0
    notes = []
    su = agg.get("stat_up") or {}

    def lv(*keys):
        return max((su.get(k, 0) for k in keys), default=0)

    atk_lv = lv("全", "攻", "特攻")
    if atk_lv > 0:
        m = rules.atk_mult(atk_lv)
        v += 0.30 * (m - 1.0) / 0.5
        notes.append(f"下回合攻击×{m:.2f}")
    def_lv = lv("全", "防", "特防")
    if def_lv > 0:
        m = rules.def_mult(def_lv)
        v += 0.20 * (1.0 - 1.0 / m) / (1.0 - 1.0 / 1.5)
        notes.append(f"下回合受伤÷{m:.2f}")
    spd_lv = lv("全", "速")
    if spd_lv > 0:
        v += 0.05
        notes.append(f"速度+{spd_lv}")
    if agg.get("control"):
        # 控场命中且对方没免疫 → 这回合完全不挨打，权重给到接近"白赚一击"
        v += 0.45
        notes.append(f"令对手{agg.get('control_kind')}（本回合无法行动）")
    if agg.get("dmg_cap"):
        v += 0.15
        notes.append(f"挡伤上限 {agg['dmg_cap']}")
    for t in (agg.get("turn_fx") or [])[:2]:
        v += 0.10
        notes.append(t)
    return min(v, 0.85), notes


def _status_outcomes(foe_replies, my_hp, agg, me=None, foe=None, my_skill=None,
                     my_levels=None, foe_levels=None):
    """属性技打出去、对方各招回应时的结果。

    与攻击技的区别：我不造成伤害，所以对方血量不变；
    但控场/挡伤会改变**我这一回合实际掉多少血**。

    控场要真的生效有个前提：**我得先出手**。对方比我快的话，
    这一下已经打完了，再控住他也追不回这回合的伤害。
    """
    outs = []
    capped = agg.get("dmg_cap") or 0
    for r in foe_replies:
        raw = r["dmg"][2]
        first = True
        if me is not None and foe is not None and my_skill is not None:
            first = speed_order(me, foe, my_skill, r["skill"],
                                my_levels, foe_levels) != "foe"
        if agg.get("control") and first and not r.get("foe_immune_control"):
            took = 0          # 对手被控住，出不了手
        elif capped:
            took = min(raw, capped)
        else:
            took = raw
        outs.append({"foe_skill": r["skill"], "order": "me" if first else "foe",
                     "my_hp_left": max(0, my_hp - took),
                     "foe_hp_left": None, "i_kill": False,
                     "i_die": took >= my_hp, "took": took})
    return outs


# ------------------------------------------------------------------ 主入口
def analyze(my_card, foe_card, state=None, foe_marks=None):
    """给出候选动作表 + 稳健推荐。

    state: {"my_hp", "my_hp_max", "foe_hp", "foe_hp_max", "my_level",
            "foe_level", "my_pp": {skill_id: 剩余}, "foe_marks": [已确认的对方技能名]}
    foe_marks: 玩家手动标记过的对方技能名列表（收窄候选池）。
    """
    state = state or {}
    mlv = state.get("my_level") or 100
    flv = state.get("foe_level") or 100
    # 能力等级：{"atk":+1,"spatk":0,"def":0,"spdef":-1,"speed":+2}
    my_levels = state.get("my_levels") or {}
    foe_levels = state.get("foe_levels") or {}
    me = panel(my_card, mlv)
    foe = panel(foe_card, flv)
    # panel 给的是裸面板；实战满血还要算上套装/刻印的整体缩放。
    # 画面上读得到数字时下面的 state 会覆盖掉这两个兜底值。
    me["hp"] = repo.hp_max(my_card, mlv)
    foe["hp"] = repo.hp_max(foe_card, flv)

    my_hp = state.get("my_hp") or me["hp"]
    my_hp_max = state.get("my_hp_max") or me["hp"]
    foe_hp = state.get("foe_hp") or foe["hp"]
    foe_hp_max = state.get("foe_hp_max") or foe["hp"]

    my_eff = effects.parse_card(my_card)
    foe_eff = effects.parse_card(foe_card)
    # 乘区口径：攻方 = 攻方魂印(常驻) × 正在用的那一招(仅该招生效)
    #           守方 = 守方魂印(常驻)
    # 绝不能把一只精灵 5 个技能的增伤乘到一起，那会把伤害吹高好几倍。
    # 条件型效果只进 hi/lo 区间，不进无条件乘区。
    my_soul = my_eff["soul"]
    foe_soul = foe_eff["soul"]

    def _up(eff, sk):
        a = (eff["skills"].get(sk["id"]) or {}).get("agg") or {}
        return a.get("dmg_up", 1.0), a.get("dmg_up_hi", 1.0)

    def _agg(eff, sk):
        return (eff["skills"].get(sk["id"]) or {}).get("agg") or {}

    foe_skills = _foe_pool(foe_card, foe_marks if foe_marks is not None
                           else state.get("foe_marks"))
    my_skills = my_card.get("skills", [])

    # 对方是否吃控场（魂印/常驻免疫）——决定属性技的控场收益能不能兑现
    foe_ctrl_immune = bool(foe_soul["marks"] and
                           ("免疫" in foe_soul["marks"] or "控制类异常" in foe_soul["marks"]))

    # ---- 我方每个技能打出去的伤害
    actions = []
    for sk in my_skills:
        pp = (state.get("my_pp") or {}).get(sk["id"])
        sa = _agg(my_eff, sk)
        u, u_hi = _up(my_eff, sk)
        lo, mid, hi = damage_of(my_card, foe_card, sk, me, foe,
                                atk_elem=my_card.get("element"),
                                def_elem=foe_card.get("element"),
                                atk_adj_lo=my_soul["dmg_up"] * u,
                                atk_adj_hi=my_soul["dmg_up_hi"] * u_hi,
                                def_adj_lo=foe_soul["dmg_down_lo"],
                                def_adj_hi=foe_soul["dmg_down"],
                                power_bonus=sa.get("power_add") or 0,
                                atk_levels=my_levels, def_levels=foe_levels)
        # 命中率折算
        acc = _acc(sk)
        worst = int(lo * acc)
        best = int(hi * acc)
        kill_now = worst >= foe_hp
        maybe_kill = best >= foe_hp
        is_attack = rules.is_attack(sk.get("stype")) and (sk.get("power") or 0) > 0
        act = {
            "kind": "skill" if is_attack else "status",
            "skill": sk,
            "pp_left": pp,
            "usable": _usable(sk, pp),
            "dmg": (lo, mid, hi),
            "dmg_hit_adj": (worst, best),
            "kill_guaranteed": kill_now,
            "kill_possible": maybe_kill,
            "priority": sk.get("priority") or 0,
            "status": sa,
            "value": 0.0,
            "notes": [],
        }
        if not is_attack:
            act["value"], act["notes"] = status_gain(sa, me)
        actions.append(act)

    actions.append({"kind": "switch", "skill": None, "usable": True,
                    "dmg": (0, 0, 0), "kill_guaranteed": False,
                    "kill_possible": False, "priority": None,
                    "value": 0.0, "notes": [],
                    "note": "换人：本回合不能出手，对手默认先手"})

    # ---- 对方候选技能的反击伤害（用于 max-min）
    foe_replies = []
    for sk in foe_skills:
        u, u_hi = _up(foe_eff, sk)
        fa = _agg(foe_eff, sk)
        lo, mid, hi = damage_of(foe_card, my_card, sk, foe, me,
                                atk_elem=foe_card.get("element"),
                                def_elem=my_card.get("element"),
                                atk_adj_lo=foe_soul["dmg_up"] * u,
                                atk_adj_hi=foe_soul["dmg_up_hi"] * u_hi,
                                def_adj_lo=my_soul["dmg_down_lo"],
                                def_adj_hi=my_soul["dmg_down"],
                                power_bonus=fa.get("power_add") or 0,
                                atk_levels=foe_levels, def_levels=my_levels)
        foe_replies.append({"skill": sk, "dmg": (lo, mid, hi),
                            "kill_me": lo >= my_hp,
                            "priority": sk.get("priority") or 0,
                            "is_attack": rules.is_attack(sk.get("stype"))
                                         and (sk.get("power") or 0) > 0,
                            "foe_immune_control": foe_ctrl_immune})

    # ---- 组装每个动作 × 每个对方回应 的后果
    for a in actions:
        if a["kind"] == "switch":
            a["outcomes"] = _switch_outcomes(a, foe_replies, my_hp)
            a["worst_hp_left"] = min(o["my_hp_left"] for o in a["outcomes"])
            continue
        if a["kind"] == "status":
            # 属性技：我不造伤，对方血量不变；关键是控场/挡伤让我少掉多少血
            a["outcomes"] = _status_outcomes(foe_replies, my_hp, a["status"],
                                             me, foe, a["skill"],
                                             my_levels, foe_levels)
            a["worst_hp_left"] = min(o["my_hp_left"] for o in a["outcomes"])
            a["kill_rate"] = 0.0
            a["die_rate"] = round(sum(1 for o in a["outcomes"] if o["i_die"])
                                  / max(1, len(a["outcomes"])), 3)
            continue
        outs = []
        for r in foe_replies:
            order = speed_order(me, foe, a["skill"], r["skill"],
                                my_levels, foe_levels)
            my_lo, my_hi = a["dmg_hit_adj"]
            e_lo, e_hi = r["dmg"][0], r["dmg"][2]
            if order == "me":
                foe_left = foe_hp - my_lo
                killed_foe = foe_left <= 0
                my_left = my_hp if killed_foe else my_hp - e_hi
            elif order == "foe":
                my_left = my_hp - e_lo
                foe_left = foe_hp if my_left <= 0 else foe_hp - my_lo
            else:
                foe_left = foe_hp - my_lo
                my_left = my_hp - e_lo
            outs.append({"foe_skill": r["skill"], "order": order,
                         "my_hp_left": max(0, my_left),
                         "foe_hp_left": max(0, foe_left),
                         "i_kill": foe_left <= 0,
                         "i_die": my_left <= 0})
        a["outcomes"] = outs
        a["worst_hp_left"] = min(o["my_hp_left"] for o in outs)
        a["kill_rate"] = round(sum(1 for o in outs if o["i_kill"]) / len(outs), 3)
        a["die_rate"] = round(sum(1 for o in outs if o["i_die"]) / len(outs), 3)

    rec = _recommend(actions, my_hp, foe_hp)
    return {
        "me": {"name": my_card.get("name"), "panel": me, "hp": my_hp,
               "hp_max": my_hp_max, "hp_ratio": my_hp / max(1, my_hp_max),
               "effects": my_eff["soul"]},
        "foe": {"name": foe_card.get("name"), "panel": foe, "hp": foe_hp,
                "hp_max": foe_hp_max, "hp_ratio": foe_hp / max(1, foe_hp_max),
                "effects": foe_eff["soul"], "pool": [s["name"] for s in foe_skills]},
        "foe_skill_pool": foe_skills,
        "foe_replies": foe_replies,
        "actions": actions,
        "recommend": rec,
        "caveats": _caveats(foe_card, foe_marks, state),
    }


def _foe_pool(foe_card, marks):
    """对方的可选技能池。有手动标记就只用标记里的；否则用前 5 个常用技能。"""
    skills = foe_card.get("skills", [])
    if marks:
        hit = [s for s in skills if s["name"] in marks]
        if hit:
            return hit
        import repo as _r
        out = []
        for nm in marks:
            got = _r.search_skill(nm, 1)
            if got:
                out.append(got[0])
        if out:
            return out
    return skills


def _acc(skill):
    """命中率 → 0~1。必中/空 都按 1.0。"""
    a = (skill.get("accuracy") or "").strip()
    if not a or "必中" in a:
        return 1.0
    import re
    m = re.search(r"(\d+)\s*%", a)
    return int(m.group(1)) / 100 if m else 1.0


def _switch_outcomes(a, foe_replies, my_hp):
    """换人：本回合必定被对方打一下（默认对手先手），伤害取中间值附近。"""
    outs = []
    for r in foe_replies:
        outs.append({"foe_skill": r["skill"], "order": "foe",
                     "my_hp_left": max(0, my_hp - r["dmg"][2]),
                     "foe_hp_left": None, "i_kill": False,
                     "i_die": r["dmg"][2] >= my_hp})
    return outs


def _recommend(actions, my_hp, foe_hp):
    """max-min：先保证不被打死，再优先能击杀的，再看稳定收益。

    评分口径（全部可解释）：
      - 最坏情况下剩余血量比例  → 主要排序键（挨打越少越靠前）
      - 能稳杀的额外加权、可能被杀的减权
      - 属性技（威力 0）加回它的**铺垫收益**（见 status_gain）：
        控场=白赚一回合、强化=下回合输出/承伤变好。
        老版本给属性技扣 0.1，等于永远不推荐强化招，那是错的。
    """
    scored = []
    for a in actions:
        if not a.get("usable", True):
            continue
        if a["kind"] == "switch":
            worst_ratio = a["worst_hp_left"] / max(1, my_hp)
            score = worst_ratio - 0.15      # 换人本回合白挨一下，扣分
            reason = "换人躲开当前对位，但本回合不能出手"
            scored.append((score, a, reason, worst_ratio))
            continue
        worst_ratio = a["worst_hp_left"] / max(1, my_hp)
        score = worst_ratio
        reason = []
        if a["kind"] == "status":
            score += a.get("value", 0.0)
            reason.append("属性技：" + "，".join(a.get("notes") or ["铺垫"]))
        elif a["kill_guaranteed"]:
            score += 1.0
            reason.append("按最低伤害也能击杀对方")
        elif a["kill_possible"]:
            score += 0.3
            reason.append("最高伤害可击杀，但有浮动风险")
        if a.get("die_rate", 0) > 0:
            score -= 0.5 * a["die_rate"]
            reason.append(f"最坏情况有 {int(a['die_rate'] * 100)}% 概率被打死")
        scored.append((score, a, "；".join(reason) or "常规输出", worst_ratio))

    if not scored:
        return {"action": None, "reason": "没有可用动作（PP/技能数据缺失）"}
    scored.sort(key=lambda x: -x[0])
    best = scored[0]
    a = best[1]
    label = ("换人" if a["kind"] == "switch" else a["skill"]["name"])
    # 最坏情况文字（不要把"最坏："写进值里，调用方会自己加前缀）
    if a["kind"] == "switch":
        worst = f"被打掉 {int(my_hp - best[3] * my_hp)} 点体力"
    else:
        outs = a["outcomes"]
        bad = min(outs, key=lambda o: o["my_hp_left"]) if outs else None
        if not bad:
            worst = ""
        elif bad.get("foe_hp_left") is None:
            # 属性技：对方血量不变，只说我这回合掉了多少
            took = int(bad.get("took", 0))
            worst = (f"对方用「{bad['foe_skill']['name']}」→ 我掉 {took}"
                     f"，我剩 {bad['my_hp_left']}")
        else:
            worst = (f"对方用「{bad['foe_skill']['name']}」"
                     f"→ 我剩 {bad['my_hp_left']}，对方剩 {bad['foe_hp_left']}")
    return {"action": label, "score": round(best[0], 4),
            "reason": best[2], "worst_case": worst,
            "alt": [(("换人" if x[1]["kind"] == "switch" else x[1]["skill"]["name"]),
                     round(x[0], 3), x[2]) for x in scored[1:3]]}


def _caveats(foe_card, marks, state):
    out = []
    if not marks:
        out.append("对方这回合用什么没标记，候选池按图鉴尾部的常用技能全枚举")
    out.append("对方数值是按种族值推算，误差可能上百点体力")
    if not out:
        return []
    return out
