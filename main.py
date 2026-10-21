# -*- coding: utf-8 -*-
"""赛尔号「巅峰之战」辅助软件 —— 主程序。

一条链路：抓屏 → OCR → 局面 → 判断 → 悬浮窗。

    python main.py              正常跑（先按 F8 或改动画面就会重算）
    python main.py --pick       先挑一次游戏窗口（会记在 data/capture.json）
    python main.py --image X.png  只对一张图跑一遍，结果打在终端（不上悬浮窗）

**硬约束（贯穿整个项目）**：只看、只算、只显示。
不读游戏内存、不解析封包、不代打、不自动出招 —— 按键永远由玩家自己按。
"""
import argparse
import os
import sys
import threading
import time

from console import fix_console; fix_console()

import capture
import decide
import effects
import hpbar
import ocr
import repo
import scene
import turnstate

HERE = os.path.dirname(os.path.abspath(__file__))
# 连续两帧局面一样就不重算；这些字段能区分"是不是同一个局面"
SIG_FIELDS = ("turn",)


def _sig(st):
    if not st:
        return None
    return (st.get("turn"),
            (st["my"] or {}).get("name"), (st["my"] or {}).get("hp"),
            (st["foe"] or {}).get("name"),
            tuple((s.get("name"), s.get("pp")) for s in st.get("skills") or []))


# ----------------------------------------------------------------- 判定
def build(st, img=None):
    """局面 + 截图 → 双方卡片 + analyze 需要的 state。

    返回 (my_card, foe_card, state, notes)；认不出来返回 (None, ...)。
    """
    notes = []
    my_name = (st.get("my") or {}).get("name")
    foe_name = (st.get("foe") or {}).get("name")

    my_card, my_score = _card_of(my_name)
    foe_card, foe_score = _card_of(foe_name)
    if not my_card:
        notes.append(f"认不出我方精灵「{my_name}」，只能显示识别结果")
    if not foe_card:
        notes.append(f"认不出对方精灵「{foe_name}」，只能显示识别结果")
    if not my_card or not foe_card:
        return my_card, foe_card, None, notes

    # ---- 我方技能：画面上那几格才是真在用的，以它为准
    picked = []
    for cell in st.get("skills") or []:
        sk, sc = repo.match_skill(my_card["id"], cell.get("name") or "")
        if not sk:
            notes.append(f"技能「{cell.get('name')}」在库里找不到，已忽略")
            continue
        sk = dict(sk)
        if cell.get("pp") is not None:
            sk["pp_now"] = cell["pp"]
        picked.append(sk)
    det = st.get("detail") or {}
    if det.get("slot") == "fifth" and det.get("name"):
        sk, sc = repo.match_skill(my_card["id"], det["name"])
        if sk and all(s["id"] != sk["id"] for s in picked):
            sk = dict(sk)
            if det.get("pp") is not None:
                sk["pp_now"] = det["pp"]
            picked.append(sk)
            notes.append(f"已把左下详情面板读到的「{det['name']}」当作第五技能")
    if len(picked) >= 2:
        my_card = dict(my_card)
        my_card["skills"] = picked
    else:
        notes.append("底部技能格读得太少，改用图鉴末尾的常用技能兜底（不准确）")

    # ---- 血量：我方的照抄画面；对方只有血条比例，用整体缩放系数折上限
    state = {}
    my = st.get("my") or {}
    state["my_hp"] = my.get("hp")
    state["my_hp_max"] = my.get("hp_max")
    bare_my = repo.stats(my_card)["hp"]
    # 用"我方满血 ÷ 我方裸面板"当这一局装备强度的标定，再套到对方身上
    if state.get("my_hp_max"):
        scale = state["my_hp_max"] / max(1, bare_my)
        notes.append(f"装备强度按我方实测标定：满血 {state['my_hp_max']} ÷ 裸面板 "
                     f"{bare_my} = {scale:.2f}")
    else:
        scale = repo.HP_SCALE
    foe_max = int(repo.stats(foe_card)["hp"] * scale)
    state["foe_hp_max"] = foe_max
    ratio = None
    if img is not None:
        try:
            ratio = hpbar.foe_ratio(img)
        except Exception as e:                      # noqa: BLE001
            notes.append(f"对方血条读取失败（{type(e).__name__}），按满血估算")
    if ratio is not None:
        state["foe_hp"] = max(1, int(foe_max * ratio))
        notes.append(f"对方血量按血条比例 {ratio:.0%} 估为 "
                     f"{state['foe_hp']}/{foe_max}（估算，可能有偏差）")
    else:
        state["foe_hp"] = foe_max
        notes.append("没读到对方血条，按满血估算（会偏乐观）")

    my_pp = {s["id"]: s["pp_now"] for s in my_card["skills"] if s.get("pp_now") is not None}
    if my_pp:
        state["my_pp"] = my_pp
    return my_card, foe_card, state, notes


def track_state(st, my_card, tracker):
    """把跨回合状态（能力等级 / 回合类效果）并进 state。

    换精灵就重开一个 tracker —— 能力等级和回合类效果都是**跟着场上这只精灵**
    走的，换人一律清零。
    """
    if my_card is None or st is None:
        return tracker
    if tracker is None or tracker.card.get("id") != my_card.get("id"):
        tracker = turnstate.Tracker(my_card)
    tracker.on_frame(st.get("turn"), st.get("skills"), st.get("detail"))
    return tracker


def active_line(tracker):
    """把生效中的状态压成一行（没有就返回 None）。"""
    if not tracker or not tracker.my_active:
        return None
    parts = []
    for a in tracker.my_active:
        bits = []
        if a.stat_up:
            bits.append("全属性+1" if a.stat_up.get("全") == 1
                        else "、".join(f"{k}+{v}" for k, v in a.stat_up.items()))
        if a.control:
            bits.append("控场")
        if a.dmg_cap:
            bits.append(f"挡伤≤{a.dmg_cap}")
        for lb in (a.labels or [])[:1]:
            bits.append(lb.split("：", 1)[-1])
        parts.append(f"{a.name}({a.turns}回合" +
                     ("".join("，" + b for b in bits) if bits else "") + ")")
    return "状态：" + " ".join(parts)


def _card_of(name, cutoff=0.55):
    """名字 → 精灵卡片。返回 (card, score)。"""
    if not name:
        return None, 0.0
    for sid, nm, sc in repo.match_spirit(name, cutoff=cutoff):
        if nm == name or sc > 0.9:
            c = repo.card(sid)
            if c:
                return c, sc
    hits = repo.match_spirit(name, cutoff=cutoff)
    if hits:
        c = repo.card(hits[0][0])
        return c, hits[0][2]
    return None, 0.0


def lines_of(my_card, foe_card, state, notes, res=None, tracker=None):
    """把判定结果压成悬浮窗要显示的三行（+ 状态 + 提示）。"""
    if not my_card or not foe_card or res is None:
        head = "识别中…"
        if my_card or foe_card:
            head = f"我：{my_card['name'] if my_card else '?'}  敌：{foe_card['name'] if foe_card else '?'}"
        return [head] + notes[:3]

    rec = res["recommend"]
    out = [f"▶ 推荐：{rec['action']}",
           f"理由：{rec['reason']}",
           f"最坏：{rec['worst_case']}"]
    alts = rec.get("alt") or []
    if alts:
        out.append("备选：" + " / ".join(a[0] for a in alts[:2]))
    act = active_line(tracker)
    if act:
        out.append(act)
    warn = list(res.get("caveats") or []) + list(notes or [])
    if warn:
        out.append("⚠ " + "；".join(warn[:2]))
    return out


def render(my_card, foe_card, state, notes, res):
    """终端里的一份详细输出（调试与自检用）。"""
    if res is None:
        return "\n".join(lines_of(my_card, foe_card, state, notes))
    L = [f"我：{my_card['name']} [{my_card['element']}]  "
         f"{state.get('my_hp')}/{state.get('my_hp_max')}",
         f"敌：{foe_card['name']} [{foe_card['element']}]  "
         f"{res['foe']['hp']}/{res['foe']['hp_max']}（估算）"]
    for a in res["actions"]:
        if a["kind"] != "skill":
            continue
        lo, mid, hi = a["dmg"]
        mark = "稳杀" if a["kill_guaranteed"] else ("可杀" if a["kill_possible"] else "")
        L.append(f"   {a['skill']['name']:<14} 威力{a['skill']['power']:>4} "
                 f"先制{a['priority']} 伤害 {lo}~{hi}(期望{mid}) {mark}")
    L.append("★ " + res["recommend"]["action"] + "   " + res["recommend"]["reason"])
    L.append("  最坏：" + res["recommend"]["worst_case"])
    for c in (res.get("caveats") or []) + notes:
        L.append("  ⚠ " + c)
    return "\n".join(L)


def once(image=None, verbose=True):
    """跑一次全链路。image 为 None 就实时抓屏。"""
    if image:
        st = scene.read_image(image)
        img = _open(image)
    else:
        st, img = scene.read_screen()
    if not st:
        return None, None, None, None, None
    my_card, foe_card, state, notes = build(st, img)
    if verbose:
        print(scene.describe(st))
        print("-" * 60)
    if not my_card or not foe_card or state is None:
        return st, my_card, foe_card, state, notes
    res = decide.analyze(my_card, foe_card, state)
    return st, my_card, foe_card, state, notes, res


def _open(path):
    try:
        from PIL import Image
        return Image.open(path)
    except Exception:  # noqa: BLE001
        return None


# ----------------------------------------------------------------- 主循环
class App:
    def __init__(self, interval=1.2, use_overlay=True):
        self.interval = interval
        self.use_overlay = use_overlay
        self.force = threading.Event()
        self.stop = threading.Event()
        self.last_sig = None
        self.ov = None
        self.tracker = None

    # ---- 后台：抓屏 → 判定 → 送悬浮窗
    def worker(self):
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception as e:                    # noqa: BLE001
                msg = f"出错：{type(e).__name__}: {e}"
                print(msg)
                if self.ov:
                    self.ov.set_lines([msg], ["#f87171"])
            self.force.wait(self.interval)
            self.force.clear()

    def tick(self):
        st, img = scene.read_screen()
        if not st:
            if self.ov:
                self.ov.set_lines(["找不到游戏窗口（先运行 python main.py --pick 选一次）"])
            return
        sig = _sig(st)
        if sig == self.last_sig and not self.force.is_set():
            return                                    # 画面没变，省一次 OCR
        self.last_sig = sig
        my_card, foe_card, state, notes = build(st, img)
        # ---- 跨回合状态：必须每帧喂（PP 下降是在回合中途观察到的）
        self.tracker = track_state(st, my_card, self.tracker)
        if state is not None and self.tracker:
            state["my_levels"] = dict(self.tracker.my_levels)
            state["my_active"] = self.tracker.my_active
            if self.tracker.my_levels:
                notes = list(notes) + [f"能力等级（按 PP/选中态自动跟踪）："
                                       f"{self.tracker.my_levels}"]
        res = None
        if my_card and foe_card and state is not None:
            res = decide.analyze(my_card, foe_card, state)
        print("\n" + "=" * 62)
        print(render(my_card, foe_card, state, notes, res))
        if self.ov:
            self.ov.set_lines(lines_of(my_card, foe_card, state, notes, res,
                                       self.tracker))

    # ---- 跑
    def run(self):
        import hotkey
        from overlay import Overlay

        self.ov = Overlay()
        self.ov.set_lines(["赛尔号辅助已启动，正在加载识别模型…"])
        # 先热一下 OCR：模型加载要几秒，放在这里就不会让第一次判定看起来像卡死
        try:
            ocr.engine()
        except Exception as e:                        # noqa: BLE001
            print(f"识别模型加载失败：{type(e).__name__}: {e}")
        self.ov.set_lines(["已就绪，等待游戏画面…（F8 立即重算）"])
        hk = hotkey.Hotkey(lambda: self.force.set(), key="F8", hk_id=1)
        hk.start()
        hk2 = hotkey.Hotkey(lambda: self.ov and self.ov.toggle_click_through(),
                            key="F9", hk_id=2)
        hk2.start()
        print(f"热键 {hk.key}=立即重算  {hk2.key}=切换鼠标穿透  右键/Esc=关闭窗口")
        t = threading.Thread(target=self.worker, daemon=True)
        t.start()
        try:
            self.ov.run()
        finally:
            self.stop.set()
            hk.stop()
            hk2.stop()


def selftest():
    """自检：把每一环单独跑一遍，不碰游戏画面。出问题时把结果发我。"""
    import traceback

    ok = []

    def step(name, fn):
        try:
            detail = fn()
            ok.append((name, True, detail))
        except Exception as e:                        # noqa: BLE001
            ok.append((name, False, f"{type(e).__name__}: {e}"))
            traceback.print_exc()

    import paths
    print("=" * 60)
    print(paths.describe())

    def _db():
        import db
        conn = db.connect()
        try:
            n = conn.execute("SELECT count(*) FROM spirits").fetchone()[0]
        finally:
            conn.close()
        sid = repo.match_spirit("雷伊")
        c = repo.card(sid[0][0]) if sid else None
        return f"精灵 {n} 只；匹配「雷伊」→ {c['name'] if c else '失败'}"

    def _rules():
        import rules
        return (f"克制 圣灵电→混沌光 = {rules.elem_coef('圣灵电', '混沌光')}；"
                f"能力+2 = {rules.ability_mult(2):.2f}")

    def _ocr():
        from PIL import Image, ImageDraw
        p = os.path.join(HERE, "data", "_selftest.png")
        im = Image.new("RGB", (420, 60), (10, 14, 20))
        ImageDraw.Draw(im).text((14, 18), "Lv.100 雷伊 1033/1093", fill=(240, 246, 250))
        im.save(p)
        items = ocr.read(p)
        os.remove(p)
        txt = " ".join(t for t, *_ in items)
        if "1033" not in txt:
            raise RuntimeError(f"没认出数字：{txt!r}")
        return f"认出 {len(items)} 块：{txt}"

    def _win():
        cs = capture.candidates()
        return f"本机可见窗口 {len(cs)} 个，最大的：{cs[0].title[:40]!r}" if cs else "没找到窗口"

    def _hot():
        import hotkey
        h = hotkey.Hotkey(lambda: None, key="F8", hk_id=99)
        h.start()
        good = h.wait_ready(2.0)
        err = h.error
        h.stop()
        if not good:
            raise RuntimeError(f"F8 注册失败：{err}")
        return "F8 注册成功（只监听，不发送按键）"

    def _ui():
        from overlay import Overlay
        ov = Overlay()
        ov.set_lines(["自检", "悬浮窗正常", "这一行是第三行"])
        ov.root.after(700, ov.root.destroy)
        ov.root.after(60, ov.poll)
        ov.root.mainloop()
        return "悬浮窗能创建、能渲染、能关闭"

    step("数据库", _db)
    step("规则与系数", _rules)
    step("OCR（自己画一张图认）", _ocr)
    step("窗口枚举", _win)
    step("全局热键", _hot)
    step("悬浮窗", _ui)

    print("-" * 60)
    bad = 0
    for name, good, detail in ok:
        print(f"{'[OK]  ' if good else '[FAIL]'} {name}：{detail}")
        bad += 0 if good else 1
    print("-" * 60)
    print("全部通过，可以用了。" if not bad else f"有 {bad} 项没过，把上面内容发我。")
    return bad


def main():
    ap = argparse.ArgumentParser(description="赛尔号巅峰之战辅助")
    ap.add_argument("--pick", action="store_true", help="挑一次游戏窗口并记住")
    ap.add_argument("--image", help="只对一张图片跑一遍")
    ap.add_argument("--interval", type=float, default=1.2, help="轮询间隔（秒）")
    ap.add_argument("--no-ui", action="store_true", help="不开悬浮窗，只在终端打印")
    ap.add_argument("--selftest", action="store_true", help="自检：逐环检查能否工作")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(1 if selftest() else 0)
    if args.pick:
        capture.pick()
        return
    if args.image:
        out = once(args.image)
        if len(out) == 6:
            print("*" * 62)
            print(render(out[1], out[2], out[3], out[4], out[5]))
        return
    if args.no_ui:
        while True:
            out = once(verbose=True)
            if len(out) == 6:
                print("*" * 62)
                print(render(out[1], out[2], out[3], out[4], out[5]))
            time.sleep(args.interval)
    App(interval=args.interval).run()


if __name__ == "__main__":
    main()
