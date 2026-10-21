# -*- coding: utf-8 -*-
"""SQLite 落库 schema。

表设计目标：
- spirits / skills / spirit_skills 是判断引擎的主数据。
- 附加表（效果、魂印）为后续伤害与减伤计算预留，先抓后解析。
- meta 存数据版本，便于用户侧"重建/更新"。
"""
import os
import sqlite3

from config import DB_PATH

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS meta (
    k TEXT PRIMARY KEY,
    v TEXT
);

CREATE TABLE IF NOT EXISTS spirits (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    species     INTEGER,
    element     TEXT,           -- 属性，可能多属性拼接，如"机械地面"
    hp          INTEGER,
    atk         INTEGER,
    def_        INTEGER,
    spatk       INTEGER,
    spdef       INTEGER,
    speed       INTEGER,
    total       INTEGER,
    gender      TEXT,
    form        TEXT,
    kind        TEXT,
    height      REAL,
    weight      REAL,
    intro       TEXT,
    raw_skills  TEXT,           -- 原始技能字段原文，排查用
    updated_at  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_spirits_name ON spirits(name);

CREATE TABLE IF NOT EXISTS skills (
    id          INTEGER PRIMARY KEY,
    name        TEXT,
    stype       TEXT,           -- 物理攻击 / 特殊攻击 / 属性攻击
    element     TEXT,
    power       INTEGER,
    pp          INTEGER,
    priority    INTEGER,        -- 先制等级
    accuracy    TEXT,           -- 原文，如 "必中（95%）" / "95%"
    crit        TEXT,
    effect_ids  TEXT,
    effect_text TEXT,           -- 技能效果全文（明文，核心字段）
    updated_at  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_skills_name ON skills(name);

CREATE TABLE IF NOT EXISTS spirit_skills (
    spirit_id   INTEGER NOT NULL,
    slot        INTEGER NOT NULL,   -- 在技能字段中的序号，0 起
    skill_id    INTEGER NOT NULL,
    learn_level INTEGER,
    tail        TEXT,               -- "-1" / "-第五" / None，原文排查用
    is_front5   INTEGER DEFAULT 0,  -- 是否属于"前五个常用技能"
    PRIMARY KEY (spirit_id, slot)
);
CREATE INDEX IF NOT EXISTS idx_ss_skill ON spirit_skills(skill_id);

-- 技能效果定义（效果:ID）——后续解析减伤/增伤/先制用
CREATE TABLE IF NOT EXISTS effects (
    id          INTEGER PRIMARY KEY,
    args_num    INTEGER,
    info        TEXT,
    param       TEXT,
    updated_at  INTEGER
);

-- 魂印（含"受到的所有攻击伤害减少10%"这类减伤），以 ID 为键
CREATE TABLE IF NOT EXISTS souls (
    id          INTEGER PRIMARY KEY,
    related_spirit INTEGER,
    icon        TEXT,
    effect_ids  TEXT,
    kind        TEXT,
    text        TEXT,
    updated_at  INTEGER
);

-- 精灵 -> 魂印 反查
CREATE TABLE IF NOT EXISTS spirit_souls (
    spirit_id   INTEGER NOT NULL,
    soul_id     INTEGER NOT NULL,
    PRIMARY KEY (spirit_id, soul_id)
);
"""


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


if __name__ == "__main__":
    c = init_db()
    n = c.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    print(f"数据库就绪: {os.path.abspath(DB_PATH)}  表数={n}")
