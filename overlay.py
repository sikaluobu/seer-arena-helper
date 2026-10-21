# -*- coding: utf-8 -*-
"""悬浮窗：把推荐结果贴在游戏画面上。

设计要点（都来自需求里定下的体验指标）：
  · 置顶、半透明、**不抢焦点** —— 游戏该收的键还得收到，鼠标不用点它。
  · 三行就够：推荐动作 / 理由 / 最坏情况。多余信息折叠进"详情"。
  · 默认可拖拽（按住任意位置拖），F9 切换"鼠标穿透"后连点都透过去。
  · 答案上屏目标 < 1 秒，所以界面只做渲染，不做任何计算。

tkinter 是标准库，不增加体积；重活（OCR/计算）都在别的线程里干，
结果通过队列送进来，这里只负责画。
"""
import queue
import tkinter as tk

from console import fix_console; fix_console()

FONT = "Microsoft YaHei UI"
BG = "#101418"
FG = "#f2f6fa"
DIM = "#9aa7b4"
ACCENT = "#4ade80"      # 推荐动作
WARN = "#fbbf24"        # 最坏情况 / 不确定
BAD = "#f87171"

DEFAULT_POS = (40, 60)
DEFAULT_ALPHA = 0.88
MAX_CHARS = 96          # 单行最长字符数，太长的提示会被截断加省略号


def _clip(text, n=MAX_CHARS):
    t = (text or "").replace("\n", " ").strip()
    return t if len(t) <= n else t[: n - 1] + "…"


class Overlay:
    """一个常驻的悬浮小窗。

    用法：
        ov = Overlay()
        ov.set_lines(["▶ 推荐：雷·裂阳圣耀", "理由：先手+3，先手稳赚", "最坏：…"])
        ov.run()          # 阻塞，进 tkinter 主循环
    """

    def __init__(self, alpha=DEFAULT_ALPHA, pos=DEFAULT_POS, width=460):
        self.max_width = width
        self.root = tk.Tk()
        self.root.title("赛尔号辅助")
        self.root.overrideredirect(True)          # 无边框
        self.root.attributes("-topmost", True)    # 置顶
        try:
            self.root.attributes("-alpha", alpha)
        except tk.TclError:
            pass
        self.root.configure(bg=BG)
        self.root.geometry(f"{width}x120+{pos[0]}+{pos[1]}")

        self.frame = tk.Frame(self.root, bg=BG, padx=10, pady=7)
        self.frame.pack(fill="both", expand=True)
        self.labels = []
        self._build(3)

        self.msgq = queue.Queue()
        self.click_through = False
        self._drag = None
        self._bind_drag()
        self.root.bind("<Button-3>", lambda e: self.root.destroy())   # 右键关闭
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)

    # ------------------------------------------------------------ 构建
    def _build(self, n):
        for lb in self.labels:
            lb.destroy()
        self.labels = []
        # 第 1 行是推荐动作（绿），中间是理由/最坏情况（白），
        # 末尾的备选和 ⚠ 提示压暗、字号小一号，别抢主信息的注意力
        colors = [ACCENT, FG, WARN, DIM, DIM, DIM]
        sizes = [12, 9, 9, 9, 8, 8]
        for i in range(n):
            lb = tk.Label(self.frame, text="", bg=BG,
                          fg=colors[i % len(colors)],
                          font=(FONT, sizes[i % len(sizes)]),
                          anchor="w", justify="left",
                          wraplength=self.max_width - 26)
            lb.pack(fill="x", anchor="w")
            self.labels.append(lb)

    def _bind_drag(self):
        self.root.bind("<Button-1>", self._drag_start)
        self.root.bind("<B1-Motion>", self._drag_move)

    def _drag_start(self, e):
        self._drag = (e.x_root - self.root.winfo_x(),
                      e.y_root - self.root.winfo_y())

    def _drag_move(self, e):
        if not self._drag:
            return
        self.root.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    # ------------------------------------------------------------ 内容
    def set_lines(self, lines, colors=None):
        """线程安全：把要显示的行塞进队列，主线程负责真正绘制。"""
        self.msgq.put(("lines", list(lines), colors))

    def set_text(self, text):
        self.set_lines([text])

    def set_click_through(self, on):
        self.msgq.put(("clickthrough", on, None))

    def toggle_click_through(self):
        self.set_click_through(not self.click_through)

    def _apply_click_through(self, on):
        """给窗口加上 WS_EX_TRANSPARENT，让鼠标事件直接穿过去。"""
        self.click_through = bool(on)
        try:
            import ctypes
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            u = ctypes.windll.user32
            style = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if on:
                style |= WS_EX_LAYERED | WS_EX_TRANSPARENT
            else:
                style &= ~WS_EX_TRANSPARENT
            u.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception:  # noqa: BLE001
            pass

    def _render(self, lines, colors=None):
        lines = [_clip(t) for t in lines]
        need = max(1, len(lines))
        if need != len(self.labels):
            self._build(max(need, 3))
        for i, lb in enumerate(self.labels):
            txt = lines[i] if i < len(lines) else ""
            lb.config(text=txt)
            if colors and i < len(colors) and colors[i]:
                lb.config(fg=colors[i])
        self.root.update_idletasks()
        # 宽高都按内容自适应，否则最长的两行会被截断/挤成多行
        w = min(self.frame.winfo_reqwidth(), self.max_width)
        h = self.frame.winfo_reqheight()
        self.root.geometry(f"{w}x{h}")

    # ------------------------------------------------------------ 循环
    def poll(self):
        try:
            while True:
                kind, a, b = self.msgq.get_nowait()
                if kind == "lines":
                    self._render(a, b)
                elif kind == "clickthrough":
                    self._apply_click_through(a)
                elif kind == "quit":
                    self.root.destroy()
                    return
        except queue.Empty:
            pass
        self.root.after(120, self.poll)

    def run(self):
        self.root.after(120, self.poll)
        self.root.mainloop()


def preview():
    """不接游戏，先看外观。"""
    ov = Overlay()
    ov.set_lines([
        "▶ 推荐：雷·裂阳圣耀（先手+3）",
        "理由：先手出手，对方换人/慢招都吃这一下",
        "最坏：对方用「万卍觉心法界镇」→ 我剩 655，对方剩 936",
    ])
    print("预览已打开：左键拖动、右键/Esc 关闭。")
    ov.run()


if __name__ == "__main__":
    preview()
