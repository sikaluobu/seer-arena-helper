# -*- coding: utf-8 -*-
"""伤害公式回验：拿已知/可推的实战伤害反推公式形态。

已回收的实测数据（用户提供的巅峰截图，m00001 内联图片）：
  图1 挑选界面：双方阵容、禁用标记
  图2 第3回合：我方 镇世神岳·玄武 325/1083，敌方 修罗铠甲；克制关系「微弱」
  图3 第16回合：我方 万霆神律·雷伊 1033/1093，敌方 妙时天女；克制 1.25 vs 0.75，飘字 克制-285
  图4 第25回合：我方 镇世神岳·玄武 1034/1083，敌方 妙时天女；克制 1.0 vs 0.75，
       飘字 +551（绿，回复）与 -259（粉，固定/百分比伤害）；技能面板 百烈军破 4/5
  图5 帕诺 七星阵列 5/5 威力160

本脚本做的是「候选公式枚举」：把每个候选算出来的伤害摆在一起，看哪个能落进实测区间。
"""
import io
import sys

from console import fix_console; fix_console()
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))

from db import connect
import damage as D
import rules as R


def formula_variants(level, power, atk, dfn):
    """三候选：宝可梦式 / 简化式(power*atk/def) / 乘 50 的旧式。"""
    base = (2.0 * level / 5.0 + 2.0) * power * atk / dfn / 50.0 + 2.0
    simple = power * atk / dfn
    old = (level * 2 / 5 + 2) * power * atk / dfn / 50 + 2
    return {"pkmn": base, "simple": simple, "old": old}


def show(sid, skill_id):
    c = connect()
    sp = c.execute("select * from spirits where id=?", (sid,)).fetchone()
    sk = c.execute("select * from skills where id=?", (skill_id,)).fetchone()
    print(f"\n[{sp['name']}] {sp['element']}  体力{sp['hp']} 攻{sp['atk']} 防{sp['def_']} "
          f"特攻{sp['spatk']} 特防{sp['spdef']} 速{sp['speed']} 总和{sp['total']}")
    print(f"  技能 {sk['name']} {sk['stype']} {sk['element']} 威力{sk['power']} 先制{sk['priority']}")


if __name__ == "__main__":
    c = connect()
    # 候选组合：参数按「种族值 600 左右的满级常见配置」粗估——能力值 ≈ 种族值*2 + 110
    def stat(race, lvl_pts=0):
        return int(race * 2 + 110 + lvl_pts)

    print("=" * 78)
    print("候选公式：同一组输入下三种公式的裸伤（无克制/无加成）")
    print("=" * 78)
    for level, power, race_atk, race_dfn in [(100, 150, 130, 110), (100, 160, 135, 108)]:
        a, d = stat(race_atk), stat(race_dfn)
        vs = formula_variants(level, power, a, d)
        print(f"\nLv{level} 威力{power} 攻{a} 防{d}")
        for k, v in vs.items():
            print(f"    {k:<7} 裸伤≈{v:8.1f}   随机0.85~1.00 → {int(v*0.85):>4}~{int(v):>4}")

    print()
    print("=" * 78)
    print("用你的截图反推：图3 万霆神律·雷伊 打 妙时天女，飘字「克制-285」")
    print("=" * 78)
    sp = c.execute("select * from spirits where name='万霆神律·雷伊'").fetchone()
    if sp is None:
        sp = c.execute("select * from spirits where name like '%雷伊%'").fetchone()
    en = c.execute("select * from spirits where name like '%妙时天女%'").fetchone()
    for x in (sp, en):
        if x:
            print(f"  {x['name']:<16} 属性={x['element']:<8} 体力{x['hp']} 攻{x['atk']} 特攻{x['spatk']} "
                  f"防{x['def_']} 特防{x['spdef']} 速{x['speed']} 总和{x['total']}")
        else:
            print("  (库里没这只)")
    if sp and en:
        coef = D.element_coef("电", en["element"])
        print(f"  电系技能打 {en['element']} 的克制系数 = {coef}")
        for pw in (85, 90, 150, 160):
            for name, base in formula_variants(100, pw, stat(sp["spatk"]), stat(en["spdef"])).items():
                for coef_ in (coef,):
                    for random_ in (0.85, 1.0):
                        print(f"    威力{pw:>3} {name:<7} 系数{coef_:.2f} 随机{random_:.2f} "
                              f"→ {int(base*coef_*random_):>5}")
        print(f"  实测飘字 = 285（克制 1.25 / 被克制 0.75 是界面显示的双方克制倍率）")
