"""G4：关键帧落在 8k+1 网格外的效果。黑底 3 秒，中间关键帧放在不同帧号，对比时间定位与闪烁。"""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json, time
from pathlib import Path
import numpy as np
from PIL import Image
from _engine_session import get_engine, wait_prompt
from fxstudio import paths, workflow, control, video

INP = Path(r"tests\input")
PROMPT = "ainvfxfluid, an orange fireball explosion bursts and thick black smoke billows upward against a black background, static camera"
W, H, N = 1024, 576, 73
black = Image.new("RGB", (W, H))
mid_alpha = np.array(Image.open(INP / "ainvfx_tank_fx_049.png").convert("RGBA").resize((W, H)))[..., 3] > 127
e = get_engine()
models = workflow.resolve_models(e)
res = []
for mid in [int(x) for x in sys.argv[1:]] or [33, 36, 30, 40]:
    tag = f"g4_mid{mid}"
    job = paths.JOBS_DIR / tag
    control.write_control(job, W, H, N, [
        {"index": 0, "base": black, "strokes": INP / "ainvfx_tank_fx_first.png"},
        {"index": mid, "base": black, "strokes": INP / "ainvfx_tank_fx_049.png"},
        {"index": N - 1, "base": black, "strokes": INP / "ainvfx_tank_fx_last.png"}])
    t0 = time.time()
    h = wait_prompt(e, e.queue(workflow.build(job, PROMPT, 42, models, prefix=f"p0/{tag}")))
    o = h["outputs"]["save"]["images"][0]
    f = paths.RUNTIME_DIR / "engine" / "output" / o["subfolder"] / o["filename"]
    fr = video.read_frames_rgb(f).astype(np.float32)
    lum = fr.mean(axis=3)
    iou = []
    for t in range(len(fr)):
        m = lum[t] > 40
        iou.append(float((m & mid_alpha).sum() / max(1, (m | mid_alpha).sum())))
    d = np.abs(np.diff(lum, axis=0)).mean(axis=(1, 2))
    lo, hi = max(1, mid - 4), min(len(d) - 1, mid + 4)
    spike = float(d[lo:hi].max() / np.median(d))
    best = int(np.argmax(iou[8:N - 8]) + 8)
    r = {"mid": mid, "grid": (mid % 8 == 1), "sec": round(time.time() - t0), "frames": len(fr),
         "iou_at_mid": round(iou[mid], 3), "best_iou_frame": best, "best_iou": round(iou[best], 3),
         "flicker_spike_near_mid": round(spike, 2), "file": str(f)}
    print(json.dumps(r, ensure_ascii=False), flush=True)
    res.append(r)
(paths.LOG_DIR / "g4_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
