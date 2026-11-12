"""看门狗确定性测试：用不响应中断的阻塞节点模拟引擎卡死。应用需以 FX_TEST_NODES=1 FX_STALL_SECONDS=150 启动
（60 秒太短：重启后第一次采样要从磁盘按需加载约 20GB 权重，会被误判为卡死；2026-11-12 实测）。"""
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import e2e_api as E
from pathlib import Path

def eng_pid():
    import psutil
    for p in psutil.process_iter(["pid", "cmdline"]):
        c = " ".join(p.info["cmdline"] or [])
        if "ComfyUI\main.py" in c and "AInVFX-Fluid-Studio\engine" in c and "F:\\" in c:
            return p.info["pid"]

def ready():
    for _ in range(150):
        if E.call("GET", "/api/status")["engine"] == "ready": return True
        time.sleep(2)
out = {}
ready(); p0 = eng_pid()
# 1) 卡死：无进度 → 60 秒后重启并报中文错误
t0 = time.time()
j = E.wait_job(E.call("POST", "/api/test/block?seconds=600")["job"], timeout=400)
out["stall"] = {"state": j["state"], "error": j.get("error"), "sec": round(time.time() - t0)}
ready(); p1 = eng_pid(); out["stall"]["engine_restarted"] = p1 != p0
print(json.dumps(out["stall"], ensure_ascii=False), flush=True)
# 2) 取消无效：取消后 10 秒仍未停下 → 重启
jid = E.call("POST", "/api/test/block?seconds=600")["job"]
time.sleep(8)
t1 = time.time(); E.call("POST", f"/api/jobs/{jid}/cancel")
j = E.wait_job(jid, timeout=120)
out["cancel"] = {"state": j["state"], "sec_after_cancel": round(time.time() - t1)}
ready(); p2 = eng_pid(); out["cancel"]["engine_restarted"] = p2 != p1
print(json.dumps(out["cancel"], ensure_ascii=False), flush=True)
# 3) 重启后正常生成
pid = E.call("POST", "/api/projects", {"name": "watchdog after"})["id"]
p = E.call("GET", f"/api/projects/{pid}")["project"]; p.update(seconds=1, scheme=0, base_mode=0)
p["prompt"]["final"] = "ainvfxfluid, an orange fireball explosion bursts, against a black background, static camera"
E.call("PUT", f"/api/projects/{pid}", p)
E.call("PUT", f"/api/projects/{pid}/strokes/k_first", raw=E.png(E.STROKES["first"], (1024, 576)), ctype="image/png")
t2 = time.time(); j = E.wait_job(E.call("POST", f"/api/projects/{pid}/generate")["job"], timeout=900)
out["after"] = {"state": j["state"], "sec": round(time.time() - t2), "error": j.get("error"), "project": pid}
print(json.dumps(out["after"], ensure_ascii=False), flush=True)
(Path(__file__).resolve().parent.parent / "runtime/logs/watchdog_block_results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
