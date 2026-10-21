# -*- coding: utf-8 -*-
"""全局配置：路径、API、限速。"""
import os

from paths import APP_DIR, resource

ROOT = APP_DIR
DATA_DIR = os.path.join(ROOT, "data")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
LOG_DIR = os.path.join(ROOT, "logs")
# 数据库优先用 exe/源码旁边那份，没有就用打包进 exe 的那份（只读）
DB_PATH = resource("data", "seer.db")

for _d in (DATA_DIR, CACHE_DIR, LOG_DIR):
    os.makedirs(_d, exist_ok=True)

API = "https://wiki.biligame.com/seer/api.php"
# 重点：这个站有反爬。缺 Referer 时 API 一律返回 HTTP 567（限流页），
# 带上 Referer 和浏览器 UA 才能正常拿到 200。别删这几个头。
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    "Referer": "https://wiki.biligame.com/seer/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
USER_AGENT = HEADERS["User-Agent"]

# MediaWiki titles= 上限对普通用户是 50
BATCH = 50
# 每次请求之间歇一下，别把 wiki 打疼（567 是 wiki 的限流码，太小会被掐）
SLEEP = 0.3
# 单批 titles 数。50 是硬上限，但实际跑下来 40 更不容易触发限流
BATCH = 40
# 单次请求超时
TIMEOUT = 60
# 失败重试
RETRIES = 4
