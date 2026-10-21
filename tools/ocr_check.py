# -*- coding: utf-8 -*-
"""截图工具 + OCR 冒烟测试。

用法：
  python tools/ocr_check.py               # 自己画一张模拟战斗截图，跑 OCR
  python tools/ocr_check.py <图片路径>     # 识别指定图片

识别引擎：RapidOCR（默认 onnxruntime 后端），体积≈onnxruntime 17MB + 模型 15MB。
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from console import fix_console; fix_console()


def make_sample(path):
    """造一张和游戏 UI 排版相近的图，用来验证 OCR 与解析。"""
    from PIL import Image, ImageDraw, ImageFont

    W, H = 1040, 520
    img = Image.new("RGB", (W, H), (12, 10, 40))
    d = ImageDraw.Draw(img)

    def font(size):
        for p in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf",
                  r"C:\Windows\Fonts\Deng.ttf"):
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, size)
                except Exception:  # noqa: BLE001
                    pass
        return ImageFont.load_default()

    f20, f28, f40 = font(20), font(28), font(40)
    # 顶部：等级 + 体力
    d.text((20, 18), "Lv.100 万霆神律·雷伊", font=f20, fill=(255, 255, 255))
    d.text((470, 18), "克制", font=f20, fill=(255, 230, 120))
    d.text((560, 18), "微弱", font=f20, fill=(150, 200, 255))
    d.text((880, 18), "Lv.100 妙时天女", font=f20, fill=(255, 255, 255))
    d.text((180, 46), "1033/1093", font=f28, fill=(120, 255, 140))
    d.text((700, 46), "870/1132", font=f28, fill=(255, 140, 160))
    d.text((500, 46), "第16回合", font=f28, fill=(255, 255, 255))
    # 飘字
    d.text((640, 250), "克制-285", font=f40, fill=(255, 60, 60))
    d.text((120, 250), "+551", font=f40, fill=(120, 255, 120))
    # 底部技能面板
    for i, (nm, pp, pw) in enumerate([("雷·黎阳圣耀", "19/20", "90"),
                                      ("雷·传承怒意", "5/5", "0"),
                                      ("雷·万鸣天镟", "5/5", "0"),
                                      ("记忆铭刻", "20/20", "85")]):
        x = 220 + i * 195
        d.rectangle([x, 445, x + 180, 510], outline=(90, 130, 200))
        d.text((x + 10, 452), nm, font=f20, fill=(255, 255, 255))
        d.text((x + 10, 478), f"次数 {pp}", font=f20, fill=(220, 220, 220))
        d.text((x + 10, 478 + 22), f"威力 {pw}", font=f20, fill=(220, 220, 220))
    img.save(path)
    return path


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args:
        path = args[0]
    else:
        path = os.path.join(ROOT, "data", "sample_battle.png")
        make_sample(path)
        print(f"[造图] {path}")

    import ocr
    items = ocr.read(path)
    print(f"识别到 {len(items)} 个文本块")
    for t, s, x1, y1, x2, y2 in items:
        print(f"  {s:.2f}  ({int(x1):>4},{int(y1):>4})  {t}")
    print()
    d = ocr.parse_battle(items)
    print("体力:", d["hp_pairs"])
    print("等级:", d["levels"])
    print("回合:", d["turns"])
    print("伤害数字:", d["dmg"])


if __name__ == "__main__":
    main()
