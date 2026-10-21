# -*- coding: utf-8 -*-
"""跨回合状态跟踪：能力等级 + 回合类效果。

**为什么需要这一层**：判断引擎原来是「单回合静态快照」，只知道画面这一帧。
但赛尔号的核心机制里大量效果是**跨回合**的：
    「4回合内免疫并反弹所有受到的异常状态」
    「3回合内令对手使用的属性技能无效」
    「全属性+1」（强化会一直挂着，直到被消强/换人）
不跟踪这些，引擎就会：把强化招当成零收益反复推荐、不知道自己的免疫还在、
不知道对方已经被封了属性技。

**怎么知道"我上一回合用了什么"**——两个信号，都要，互为校验：
  1) PP 递减（主）：底部技能格的「次数 x/y」是明文数字，你用了哪招，
     它的 PP 就少 1。这是最可靠的信号，因为它不需要任何额外的操作。
  2) 选中态（辅）：左下的圆形面板显示你当前点选/悬停的技能名。
     它比 PP 早一拍（你先点技能再点战斗），用于消歧；
     但你是"悬停"才会显示，所以不能只靠它。

**对方的技能看不到**（要点开才有文字，用户明确说过 OCR 不现实），
所以对方的回合类效果只能靠手动标记登记，这里不猜。
"""
import effects
import rules

MAX_TURNS = 10      # 单条效果的回合数上限，超过就是解析错了


class Active:
    """一条正在生效的回合类效果。"""

    __slots__ = ("name", "turns", "stat_up", "control", "dmg_cap",
                 "labels", "src")

    def __init__(self, name, turns, stat_up=None, control=False,
                 dmg_cap=0, labels=(), src=None):
        self.name = name
        self.turns = max(1, min(MAX_TURNS, int(turns or 1)))
        self.stat_up = dict(stat_up or {})
        self.control = control
        self.dmg_cap = dmg_cap or 0
        self.labels = list(labels or ())
        self.src = src

    def tick(self):
        self.turns -= 1
        return self.turns > 0

    def __repr__(self):
        return f"<{self.name} {self.turns}回合 {self.stat_up}>"


class Tracker:
    """按回合推进的场面状态跟踪器。

    用法：
        t = Tracker(my_card)
        t.on_frame(turn_no, cells, detail)   # 每帧调用
        t.my_levels, t.my_active             # 给 decide.analyze 的 state
    """

    def __init__(self, my_card=None, my_levels=None):
        self.card = my_card
        self.turn = None
        self.pp = {}              # {技能名: (剩余, 上限)}
        self.used = None          # 本回合确认使用的技能名
        self._drop = 0            # 本回合最大 PP 降幅（用于消歧）
        self.hover = None         # 当前选中态的技能名
        self.my_active = []
        self.foe_active = []      # 对方效果看不到，只能 mark_foe_effect 手动登记
        self.my_levels = dict(my_levels or {})
        self.notes = []

    # ---------------------------------------------------------------- 帧更新
    def on_frame(self, turn_no, cells=None, detail=None):
        """每帧调用。返回 True 表示"检测到了新回合"。

        注意顺序：**先吸收 PP，再判断是否换回合**。
        PP 的下降发生在你出招的那一刻（回合中途），所以必须在回合内就观察到它；
        等到跨回合那一帧再看，画面上的 PP 已经和本回合快照一致了，看不出变化。
        """
        if detail and detail.get("name"):
            self.hover = detail["name"]
        if cells:
            self._absorb_pp(cells)

        new_turn = (turn_no is not None and turn_no != self.turn)
        if not new_turn:
            return False

        if self.turn is not None:
            self._end_turn()
        self.turn = turn_no
        self.used = None          # 新回合重新开始观察
        return True

    def _absorb_pp(self, cells):
        """记录 PP 快照；**发现下降就判定这是本回合使用的技能**。"""
        for c in (cells or []):
            nm, pp = c.get("name"), c.get("pp")
            if not nm or pp is None:
                continue
            old = self.pp.get(nm)
            self.pp[nm] = (pp, c.get("pp_max"))
            if old is None or pp >= old[0]:
                continue
            # PP 掉得最多的那个就是实际用的招
            if self.used is None or (old[0] - pp) > self._drop:
                self.used, self._drop = nm, old[0] - pp

    def _end_turn(self):
        """上一回合结束：登记用过的招 → 已有状态减 1 → 重算能力等级。"""
        used = self.used or self.hover
        self.my_active = [a for a in self.my_active if a.tick()]
        if used:
            self._register(used)
        self._recompute_levels()

    def _register(self, skill_name):
        """把某技能带来的回合类效果/强化登记成持续状态。"""
        if not self.card:
            return
        target = None
        for s in self.card.get("skills", []):
            if s["name"] == skill_name or skill_name in s["name"]:
                target = s
                break
        if not target:
            return
        out = effects.parse_skill(target)
        agg = effects.agg_from(out["facts"], out["marks"])
        # 纯属性技才有持续收益；攻击技的时效性效果（下1回合增伤）也记，
        # 但只记它自己写得明的回合数
        turns = agg.get("turn_fx_max") or 0
        if not (agg.get("stat_up") or agg.get("control")
                or agg.get("dmg_cap") or turns):
            return
        if not turns:
            turns = 1
        # 同名效果重复使用 → 刷新而不是叠一条
        self.my_active = [a for a in self.my_active if a.name != skill_name]
        self.my_active.append(Active(
            skill_name, turns,
            stat_up=agg.get("stat_up"), control=agg.get("control"),
            dmg_cap=agg.get("dmg_cap"),
            labels=agg.get("turn_fx"), src=target["id"]))
        self.notes.append(f"第{self.turn}回合起 {skill_name}：{turns}回合"
                          + ("／" + "、".join(agg["turn_fx"]) if agg.get("turn_fx") else ""))

    def _recompute_levels(self):
        """把生效中的强化折成能力等级（同名属性取最高，上限 ±6）。"""
        lv = {}
        for a in self.my_active:
            for stat, n in (a.stat_up or {}).items():
                if stat == "全":
                    for k in ("atk", "spatk", "def", "spdef", "speed"):
                        lv[k] = lv.get(k, 0) + n
                else:
                    key = {"攻": "atk", "特攻": "spatk", "防": "def",
                           "特防": "spdef", "速": "speed"}.get(stat, stat)
                    lv[key] = lv.get(key, 0) + n
        self.my_levels = {k: max(rules.ABILITY_MIN, min(rules.ABILITY_MAX, v))
                          for k, v in lv.items()}

    # ---------------------------------------------------------------- 外部接口
    def mark_reset_levels(self):
        """被消强时调用：能力等级清零（回合类效果本身不因此消失）。"""
        self.my_levels = {}

    def mark_foe_effect(self, name, turns, dmg_cap=0):
        """手动登记对方的回合类效果（对方技能看不到，只能手标）。"""
        self.foe_active.append(Active(name, turns, dmg_cap=dmg_cap))
