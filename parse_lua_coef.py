# -*- coding: utf-8 -*-
"""把 wiki 的 Lua 模块（模块:属性克制）解析成 Python 数据结构并落库。

该模块是纯数据表 + 纯函数，不需要执行 Lua：用正则抽出
  - p.externalToInternal  （显示名 -> 内部名，如 "草超能" -> "草·超能"）
  - p.coefData            （单属性 attack/defense 系数表）
系数合并规则（原模块 p.singleCoef / p.dualVsSingle / p.getDualAttributeCoef）：
  A·B vs C 单属性：a=coef(A,C), b=coef(B,C)
      两者都=2 -> 4；任一=0 -> (a+b)/4；否则 (a+b)/2
  双 vs 双：分别算 双->t1、双->t2，再取平均
  单 vs 双：c1=coef(S,t1), c2=coef(S,t2)，同样 4 / (c1+c2)/4 / (c1+c2)/2
"""
import io
import json
import os
import re
import sys

from console import fix_console; fix_console()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import DATA_DIR

LUA = os.path.join(DATA_DIR, "rules", "模块_属性克制.lua")
OUT_JSON = os.path.join(DATA_DIR, "coef.json")


def _block(text, start_pat):
    """抽出 `p.xxx = {` 起的配对花括号块（返回块内容，不含最外层括号）。"""
    m = re.search(start_pat, text)
    if not m:
        raise SystemExit("找不到块: " + start_pat)
    i = text.index("{", m.start())
    depth = 0
    for j in range(i, len(text)):
        c = text[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[i + 1:j]
    raise SystemExit("花括号不配对: " + start_pat)


def parse_aliases(text):
    body = _block(text, r"p\.externalToInternal\s*=")
    out = {}
    for k, v in re.findall(r'\["([^"]+)"\]\s*=\s*"([^"]+)"', body):
        out[k] = v
    return out


def parse_coef(text):
    body = _block(text, r"p\.coefData\s*=")
    out = {}
    # 逐个顶层属性： ["草"] = { ... },
    for am in re.finditer(r'\["([^"]+)"\]\s*=\s*\{', body):
        attr = am.group(1)
        if attr not in ("attack", "defense"):
            pass
        i = body.index("{", am.start())
        depth, end = 0, None
        for j in range(i, len(body)):
            if body[j] == "{":
                depth += 1
            elif body[j] == "}":
                depth -= 1
                if depth == 0:
                    end = j
                    break
        inner = body[i + 1:end]
        # 顶层先找到真正的属性名：只有 attack/defense 两个子块
        sub = {}
        for mode in ("attack", "defense"):
            mm = re.search(r'\["%s"\]\s*=\s*\{' % mode, inner)
            if not mm:
                continue
            i2 = inner.index("{", mm.start())
            d2, e2 = 0, None
            for j2 in range(i2, len(inner)):
                if inner[j2] == "{":
                    d2 += 1
                elif inner[j2] == "}":
                    d2 -= 1
                    if d2 == 0:
                        e2 = j2
                        break
            sub[mode] = {
                k: float(v) for k, v in re.findall(
                    r'\["([^"]+)"\]\s*=\s*(-?[\d.]+)', inner[i2 + 1:e2])
            }
        if sub:
            out[attr] = sub
    return out


def main():
    text = open(LUA, encoding="utf-8").read()
    aliases = parse_aliases(text)
    coef = parse_coef(text)
    single = [a for a, v in coef.items() if "attack" in v]
    print(f"单属性 {len(single)} 个: {single}")
    print(f"别名 {len(aliases)} 条")
    # 校验：每个属性对 27 个属性的 attack/defense 是否齐全
    miss = []
    for a, v in coef.items():
        for mode in ("attack", "defense"):
            for b in single:
                if b not in v.get(mode, {}):
                    miss.append((a, mode, b))
    print(f"缺失组合 {len(miss)}")
    for x in miss[:20]:
        print("   ", x)
    # 对称性抽查：草→水=2，说明水→草 defense 应为 2
    print("样例 草 attack 水 =", coef["草"]["attack"]["水"])
    print("样例 草 defense 火 =", coef["草"]["defense"]["火"])
    data = {
        "single": single,
        "aliases": aliases,
        "coef": {a: {"attack": v.get("attack", {}), "defense": v.get("defense", {})}
                 for a, v in coef.items()},
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    print(f"写出 {OUT_JSON}  ({os.path.getsize(OUT_JSON)} 字节)")

    # 顺带核对：spirits.element 里的写法能不能对上
    from db import connect
    c = connect()
    els = [r[0] for r in c.execute("select distinct element from spirits where element is not null")]
    unknown = [e for e in els if e not in single and e not in aliases]
    known_single = [e for e in els if e in single]
    known_alias = [e for e in els if e in aliases]
    print(f"\n精灵属性写法共 {len(els)} 种：可直接匹配 {len(known_single)}，"
          f"需别名归一 {len(known_alias)}，对不上 {len(unknown)}")
    if unknown:
        print("  对不上的:", unknown[:30])


if __name__ == "__main__":
    main()
