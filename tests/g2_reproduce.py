"""G2：在精简引擎上用与 fx_00011_.mp4 完全相同的输入复现。"""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json, time, shutil
from pathlib import Path
from PIL import Image
from _engine_session import get_engine, wait_prompt
from fxstudio import imaging, paths, workflow, control, timeline

INP = Path(r"tests\input")
API = json.load(open(sys.argv[1], encoding="utf-8"))   # fx_00011 的嵌入 prompt
prompt = API["9807"]["inputs"]["value"]
tag = sys.argv[2] if len(sys.argv) > 2 else "g2"
secs, w, h = 5, 1024, 576
base = imaging.make_base(Image.open(INP / "ainvfx_tank_demo.png"), 1, w, h)
n = timeline.total_frames(secs)
kfs = [{"index": 0, "base": base, "strokes": INP / "ainvfx_tank_fx_first.png"},
       {"index": n - 1, "base": base, "strokes": INP / "ainvfx_tank_fx_last.png"}]
job = paths.JOBS_DIR / tag
control.write_control(job, w, h, n, kfs)
e = get_engine()
wf = workflow.build(job, prompt, 42, workflow.resolve_models(e), prefix=f"p0/{tag}")
(job / "api_prompt.json").write_text(json.dumps(wf, ensure_ascii=False, indent=1), encoding="utf-8")
t0 = time.time()
hist = wait_prompt(e, e.queue(wf))
dt = time.time() - t0
out = hist["outputs"]["save"]["images"][0]
src = paths.RUNTIME_DIR / "engine" / "output" / out["subfolder"] / out["filename"]
print(json.dumps({"seconds": round(dt, 1), "file": str(src)}, ensure_ascii=False))
