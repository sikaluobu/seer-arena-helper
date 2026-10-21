# -*- coding: utf-8 -*-
"""抓取"对战机制"等规则页面，落地成文本，供后续人工/半自动提取常数。

规则页不是结构化数据，这里只负责把原文拉到 data/rules/ 下。
真正提取常数在 rules.py 里手工维护（有出处标注）。
"""
import io
import os
import re
import sys

from console import fix_console; fix_console()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import DATA_DIR
from wiki_client import WikiClient

RULES_DIR = os.path.join(DATA_DIR, "rules")
os.makedirs(RULES_DIR, exist_ok=True)

PAGES = [
    "对战机制",
    "属性克制",
    "巅峰之战",
    "巅峰圣战",
    "异常状态",
    "能力等级",
    "技能效果",
    "魂印",
]


def safe(name):
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def main():
    wc = WikiClient()
    for p in PAGES:
        text = wc.get_wikitext(p)
        if text is None:
            print(f"[miss] {p}")
            continue
        fp = os.path.join(RULES_DIR, safe(p) + ".wiki")
        with open(fp, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"[ok]   {p:<12} {len(text):>7} 字符 -> {fp}")


if __name__ == "__main__":
    main()
