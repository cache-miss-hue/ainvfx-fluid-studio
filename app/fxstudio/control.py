"""控制视频描述的写出：job_dir/control.json + 每个关键帧的底图 PNG 与笔触 PNG。
引擎内 FXLoadControlFrames 按此组装（未列出的帧 = 黑帧 = 此刻无特效）。"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from PIL import Image


def write_control(job_dir: Path, width: int, height: int, length: int, keyframes: list[dict],
                  tail_guide: Image.Image | None = None) -> Path:
    """keyframes: [{"index": int, "base": PIL.Image|None, "strokes": Path|PIL.Image|None}]
    tail_guide: 尾帧目标图（原图，不做底图处理），给 LTXVAddGuide 钉住最后一帧。"""
    job_dir.mkdir(parents=True, exist_ok=True)
    spec = {"width": width, "height": height, "length": length, "keyframes": []}
    if tail_guide is not None:
        assert tail_guide.size == (width, height), (tail_guide.size, width, height)
        tail_guide.convert("RGB").save(job_dir / "tail_guide.png")
        spec["tail_guide"] = "tail_guide.png"
    for kf in sorted(keyframes, key=lambda k: k["index"]):
        i = int(kf["index"])
        ent = {"index": i}
        if kf.get("base") is not None:
            b = kf["base"]
            assert b.size == (width, height), (b.size, width, height)
            ent["base"] = f"base_{i:03d}.png"
            b.convert("RGB").save(job_dir / ent["base"])
        s = kf.get("strokes")
        if s is not None:
            ent["strokes"] = f"strokes_{i:03d}.png"
            if isinstance(s, (str, Path)):
                shutil.copyfile(s, job_dir / ent["strokes"])
            else:
                s.save(job_dir / ent["strokes"])
        spec["keyframes"].append(ent)
    (job_dir / "control.json").write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
    return job_dir
