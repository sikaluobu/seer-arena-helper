# -*- coding: utf-8 -*-
import sys
from console import fix_console; fix_console()
sys.path.insert(0,'.')
from wiki_client import WikiClient
wc = WikiClient(use_cache=True)
tests = ["效果:%d" % i for i in [0,458,459,460,461,462]]
r = wc.get_many(tests)
for k,v in r.items():
    print(repr(k), "->", (v[:80].replace("\n","⏎") if v else None))
