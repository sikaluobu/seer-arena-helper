# -*- coding: utf-8 -*-
"""wiki.biligame.com/seer 的 MediaWiki API 客户端。

设计要点：
- 批量取 wikitext（titles= 上限 50），一次网络请求换 50 页内容。
- 磁盘缓存：data/cache/<sha1>.json 存原始 wikitext，重跑不重复打 wiki。
- 重试 + 退避 + 上限，失败不中断整批。
"""
import hashlib
import json
import os
import time
import random
import requests

from config import API, HEADERS, CACHE_DIR, BATCH, SLEEP, TIMEOUT, RETRIES


def _cache_path(title):
    h = hashlib.sha1(title.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, h + ".json")


class WikiClient:
    def __init__(self, use_cache=True):
        self.s = requests.Session()
        self.s.headers.update(HEADERS)
        self.use_cache = use_cache

    # ---------- 低层 ----------
    def _get(self, params):
        last = None
        for attempt in range(RETRIES):
            try:
                r = self.s.get(API, params=params, timeout=TIMEOUT)
                if r.status_code == 200:
                    ctype = r.headers.get("Content-Type", "")
                    if "json" in ctype:
                        return r.json()
                    last = f"非 JSON 响应 ({ctype})"
                elif r.status_code == 567:
                    # b 站反爬页：多半是头不对或短时限流，退避重试
                    last = "HTTP 567 (反爬限流)"
                else:
                    last = f"HTTP {r.status_code}"
            except Exception as e:  # noqa: BLE001
                last = repr(e)
            time.sleep(1.0 * (2 ** attempt) + random.random() * 0.5)
        raise RuntimeError(f"wiki 请求失败: {last} params={params}")

    def _cached(self, title, fetch):
        p = _cache_path(title)
        if self.use_cache and os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    v = json.load(f)
                if not v.get("__miss__"):
                    return v["text"]
            except Exception:  # noqa: BLE001
                pass
        text = fetch()
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"text": text, "__miss__": text is None}, f, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            pass
        return text

    # ---------- 高层 ----------
    def list_pages(self, prefix, namespace=0):
        """按前缀枚举全部页面标题。"""
        out, cont = [], None
        while True:
            p = {
                "action": "query", "list": "allpages", "format": "json",
                "apnamespace": namespace, "aplimit": 500, "apprefix": prefix,
            }
            if cont:
                p["apcontinue"] = cont
            j = self._get(p)
            for pg in j.get("query", {}).get("allpages", []):
                out.append(pg["title"])
            cont = j.get("continue", {}).get("apcontinue")
            if not cont:
                break
            time.sleep(SLEEP)
        return out

    def search(self, query, limit=10):
        """全文搜索，返回页面标题列表。"""
        j = self._get({
            "action": "query", "list": "search", "srsearch": query,
            "srlimit": limit, "format": "json",
        })
        return [x["title"] for x in j.get("query", {}).get("search", [])]

    def get_wikitext(self, title):
        """取单页 wikitext，返回 str 或 None（页面不存在/不是文本页）。"""
        def fetch():
            j = self._get({
                "action": "query", "prop": "revisions", "rvprop": "content",
                "rvslots": "main", "titles": title, "format": "json",
                "redirects": 1,
            })
            pages = j.get("query", {}).get("pages", {})
            for _pid, page in pages.items():
                if "missing" in page:
                    return None
                revs = page.get("revisions") or []
                if not revs:
                    return None
                return revs[0].get("slots", {}).get("main", {}).get("*")
            return None
        return self._cached(title, fetch)

    def get_many(self, titles, progress=None):
        """批量取多页 wikitext。返回 {title: text|None}。"""
        result = {}
        todo = list(titles)
        done = 0
        for i in range(0, len(todo), BATCH):
            chunk = todo[i:i + BATCH]
            # 先看缓存
            need = []
            for t in chunk:
                p = _cache_path(t)
                if self.use_cache and os.path.exists(p):
                    try:
                        with open(p, "r", encoding="utf-8") as f:
                            v = json.load(f)
                        if not v.get("__miss__"):
                            result[t] = v["text"]
                            continue
                    except Exception:  # noqa: BLE001
                        pass
                need.append(t)
            if need:
                # 整批失败会自动拆成小块重试，避免因为 50 个里 1 个报错全军覆没
                chunks = [need]
                for depth in range(4):
                    nxt = []
                    for ch in chunks:
                        try:
                            j = self._get({
                                "action": "query", "prop": "revisions", "rvprop": "content",
                                "rvslots": "main", "titles": "|".join(ch),
                                "format": "json", "redirects": 1,
                            })
                            self._absorb(j, result, progress=None)
                        except Exception as e:  # noqa: BLE001
                            if len(ch) <= 1:
                                if progress:
                                    progress(f"  ! 单页仍失败，跳过: {ch[0]}")
                                continue
                            half = max(1, len(ch) // 2)
                            nxt.extend([ch[:half], ch[half:]])
                            if progress:
                                progress(f"  ! 批次 {len(ch)} 失败({e})，拆成 "
                                         f"{len(ch[:half])}+{len(ch[half:])} 重试")
                    if not nxt:
                        break
                    chunks = nxt
            done += len(chunk)
            if progress:
                progress(f"  已取 {done}/{len(todo)}")
            time.sleep(SLEEP)
        return result

    def _absorb(self, j, result, progress=None):
        """把一次 query 响应里的页面内容收进 result 并写缓存。"""
        norm = {}
        for n in j.get("query", {}).get("normalized", []):
            norm[n["to"]] = n["from"]
        for r in j.get("query", {}).get("redirects", []):
            norm[r["to"]] = r["from"]
        got = {}
        for _pid, page in j.get("query", {}).get("pages", {}).items():
            title = page.get("title")
            if "missing" in page:
                text = None
            else:
                revs = page.get("revisions") or []
                text = revs[0].get("slots", {}).get("main", {}).get("*") if revs else None
            got[title] = text
        for t in list(got.keys()):
            result[t] = got[t]
            self._write_cache(t, got[t])
        for src, dst in norm.items():
            if dst in got and src not in got:
                result[src] = got[dst]
                self._write_cache(src, got[dst])

    @staticmethod
    def _write_cache(title, text):
        try:
            with open(_cache_path(title), "w", encoding="utf-8") as f:
                json.dump({"text": text, "__miss__": text is None}, f, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            pass
