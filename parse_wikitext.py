# -*- coding: utf-8 -*-
"""wikitext 解析：精灵模板 / 技能模板 / 效果模板 / 魂印模板。

只做"结构化抽取"，不做语义推理。任何解析不出来的字段原样留在 raw 里。
"""
import re
from typing import Optional


def _split_top_level(s: str) -> list:
    """按 | 切分，但忽略 {{...}} 和 [[...]] 内部的 |。"""
    parts, buf, depth_curly, depth_sq = [], [], 0, 0
    i = 0
    while i < len(s):
        two = s[i:i + 2]
        if two == "{{":
            depth_curly += 1
            buf.append(two)
            i += 2
            continue
        if two == "}}":
            depth_curly = max(0, depth_curly - 1)
            buf.append(two)
            i += 2
            continue
        if two == "[[":
            depth_sq += 1
            buf.append(two)
            i += 2
            continue
        if two == "]]":
            depth_sq = max(0, depth_sq - 1)
            buf.append(two)
            i += 2
            continue
        ch = s[i]
        if ch == "|" and depth_curly == 0 and depth_sq == 0:
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts


def parse_template(text: str, name: str) -> Optional[dict]:
    """解析形如 {{name | k=v | k=v ...}} 的模板，返回字段字典。

    值里可能继续嵌套模板，用深度配平找到模板结束位置。
    """
    if not text:
        return None
    start = text.find("{{" + name)
    if start < 0:
        # 容忍 {{ name
        m = re.search(r"\{\{\s*" + re.escape(name) + r"\s*[|\n}]", text)
        if not m:
            return None
        start = m.start()
    i = start + 2
    depth = 1
    while i < len(text) and depth > 0:
        if text[i:i + 2] == "{{":
            depth += 1
            i += 2
            continue
        if text[i:i + 2] == "}}":
            depth -= 1
            i += 2
            continue
        i += 1
    body = text[start + 2:i - 2]
    parts = _split_top_level(body)
    # parts[0] 是模板名
    out = {}
    positional = []
    for p in parts[1:]:
        if "=" in p:
            k, _, v = p.partition("=")
            out[k.strip()] = v.strip()
        else:
            if p.strip():
                positional.append(p.strip())
    if positional:
        out["__positional__"] = positional
    return out


def _int(v, default=None):
    if v is None:
        return default
    v = str(v).strip()
    if not v or v in ("--", "-"):
        return default
    m = re.search(r"-?\d+", v.replace(",", ""))
    return int(m.group()) if m else default


def _float(v, default=None):
    if v is None:
        return default
    m = re.search(r"-?\d+(\.\d+)?", str(v))
    return float(m.group()) if m else default


# ---------------- 精灵 ----------------

def parse_spirit(text: str) -> Optional[dict]:
    t = parse_template(text, "精灵")
    if not t or "ID" not in t:
        return None
    return {
        "id": _int(t.get("ID")),
        "name": (t.get("名称") or "").strip(),
        "species": _int(t.get("种类")),
        "element": (t.get("属性") or "").strip(),
        "hp": _int(t.get("体力")),
        "atk": _int(t.get("攻击")),
        "def_": _int(t.get("防御")),
        "spatk": _int(t.get("特攻")),
        "spdef": _int(t.get("特防")),
        "speed": _int(t.get("速度")),
        "total": _int(t.get("总和")),
        "gender": (t.get("性别") or "").strip(),
        "form": (t.get("形态") or "").strip(),
        "kind": (t.get("类型") or "").strip(),
        "height": _float(t.get("身高")),
        "weight": _float(t.get("体重")),
        "intro": (t.get("介绍") or "").strip(),
        "raw_skills": (t.get("技能") or "").strip(),
        "skill_str": (t.get("技能") or "").strip(),
    }


# ---------------- 技能 ----------------

def parse_skill(text: str) -> Optional[dict]:
    t = parse_template(text, "技能")
    if not t or "技能序号" not in t:
        return None
    return {
        "id": _int(t.get("技能序号")),
        "name": (t.get("技能名称") or "").strip(),
        "stype": (t.get("技能类型") or "").strip(),
        "element": (t.get("技能属性") or "").strip(),
        "power": _int(t.get("威力"), 0),
        "pp": _int(t.get("次数")),
        "priority": _int(t.get("先制"), 0),
        "accuracy": (t.get("命中率") or "").strip(),
        "crit": (t.get("暴击概率") or "").strip(),
        "effect_ids": (t.get("效果ID") or "").strip(),
        "effect_text": (t.get("技能效果") or "").strip(),
    }


# ---------------- 效果 ----------------

def parse_effect(text: str) -> Optional[dict]:
    t = parse_template(text, "技能效果")
    if not t or "id" not in t:
        return None
    return {
        "id": _int(t.get("id")),
        "args_num": _int(t.get("argsNum")),
        "info": (t.get("info") or "").strip(),
        "param": (t.get("param") or "").strip(),
    }


# ---------------- 魂印 ----------------

def parse_soul(text: str) -> Optional[dict]:
    t = parse_template(text, "魂印")
    if not t or "魂印ID" not in t:
        return None
    return {
        "id": _int(t.get("魂印ID")),
        "related_spirit": _int(t.get("相关精灵")),
        "icon": (t.get("魂印图标") or "").strip(),
        "effect_ids": (t.get("效果IDs") or "").strip(),
        "kind": (t.get("kind") or "").strip(),
        "text": (t.get("魂印效果") or "").strip(),
    }


# ---------------- 精灵技能字段 ----------------

def parse_skill_field(raw: str) -> list:
    """把 '11141-1;20276-5;17622-67-1;17625-75-第五' 解析成结构化列表。

    返回 [{'skill_id':11141,'learn_level':1,'tail':None}, ...]
    tail 保留原文（如 '1' 或 '第五'），含义待核实，仅作排查线索。
    """
    out = []
    if not raw:
        return out
    for seg in raw.split(";"):
        seg = seg.strip()
        if not seg:
            continue
        bits = seg.split("-")
        sid = _int(bits[0])
        if sid is None:
            continue
        level = _int(bits[1]) if len(bits) > 1 else None
        tail = "-".join(bits[2:]) if len(bits) > 2 else None
        out.append({"skill_id": sid, "learn_level": level, "tail": tail})
    return out
