# -*- coding: utf-8 -*-
"""造一张"像真的"战斗截图，用来在没有游戏可开时验证整条链路。

画的是 1040x520（和用户给的视频截图同尺寸），包含：
  顶部  双方血条（左 30% 已填 / 右 65% 已填）、Lv.100 + 精灵名、中央「第16回合」
  中部  飘字「克制-285」和「+551」
  底部  四个技能格（技能名 / 次数 / 威力）
  左下  圆形详情面板（技能名折成两行 + 次数 + 威力）

用法: python tools/make_fake_battle.py [输出路径]
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from console import fix_console; fix_console()   # noqa: E402


def font(size):
    from PIL import ImageFont
    for p in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf",
              r"C:\Windows\Fonts\Deng.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:  # noqa: BLE001
                pass
    return ImageFont.load_default()


def make(path, my_name="万霆神律·雷伊", foe_name="妙时天女",
         my_ratio=0.30, foe_ratio=0.65, turn=16,
         skills=(("雷·裂阳圣耀", 19, 20, 90), ("雷·传承怒意", 5, 5, 0),
                 ("雷·万鸣天镟", 5, 5, 0), ("雷·寰宇涤魔", 5, 5, 0)),
         detail=("帕诺", "七星阵列", 4, 5, 160),
         floats=(("克制-285", 640, 250, (255, 60, 60)),
                 ("+551", 116, 254, (120, 255, 120)))):
    from PIL import Image, ImageDraw
    W, H = 1040, 520
    img = Image.new("RGB", (W, H), (14, 12, 42))
    d = ImageDraw.Draw(img)
    f18, f20, f26, f40 = font(18), font(20), font(26), font(40)

    # --- 血条（左右各一条，长度不同，填充色不同）
    def bar(x0, y0, x1, y1, ratio, fill, empty):
        d.rectangle([x0, y0, x1, y1], fill=empty)
        d.rectangle([x0, y0, x0 + int((x1 - x0) * ratio), y1], fill=fill)

    d.text((18, 12), f"Lv.100 {my_name}", font=f18, fill=(245, 245, 245))
    bar(18, 38, 358, 52, my_ratio, (92, 232, 118), (22, 56, 34))
    d.text((860, 12), f"Lv.100 {foe_name}", font=f18, fill=(245, 245, 245))
    bar(680, 38, 1022, 52, foe_ratio, (242, 182, 62), (58, 20, 26))
    # 回合 / 倍率
    d.text((470, 40), f"第{turn}回合", font=f26, fill=(250, 250, 250))
    d.text((360, 16), "克制 1.25", font=f18, fill=(255, 230, 120))
    d.text((760, 16), "微弱 0.75", font=f18, fill=(150, 200, 255))
    # 我的明文血量（对方没有）
    d.text((150, 56), "1033/1093", font=f20, fill=(130, 250, 150))

    # --- 飘字
    for t, x, y, c in floats:
        d.text((x, y), t, font=f40, fill=c)

    # --- 左下圆形详情面板（技能名折两行 + 次数 + 威力）
    d.ellipse([8, 350, 210, 512], fill=(226, 158, 38), outline=(255, 236, 190), width=3)
    n1, n2, pp, pm, pw = detail
    d.text((62, 362), n1, font=f26, fill=(255, 255, 255))
    d.text((40, 394), n2, font=f26, fill=(255, 255, 255))
    d.text((30, 434), "次数", font=f20, fill=(255, 250, 235))
    d.text((130, 434), f"{pp}/{pm}", font=f20, fill=(255, 255, 255))
    d.text((30, 464), "威力", font=f20, fill=(255, 250, 235))
    d.text((130, 464), str(pw), font=f20, fill=(255, 255, 255))

    # --- 底部四个技能格
    for i, (nm, pp, pm, pw) in enumerate(skills):
        x = 225 + i * 195
        d.rectangle([x, 440, x + 180, 512], fill=(30, 40, 70), outline=(90, 130, 200))
        d.text((x + 10, 448), nm, font=f20, fill=(255, 255, 255))
        d.text((x + 10, 476), f"次数 {pp}/{pm}", font=f20, fill=(220, 220, 220))
        d.text((x + 10, 496), f"威力 {pw}", font=f20, fill=(220, 220, 220))

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    img.save(path)
    return path


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "fake_battle.png")
    print("已生成:", make(out))
