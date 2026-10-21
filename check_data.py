# -*- coding: utf-8 -*-
"""数据库体检：覆盖率、字段完整度、前五个技能规则是否站得住。

用法：python check_data.py [抽查只数]
"""
import io
import os
import random
import sys

from console import fix_console; fix_console()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import connect


def pct(a, b):
    return f"{a}/{b} ({100.0*a/b:.1f}%)" if b else "0/0"


def main(sample=200):
    c = connect()
    q = lambda s, *a: c.execute(s, a).fetchone()[0]

    print("=" * 62)
    print("表规模")
    print("=" * 62)
    for t in ["spirits", "spirit_skills", "skills", "effects", "souls", "spirit_souls"]:
        print(f"  {t:<14} {q('select count(*) from '+t):>7}")

    print()
    print("=" * 62)
    print("字段完整度")
    print("=" * 62)
    n_sp = q("select count(*) from spirits")
    n_sk = q("select count(*) from skills")
    print(f"  精灵 有名字        {pct(q('select count(*) from spirits where name > char(0)'), n_sp)}")
    print(f"  精灵 有属性        {pct(q('select count(*) from spirits where element > char(0)'), n_sp)}")
    print(f"  精灵 六项种族值全  {pct(q('select count(*) from spirits where hp is not null and atk is not null and def_ is not null and spatk is not null and spdef is not null and speed is not null'), n_sp)}")
    print(f"  精灵 有魂印        {pct(q('select count(distinct spirit_id) from spirit_souls'), n_sp)}")
    print(f"  技能 有名字        {pct(q('select count(*) from skills where name > char(0)'), n_sk)}")
    print(f"  技能 有类型        {pct(q('select count(*) from skills where stype > char(0)'), n_sk)}")
    print(f"  技能 有威力        {pct(q('select count(*) from skills where power is not null'), n_sk)}")
    print(f"  技能 有 PP         {pct(q('select count(*) from skills where pp is not null'), n_sk)}")
    print(f"  技能 有先制        {pct(q('select count(*) from skills where priority is not null'), n_sk)}")
    print(f"  技能 有效果明文    {pct(q('select count(*) from skills where effect_text > char(0)'), n_sk)}")
    print(f"  技能 有效果ID      {pct(q('select count(*) from skills where effect_ids > char(0)'), n_sk)}")

    print()
    print("=" * 62)
    print("引用完整性（前端技能 ID 是否都能在技能表里找到）")
    print("=" * 62)
    print(f"  前五个技能关联     {q('select count(*) from spirit_skills where is_front5=1')}")
    print(f"  其中技能表命中     {pct(q('select count(*) from spirit_skills ss join skills s on s.id=ss.skill_id where ss.is_front5=1'), q('select count(*) from spirit_skills where is_front5=1'))}")
    print(f"  全部技能关联命中   {pct(q('select count(*) from spirit_skills ss join skills s on s.id=ss.skill_id'), q('select count(*) from spirit_skills'))}")
    missing = c.execute("""select ss.spirit_id, ss.skill_id from spirit_skills ss
                           left join skills s on s.id=ss.skill_id
                           where s.id is null limit 10""").fetchall()
    if missing:
        print(f"  未命中示例: {[(r[0], r[1]) for r in missing]}")

    print()
    print("=" * 62)
    print(f"前五个技能规则抽查（随机 {sample} 只）")
    print("=" * 62)
    ids = [r[0] for r in c.execute(
        "select id from spirits order by random() limit ?", (sample,))]
    bad_empty, bad_dup, bad_missing = [], [], []
    for sid in ids:
        rows = c.execute("""select ss.slot, ss.skill_id, s.name, s.stype, s.power, s.priority
                            from spirit_skills ss left join skills s on s.id=ss.skill_id
                            where ss.spirit_id=? and ss.is_front5=1 order by ss.slot""",
                         (sid,)).fetchall()
        if len(rows) < 5:
            bad_empty.append((sid, len(rows)))
            continue
        sids = [r["skill_id"] for r in rows]
        if len(set(sids)) != len(sids):
            bad_dup.append((sid, sids))
        for r in rows:
            if r["name"] is None:
                bad_missing.append((sid, r["skill_id"]))
    print(f"  不足 5 个技能:      {len(bad_empty)}  {bad_empty[:5]}")
    print(f"  前 5 个里有重复:    {len(bad_dup)}  {bad_dup[:3]}")
    print(f"  前 5 个有查不到的:  {len(bad_missing)}  {bad_missing[:5]}")

    print()
    print("=" * 62)
    print("样例：随机 3 只精灵的前五个技能（这就是判断引擎看到的候选池）")
    print("=" * 62)
    for sid in ids[:3]:
        sp = c.execute("select * from spirits where id=?", (sid,)).fetchone()
        print(f"\n  [{sp['id']}] {sp['name']}  属性={sp['element']}  "
              f"体力={sp['hp']} 攻击={sp['atk']} 防御={sp['def_']} "
              f"特攻={sp['spatk']} 特防={sp['spdef']} 速度={sp['speed']}")
        rows = c.execute("""select ss.slot, ss.skill_id, ss.tail, s.name, s.stype, s.element,
                                   s.power, s.pp, s.priority, s.effect_text
                            from spirit_skills ss left join skills s on s.id=ss.skill_id
                            where ss.spirit_id=? and ss.is_front5=1 order by ss.slot""",
                         (sid,)).fetchall()
        for r in rows:
            eff = (r["effect_text"] or "")[:46]
            print(f"    {r['slot']}. {str(r['name']):<10} {str(r['stype']):<5} "
                  f"{str(r['element']):<6} 威力{str(r['power']):>3} PP{str(r['pp']):>3} "
                  f"先制{r['priority']}  {eff}")
        so = c.execute("""select so.text from spirit_souls ss join souls so on so.id=ss.soul_id
                          where ss.spirit_id=? limit 1""", (sid,)).fetchone()
        if so and so["text"]:
            print(f"    魂印: {so['text'][:110]}")

    print()
    print("=" * 62)
    print("属性词表（双属性是拼接的，需要切词）")
    print("=" * 62)
    els = [r[0] for r in c.execute("select distinct element from spirits where element<>''")]
    print(f"  精灵属性种类: {len(els)}   示例: {els[:14]}")
    sels = [r[0] for r in c.execute("select distinct element from skills where element<>''")]
    print(f"  技能属性种类: {len(sels)}   示例: {sels[:14]}")
    over = [e for e in els if len(e) > 6]
    print(f"  长度>6 的属性（多半是三属性拼接）: {len(over)}  示例: {over[:8]}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 200)
