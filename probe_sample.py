# -*- coding: utf-8 -*-
"""小样本抽查：验证解析器、前五个技能规则、tail 标记分布。

先跑这个，确认假设站得住，再决定要不要全量抓近 5000 只精灵。
"""
import io
import random
import sys
from collections import Counter

from console import fix_console; fix_console()
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))

import parse_wikitext as P
from wiki_client import WikiClient


def main(sample=40):
    wc = WikiClient(use_cache=True)
    print("枚举 精灵: 命名空间页面…")
    titles = wc.list_pages("精灵:", namespace=0)
    # list_pages 用前缀枚举，会带上 "精灵:" 本身和子页面
    titles = [t for t in titles if t.startswith("精灵:") and t.count(":") == 1
              and t[3:].isdigit()]
    print(f"主命名空间下 '精灵:<数字>' 共 {len(titles)} 页")

    random.seed(20240510)
    pick = random.sample(titles, min(sample, len(titles)))
    print(f"随机抽 {len(pick)} 页抓取…")
    pages = wc.get_many(pick, progress=lambda m: None)

    n_ok = n_fail = 0
    tail_cnt = Counter()
    rule_same = 0
    skills_needed = set()
    parsed_spirits = []

    for t, text in pages.items():
        sp = P.parse_spirit(text)
        if not sp or not sp["id"]:
            n_fail += 1
            continue
        n_ok += 1
        parsed_spirits.append((t, sp))
        lst = P.parse_skill_field(sp["skill_str"])
        for e in lst:
            tail_cnt[e["tail"]] += 1
            skills_needed.add(e["skill_id"])
        # 规则 A：原始顺序前 5
        a = [e["skill_id"] for e in lst[:5]]
        # 规则 B：按学习等级升序、去掉带 tail 的，再取前 5
        core = [e for e in lst if not e["tail"]]
        b = [e["skill_id"] for e in sorted(core, key=lambda x: (x["learn_level"] or 0))][:5]
        if a == b:
            rule_same += 1

    print(f"\n解析成功 {n_ok} / 失败 {n_fail}")
    print(f"tail 标记分布: {tail_cnt.most_common(10)}")
    print(f"规则A(原始前5) == 规则B(去tail按等级排序前5): {rule_same}/{n_ok}")

    print("\n--- 抽查前 8 只 ---")
    for t, sp in parsed_spirits[:8]:
        lst = P.parse_skill_field(sp["skill_str"])
        print(f"{sp['id']:>6} {sp['name']:<12} 属性={sp['element']:<8} "
              f"速度={sp['speed']} 体力={sp['hp']} 技能数={len(lst)}")
        print(f"       前5(原始): {[e['skill_id'] for e in lst[:5]]}")
        print(f"       前5(tail): {[e['tail'] for e in lst[:5]]}")

    # 抓这些技能页看字段完整度
    print(f"\n抽查技能页字段完整度（共需 {len(skills_needed)} 个，抓前 60 个）…")
    sp_skills = wc.get_many(["技能:%d" % s for s in list(skills_needed)[:60]])
    ok = miss = 0
    empty_name = empty_type = empty_power = 0
    has_effect = 0
    for t, text in sp_skills.items():
        sk = P.parse_skill(text)
        if not sk:
            miss += 1
            continue
        ok += 1
        if not sk["name"]:
            empty_name += 1
        if not sk["stype"]:
            empty_type += 1
        if sk["power"] is None:
            empty_power += 1
        if sk["effect_text"]:
            has_effect += 1
    print(f"技能解析成功 {ok} / 缺失 {miss}")
    print(f"  缺技能名 {empty_name} / 缺类型 {empty_type} / 缺威力 {empty_power}")
    print(f"  有技能效果明文: {has_effect}/{ok}")

    for t, text in list(sp_skills.items())[:5]:
        print("  ", P.parse_skill(text))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 40)
