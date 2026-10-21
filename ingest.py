# -*- coding: utf-8 -*-
"""全量落库：精灵 -> 技能 -> 效果 / 魂印。

用法：
    python ingest.py spirits      # 只抓精灵（含技能字段），落 spirits + spirit_skills
    python ingest.py skills       # 抓 spirit_skills 引用的全部技能页，落 skills
    python ingest.py effects      # 抓 skills.effect_ids 引用的效果页，落 effects
    python ingest.py souls        # 抓 魂印:* 全部页面，落 souls + spirit_souls
    python ingest.py all

可反复执行：wiki 响应有磁盘缓存，已入库的会跳过。
"""
import io
import os
import sys
import time

from console import fix_console; fix_console()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import parse_wikitext as P
from config import DB_PATH
import db as DB
from wiki_client import WikiClient

# 实战常用配招的角色标签（与 repo.ROLE_TAGS 保持一致，避免循环 import 而已）
COMMON_ROLES = ("强化", "防御", "先手", "制敌", "第五")


def _is_common(tail):
    if not tail:
        return False
    t = str(tail).strip()
    if t.isdigit():
        return False
    return t.split("-")[0] in COMMON_ROLES

NOW = int(time.time())


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- spirits
def ingest_spirits(wc, conn):
    log("== 抓精灵 ==")
    titles = wc.list_pages("精灵:", namespace=0)
    titles = [t for t in titles if t.startswith("精灵:") and t.count(":") == 1
              and t[3:].isdigit()]
    log(f"待抓 {len(titles)} 页")
    pages = wc.get_many(titles, progress=log)

    rows, links, bad = [], [], 0
    for t, text in pages.items():
        sp = P.parse_spirit(text)
        if not sp or not sp["id"]:
            bad += 1
            continue
        rows.append((
            sp["id"], sp["name"], sp["species"], sp["element"], sp["hp"], sp["atk"],
            sp["def_"], sp["spatk"], sp["spdef"], sp["speed"], sp["total"],
            sp["gender"], sp["form"], sp["kind"], sp["height"], sp["weight"],
            sp["intro"], sp["raw_skills"], NOW,
        ))
        lst = P.parse_skill_field(sp["skill_str"])
        for i, e in enumerate(lst):
            links.append((sp["id"], i, e["skill_id"], e["learn_level"], e["tail"],
                          1 if _is_common(e.get("tail")) else 0))

    c = conn.cursor()
    c.executemany("""
        INSERT INTO spirits (id,name,species,element,hp,atk,def_,spatk,spdef,speed,
                             total,gender,form,kind,height,weight,intro,raw_skills,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name, element=excluded.element, hp=excluded.hp, atk=excluded.atk,
            def_=excluded.def_, spatk=excluded.spatk, spdef=excluded.spdef,
            speed=excluded.speed, total=excluded.total, raw_skills=excluded.raw_skills,
            updated_at=excluded.updated_at
    """, rows)
    c.executemany("""
        INSERT INTO spirit_skills (spirit_id,slot,skill_id,learn_level,tail,is_front5)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT(spirit_id,slot) DO UPDATE SET
            skill_id=excluded.skill_id, learn_level=excluded.learn_level,
            tail=excluded.tail, is_front5=excluded.is_front5
    """, links)
    conn.commit()
    log(f"spirits 入库 {len(rows)}  技能关联 {len(links)}  解析失败 {bad}")
    return len(rows), len(links)


# ---------------------------------------------------------------- skills
def ingest_skills(wc, conn):
    log("== 抓技能 ==")
    ids = [r[0] for r in conn.execute(
        "SELECT DISTINCT skill_id FROM spirit_skills ORDER BY skill_id")]
    log(f"技能字段引用了 {len(ids)} 个技能 ID，全部抓取")
    titles = ["技能:%d" % i for i in ids]
    pages = wc.get_many(titles, progress=log)

    rows, bad, miss = [], 0, 0
    for i in ids:
        text = pages.get("技能:%d" % i)
        if text is None:
            miss += 1
            continue
        sk = P.parse_skill(text)
        if not sk or not sk["id"]:
            bad += 1
            continue
        rows.append((sk["id"], sk["name"], sk["stype"], sk["element"], sk["power"],
                     sk["pp"], sk["priority"], sk["accuracy"], sk["crit"],
                     sk["effect_ids"], sk["effect_text"], NOW))
    c = conn.cursor()
    c.executemany("""
        INSERT INTO skills (id,name,stype,element,power,pp,priority,accuracy,crit,
                            effect_ids,effect_text,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name, stype=excluded.stype, element=excluded.element,
            power=excluded.power, pp=excluded.pp, priority=excluded.priority,
            accuracy=excluded.accuracy, crit=excluded.crit,
            effect_ids=excluded.effect_ids, effect_text=excluded.effect_text,
            updated_at=excluded.updated_at
    """, rows)
    conn.commit()
    log(f"skills 入库 {len(rows)}  页面缺失 {miss}  解析失败 {bad}")
    return len(rows)


# ---------------------------------------------------------------- effects
def ingest_effects(wc, conn):
    log("== 抓技能效果定义 ==")
    ids = set()
    for (s,) in conn.execute("SELECT DISTINCT effect_ids FROM skills WHERE effect_ids<>''"):
        for tok in str(s).replace("|", " ").split():
            if tok.isdigit():
                ids.add(int(tok))
    ids = sorted(ids)
    log(f"共 {len(ids)} 个效果 ID")
    pages = wc.get_many(["效果:%d" % i for i in ids], progress=log)
    rows = []
    for i in ids:
        text = pages.get("效果:%d" % i)
        if text is None:
            continue
        ef = P.parse_effect(text)
        if not ef or ef["id"] is None:
            continue
        rows.append((ef["id"], ef["args_num"], ef["info"], ef["param"], NOW))
    c = conn.cursor()
    c.executemany("""
        INSERT INTO effects (id,args_num,info,param,updated_at) VALUES (?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET args_num=excluded.args_num, info=excluded.info,
                                      param=excluded.param, updated_at=excluded.updated_at
    """, rows)
    conn.commit()
    log(f"effects 入库 {len(rows)}")
    return len(rows)


# ---------------------------------------------------------------- souls
def ingest_souls(wc, conn):
    log("== 抓魂印 ==")
    titles = wc.list_pages("魂印:", namespace=0)
    titles = [t for t in titles if t.startswith("魂印:") and t[3:].isdigit()]
    log(f"待抓 {len(titles)} 页")
    pages = wc.get_many(titles, progress=log)
    rows, links, bad = [], [], 0
    for t, text in pages.items():
        so = P.parse_soul(text)
        if not so or so["id"] is None:
            bad += 1
            continue
        rows.append((so["id"], so["related_spirit"], so["icon"], so["effect_ids"],
                     so["kind"], so["text"], NOW))
        if so["related_spirit"]:
            links.append((so["related_spirit"], so["id"]))
    c = conn.cursor()
    c.executemany("""
        INSERT INTO souls (id,related_spirit,icon,effect_ids,kind,text,updated_at)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET related_spirit=excluded.related_spirit,
            icon=excluded.icon, effect_ids=excluded.effect_ids, kind=excluded.kind,
            text=excluded.text, updated_at=excluded.updated_at
    """, rows)
    c.executemany("""
        INSERT OR IGNORE INTO spirit_souls (spirit_id,soul_id) VALUES (?,?)
    """, links)
    conn.commit()
    log(f"souls 入库 {len(rows)}  关联 {len(links)}  解析失败 {bad}")
    return len(rows)


def main():
    what = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
    conn = DB.init_db()
    wc = WikiClient(use_cache=True)
    t0 = time.time()
    if what in ("spirits", "all"):
        ingest_spirits(wc, conn)
    if what in ("skills", "all"):
        ingest_skills(wc, conn)
    if what in ("effects", "all"):
        ingest_effects(wc, conn)
    if what in ("souls", "all"):
        ingest_souls(wc, conn)
    cur = conn.execute("INSERT OR REPLACE INTO meta (k,v) VALUES ('built_at',?)", (str(NOW),))
    conn.commit()
    log(f"\n完成，用时 {time.time()-t0:.1f}s  库={DB_PATH}")


if __name__ == "__main__":
    main()
