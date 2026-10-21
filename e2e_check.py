# -*- coding: utf-8 -*-
"""端到端自检：识别 → 判断 → 推荐。

用截图里出现的真实对位做测试：
  万霆神律·雷伊(圣灵电) vs 妙时天女(混沌光)
  镇世神岳·玄武(机械地面) vs 修罗铠甲(混沌圣灵)
"""
import json
import sys

from console import fix_console; fix_console()

import decide
import repo


def show(title, my_name, foe_name, **state):
    print("=" * 68)
    print(title)
    mc = None
    for sid, nm, sc in repo.match_spirit(my_name, cutoff=0.55):
        if nm == my_name or sc > 0.9:
            mc = repo.card(sid)
            if mc:
                break
    fc = None
    for sid, nm, sc in repo.match_spirit(foe_name, cutoff=0.55):
        if nm == foe_name or sc > 0.9:
            fc = repo.card(sid)
            if fc:
                break
    if not mc or not fc:
        print(f"  匹配失败: 我={mc and mc['name']} 敌={fc and fc['name']}")
        return
    print(f"  我: {mc['name']} [{mc['element']}] 技能 {[s['name'] for s in mc['skills']]}")
    print(f"  敌: {fc['name']} [{fc['element']}] 候选 {[s['name'] for s in fc['skills']]}")
    r = decide.analyze(mc, fc, state)
    print(f"  我方面板: 血{r['me']['panel']['hp']} 攻{r['me']['panel']['atk']} "
          f"防{r['me']['panel']['def_']} 特攻{r['me']['panel']['spatk']} "
          f"特防{r['me']['panel']['spdef']} 速{r['me']['panel']['speed']}")
    print(f"  对方推算: 血{r['foe']['panel']['hp']} 速{r['foe']['panel']['speed']}")
    print(f"  当前血量: 我 {r['me']['hp']}/{r['me']['hp_max']}  敌 {r['foe']['hp']}/{r['foe']['hp_max']}")
    print("  各技能伤害（对当前敌方）:")
    for a in r["actions"]:
        if a["kind"] == "switch":
            continue
        sk = a["skill"]
        lo, mid, hi = a["dmg"]
        mark = "稳杀" if a["kill_guaranteed"] else ("可杀" if a["kill_possible"] else "")
        print(f"    {sk['name']:<14} 威力{sk['power']:>3} 先制{a['priority']} "
              f"伤害 {lo:>4}~{hi:>4} (期望{mid:>4}) {mark}")
    rec = r["recommend"]
    print(f"  ★ 推荐: {rec['action']}   ({rec['reason']})")
    print(f"     最坏情况: {rec['worst_case']}")
    for nm, sc, rs in rec.get("alt", []):
        print(f"     备选: {nm}  score={sc}  {rs}")
    for c in r["caveats"]:
        print("     ⚠", c)


if __name__ == "__main__":
    show("【截图2】第3回合：镇世神岳·玄武 vs 修罗铠甲（我 325/1083）",
         "镇世神岳·玄武", "修罗铠甲", my_hp=325, my_hp_max=1083)
    show("【截图3】第16回合：万霆神律·雷伊 vs 妙时天女（我 1033/1093）",
         "万霆神律·雷伊", "妙时天女", my_hp=1033, my_hp_max=1093)
    show("【截图4】第25回合：镇世神岳·玄武 vs 妙时天女（我 1034/1083）",
         "镇世神岳·玄武", "妙时天女", my_hp=1034, my_hp_max=1083,
         foe_marks=["妙舞天音", "天女散花"])
