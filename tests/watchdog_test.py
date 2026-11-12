"""看门狗与取消重启的实测。需要应用以 FX_TEST_SKIP_FULL_FREE=1 FX_STALL_SECONDS=90 启动（故意复现卡死）。"""
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import e2e_api as E
from pathlib import Path

def setup(name):
    pid = E.call("POST", "/api/projects", {"name": name})["id"]
    E.upload(pid, E.INP / "ainvfx_tank_demo.png")
    p = E.call("GET", f"/api/projects/{pid}")["project"]
    p.update(seconds=2, scheme=1, base_mode=1, seed=42)
    p["prompt"].update(scene_en="a white tank on a snowy field", effect="explosion")
    p["prompt"]["final"] = E.call("POST", "/api/prompt/compose", {"form": p["prompt"], "base_mode": 1})["final"]
    E.call("PUT", f"/api/projects/{pid}", p)
    E.call("PUT", f"/api/projects/{pid}/strokes/k_first", raw=E.png(E.STROKES["first"], (1024, 576)), ctype="image/png")
    return pid

def translate():
    j = E.wait_job(E.call("POST", "/api/prompt/translate", {"text": "雪地上的坦克"})["job"])
    assert j["state"] == "done", j

out = {}
pid = setup("看门狗测试")
# 1) 卡死 → 看门狗
translate()
t0 = time.time()
j = E.wait_job(E.call("POST", f"/api/projects/{pid}/generate")["job"], timeout=900)
out["stall"] = {"state": j["state"], "error": j.get("error"), "sec": round(time.time() - t0)}
print(json.dumps(out["stall"], ensure_ascii=False), flush=True)
# 等引擎重启就绪
for _ in range(120):
    if E.call("GET", "/api/status")["engine"] == "ready": break
    time.sleep(2)
# 2) 卡死 → 用户取消 → 10 秒内重启
translate()
jid = E.call("POST", f"/api/projects/{pid}/generate")["job"]
while E.call("GET", f"/api/jobs/{jid}")["stage"] != "编码提示词":
    time.sleep(1)
time.sleep(20)
t1 = time.time()
E.call("POST", f"/api/jobs/{jid}/cancel")
j = E.wait_job(jid, timeout=300)
out["cancel"] = {"state": j["state"], "sec_after_cancel": round(time.time() - t1)}
print(json.dumps(out["cancel"], ensure_ascii=False), flush=True)
for _ in range(120):
    if E.call("GET", "/api/status")["engine"] == "ready": break
    time.sleep(2)
# 3) 重启后正常生成（不先翻译）
t2 = time.time()
j = E.wait_job(E.call("POST", f"/api/projects/{pid}/generate")["job"], timeout=900)
out["after"] = {"state": j["state"], "sec": round(time.time() - t2), "error": j.get("error")}
print(json.dumps(out["after"], ensure_ascii=False), flush=True)
(Path(__file__).resolve().parent.parent / "runtime/logs/watchdog_results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print("PROJECT", pid)
