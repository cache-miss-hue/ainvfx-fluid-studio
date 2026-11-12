"""fx_private：AInVFX Fluid Studio 的私有小节点。

FXLoadControlFrames：读取应用层写好的控制视频描述（job_dir/control.json + 底图 PNG + 笔触 PNG），
在内存里无损组装成 IMAGE 批次。合成方式与 ComfyUI 核心 Painter 节点逐行一致
（笔触 RGBA 按 alpha 叠到底图上，float32），未画关键帧的位置为纯黑帧。
"""
import hashlib
import json
import os

import numpy as np
import torch
from PIL import Image


def _load_rgb(path):
    img = Image.open(path)
    img = img.convert("RGB")
    return np.array(img).astype(np.float32) / 255.0


def _composite(base_np, strokes_path, w, h):
    # 与 comfy_extras/nodes_painter.py 相同
    painter_img = Image.open(strokes_path).convert("RGBA")
    if painter_img.size != (w, h):
        painter_img = painter_img.resize((w, h), Image.LANCZOS)
    painter_np = np.array(painter_img).astype(np.float32) / 255.0
    rgb = painter_np[:, :, :3]
    alpha = painter_np[:, :, 3:4]
    return rgb * alpha + base_np * (1.0 - alpha)


class FXLoadControlFrames:
    CATEGORY = "fx_private"
    RETURN_TYPES = ("IMAGE", "INT", "INT", "INT", "IMAGE")
    RETURN_NAMES = ("images", "width", "height", "length", "tail_guide")
    FUNCTION = "load"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"job_dir": ("STRING", {"default": ""})}}

    @classmethod
    def IS_CHANGED(cls, job_dir):
        m = hashlib.sha256()
        spec_path = os.path.join(job_dir, "control.json")
        with open(spec_path, "rb") as f:
            data = f.read()
        m.update(data)
        spec = json.loads(data.decode("utf-8"))
        for kf in spec.get("keyframes", []):
            for k in ("base", "strokes"):
                if kf.get(k):
                    with open(os.path.join(job_dir, kf[k]), "rb") as f:
                        m.update(f.read())
        if spec.get("tail_guide"):
            with open(os.path.join(job_dir, spec["tail_guide"]), "rb") as f:
                m.update(f.read())
        return m.hexdigest()

    def load(self, job_dir):
        with open(os.path.join(job_dir, "control.json"), "r", encoding="utf-8") as f:
            spec = json.load(f)
        w, h, n = int(spec["width"]), int(spec["height"]), int(spec["length"])
        out = torch.zeros((n, h, w, 3), dtype=torch.float32)
        for kf in spec.get("keyframes", []):
            idx = int(kf["index"])
            if not (0 <= idx < n):
                raise ValueError(f"关键帧帧号 {idx} 超出范围 0..{n - 1}")
            if kf.get("base"):
                base = _load_rgb(os.path.join(job_dir, kf["base"]))
                if base.shape[0] != h or base.shape[1] != w:
                    raise ValueError(f"底图尺寸 {base.shape[1]}x{base.shape[0]} 与输出 {w}x{h} 不一致")
            else:
                base = np.zeros((h, w, 3), dtype=np.float32)
            if kf.get("strokes"):
                frame = _composite(base, os.path.join(job_dir, kf["strokes"]), w, h)
            else:
                frame = base
            out[idx] = torch.from_numpy(np.ascontiguousarray(frame))
        if spec.get("tail_guide"):
            tail = torch.from_numpy(_load_rgb(os.path.join(job_dir, spec["tail_guide"]))).unsqueeze(0)
        else:
            tail = out[-1:]
        return (out, w, h, n, tail)


NODE_CLASS_MAPPINGS = {"FXLoadControlFrames": FXLoadControlFrames}
NODE_DISPLAY_NAME_MAPPINGS = {"FXLoadControlFrames": "FX · 读取控制帧（私有）"}




if os.environ.get("FX_TEST_NODES") == "1":
    class FXTestBlock:
        """仅测试用：阻塞 N 秒且不响应中断（模拟引擎卡死），只在 FX_TEST_NODES=1 时注册。"""
        CATEGORY = "fx_private/test"
        RETURN_TYPES = ()
        FUNCTION = "run"
        OUTPUT_NODE = True

        @classmethod
        def INPUT_TYPES(cls):
            return {"required": {"seconds": ("INT", {"default": 300}), "nonce": ("STRING", {"default": ""})}}

        def run(self, seconds, nonce):
            import time as _t
            t0 = _t.time()
            while _t.time() - t0 < seconds:
                _t.sleep(0.5)
            return {"ui": {"text": ["done"]}}

    NODE_CLASS_MAPPINGS["FXTestBlock"] = FXTestBlock
