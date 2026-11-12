"""G3：应用层底图（缩放居中裁切 / 模糊 / 色块化）与 ComfyUI 节点逐像素对比。"""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shutil, json
import numpy as np
from PIL import Image
from _engine_session import get_engine, wait_prompt
from fxstudio import imaging, paths

SRC = r"tests\input\ainvfx_tank_demo.png"
e = get_engine()
inp = paths.RUNTIME_DIR / "engine" / "input"; outd = paths.RUNTIME_DIR / "engine" / "output"
shutil.copy(SRC, inp / "g3_src.png")
ref = Image.open(SRC)
report = []
for (w, h) in [(1024, 576), (576, 1024), (768, 768)]:
    for (r, s, c) in [(12, 4.0, 8), (6, 2.0, 6)]:
        tag = f"g3_{w}x{h}_{r}_{c}"
        wf = {"l": {"class_type": "LoadImage", "inputs": {"image": "g3_src.png"}},
              "sc": {"class_type": "ImageScale", "inputs": {"upscale_method": "lanczos", "crop": "center", "width": w, "height": h, "image": ["l", 0]}},
              "bl": {"class_type": "ImageBlur", "inputs": {"image": ["sc", 0], "blur_radius": r, "sigma": s}},
              "qu": {"class_type": "ImageQuantize", "inputs": {"image": ["bl", 0], "colors": c, "dither": "none"}},
              "s1": {"class_type": "SaveImage", "inputs": {"images": ["sc", 0], "filename_prefix": tag + "_m1"}},
              "s2": {"class_type": "SaveImage", "inputs": {"images": ["qu", 0], "filename_prefix": tag + "_m2"}}}
        h_ = wait_prompt(e, e.queue(wf))
        for mode, node in ((1, "s1"), (2, "s2")):
            fn = h_["outputs"][node]["images"][0]["filename"]
            eng = np.array(Image.open(outd / fn).convert("RGB")).astype(int)
            app = np.array(imaging.make_base(ref, mode, w, h, r, s, c)).astype(int)
            diff = np.abs(eng - app)
            same = float((diff.max(axis=2) == 0).mean())
            report.append({"case": f"{w}x{h} r{r} s{s} c{c} mode{mode}", "identical_px": round(same, 6), "max_abs": int(diff.max()), "mean_abs": round(float(diff.mean()), 5)})
for r in report: print(json.dumps(r, ensure_ascii=False))
