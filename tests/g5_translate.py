"""G5：中文→英文的技术路径。分别用 Gemma4 12B（GGUF，已随包）与 gemma4_e2b 跑 TextGenerate。"""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json, time, subprocess
from _engine_session import get_engine, wait_prompt
from fxstudio import prompt as P

TEXTS = ["一辆白色冬季迷彩坦克停在积雪的草地上，穿甲弹击中侧面装甲，橙色火球从装甲板上爆开，浓密的黑烟冲天而起，晴朗的蓝天，背景是光秃秃的树",
         "厨房里的锅冒出大量白色蒸汽，缓缓上升并散开",
         "海浪拍打礁石，溅起浅蓝色和白色的水花"]
LOADERS = {
  "12b_gguf": {"class_type": "CLIPLoaderGGUF", "inputs": {"clip_name": "gemma4-12b-with-proj-ltx-2.5-Q4_K_M.gguf", "type": "ltxv"}},
  "e2b": {"class_type": "CLIPLoader", "inputs": {"clip_name": "gemma4_e2b_it_int8_convrot.safetensors", "type": "ltxv", "device": "default"}},
  "e2b_cpu": {"class_type": "CLIPLoader", "inputs": {"clip_name": "gemma4_e2b_it_int8_convrot.safetensors", "type": "ltxv", "device": "cpu"}},
}
which = sys.argv[1:] or list(LOADERS)
e = get_engine()
def vram():
    return subprocess.run(["nvidia-smi","--query-gpu=memory.used","--format=csv,noheader,nounits"],capture_output=True,text=True).stdout.strip()
for name in which:
    for t in TEXTS:
        src = P.apply_glossary(t)
        wf = P.translate_workflow(src, LOADERS[name])
        t0 = time.time()
        try:
            h = wait_prompt(e, e.queue(wf))
            out = h["outputs"]["out"]["text"][0]
            print(json.dumps({"model": name, "sec": round(time.time()-t0,1), "vram_mb": vram(), "glossary": src, "out": P.clean_translation(out)}, ensure_ascii=False))
        except Exception as ex:
            print(json.dumps({"model": name, "error": str(ex)[:600]}, ensure_ascii=False)); break
