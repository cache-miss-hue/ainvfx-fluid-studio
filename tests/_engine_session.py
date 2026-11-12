"""测试辅助：启动引擎（或连接已在运行的同一引擎），供 P0 脚本复用。"""
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from fxstudio import paths
from fxstudio.engine import Engine

STATE = paths.RUNTIME_DIR / "test_engine.json"

def get_engine(start=True):
    paths.ensure_dirs()
    if STATE.exists():
        e = Engine(port=json.loads(STATE.read_text())["port"])
        if e.alive():
            return e
    if not start:
        raise RuntimeError("engine not running")
    e = Engine(extra_args=[a for a in os.environ.get("FX_ENGINE_ARGS", "").split() if a])
    e.start()
    STATE.write_text(json.dumps({"port": e.port, "pid": e.proc.pid}))
    return e

def wait_prompt(e, pid, timeout=3600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = e.history(pid)
        if h and h.get("status", {}).get("completed") is not None or (h and h.get("outputs")):
            st = h.get("status", {})
            if st.get("status_str") == "error":
                raise RuntimeError(json.dumps(st.get("messages"), ensure_ascii=False)[:3000])
            return h
        time.sleep(2)
    raise TimeoutError
