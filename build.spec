# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包脚本：把整条链路打成一个 exe，用户不用装 Python。

    python -m PyInstaller build.spec --noconfirm

产物在 dist/ 下。
"""
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

# spec 文件里没有 __file__；PyInstaller 会注入 SPECPATH（spec 所在目录）
HERE = SPECPATH

datas = [
    (os.path.join(HERE, "data", "seer.db"), "data"),      # 精灵/技能库 4940 只
    (os.path.join(HERE, "data", "coef.json"), "data"),    # 属性克制系数表
]
binaries = []
hiddenimports = []

# RapidOCR 自带 onnx 模型（det/cls/rec 共约 32MB）和 config.yaml，
# 必须整包收进去，否则运行时报"找不到模型"。
for pkg in ("rapidocr", "onnxruntime"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

hiddenimports += collect_submodules("PIL")
hiddenimports += [
    "sqlite3", "tkinter", "tkinter.font",
    "numpy", "cv2", "shapely", "pyclipper", "omegaconf", "yaml",
]

# 这些库一个都用不上，装上也只是白占体积（有的会连带拖进几十 MB）
excludes = [
    "matplotlib", "scipy", "pandas", "pytest", "IPython", "notebook",
    "PySide2", "PySide6", "PyQt5", "PyQt6", "torch", "tensorflow",
    "paddle", "paddleocr", "sklearn", "sympy", "setuptools",
    # 下面这堆是实测从别处被连带拉进来的，我们一行都不用：
    # pyarrow 81MB / faiss 74MB / tokenizers 7MB / hf_xet 7MB …（合计约 177MB）
    "pyarrow", "faiss", "faiss_cpu", "tokenizers", "hf_xet", "safetensors",
    "transformers", "datasets", "sentence_transformers", "pydantic_core",
    "pydantic", "grpc", "google", "jax", "dask", "distributed",
    "numexpr", "bottleneck", "sqlalchemy", "IPython", "jupyter",
]

# 还要按文件再剔一遍：excludes 只管 Python 模块，但这些是数据文件和 DLL，
# 得直接从打包清单里划掉。
#   opencv_videoio_ffmpeg —— 31MB 的视频编解码器，我们只处理静态截图
#   PIL._avif / _webp      —— 7.8MB 的图片编解码器，游戏截图是 BMP/PNG
#   torch-*.dist-info      —— torch 已经排除，只剩它的元数据还在
DROP = (
    "cv2\\opencv_videoio_ffmpeg",
    "cv2/opencv_videoio_ffmpeg",
    "PIL\\_avif",
    "PIL/_avif",
    "PIL\\_webp",
    "PIL/_webp",
    "torch-2",
    "torch\\",
    "torch/",
)


def _keep(entry):
    name = str(entry[0]).replace("/", "\\")
    return not any(d.replace("/", "\\") in name for d in DROP)


block_cipher = None

a = Analysis(
    [os.path.join(HERE, "main.py")],
    pathex=[HERE],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# 剔掉上面 DROP 里列的 DLL / 数据文件
_before = len(a.binaries) + len(a.datas)
a.binaries = [x for x in a.binaries if _keep(x)]
a.datas = [x for x in a.datas if _keep(x)]
print(f"[build.spec] 按体积剔除 {_before - len(a.binaries) - len(a.datas)} 项")

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="SeerHelper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # UPX 压缩会把 onnxruntime 的 DLL 压坏，别开
    runtime_tmpdir=None,
    console=True,              # 要留着终端：--pick 选窗口要在里面输编号
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
