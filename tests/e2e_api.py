"""端到端：通过应用服务的 HTTP 接口完成 建项目 → 参考 → 笔触 → 提示词 → 生成 → (叠加导出)。
用法：e2e_api.py <app端口> <用例名…>   用例见 CASES。结果写 runtime/logs/e2e_<用例>.json
"""
import sys, os, io, json, time, urllib.request
from pathlib import Path
from PIL import Image

PORT = int(sys.argv[1])
BASE = f"http://127.0.0.1:{PORT}"
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
INP = Path(r"tests\input")
ROOT = Path(__file__).resolve().parent.parent

def call(method, path, body=None, raw=None, ctype="application/json"):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    import urllib.parse
    req = urllib.request.Request(BASE + urllib.parse.quote(path, safe="/?=&"), data=data, method=method, headers={"Content-Type": ctype} if data else {})
    try:
        with OP.open(req, timeout=600) as r:
            b = r.read()
            return json.loads(b) if b and r.headers.get("content-type", "").startswith("application/json") else b
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path} -> {e.code} {e.read().decode('utf-8','replace')[:300]}")

def upload(pid, f):
    bnd = "----fxb"
    body = (f"--{bnd}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{f.name}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode() + f.read_bytes() + f"\r\n--{bnd}--\r\n".encode()
    return call("POST", f"/api/projects/{pid}/reference", raw=body, ctype=f"multipart/form-data; boundary={bnd}")

def png(path, size):
    im = Image.open(path).convert("RGBA").resize(size, Image.NEAREST); b = io.BytesIO(); im.save(b, "PNG"); return b.getvalue()

def wait_job(jid, timeout=1800):
    t0 = time.time(); last = None
    while time.time() - t0 < timeout:
        j = call("GET", f"/api/jobs/{jid}")
        s = (j["state"], j["stage"], j.get("step"))
        if s != last:
            print("   ", s, round(j["progress"], 2), flush=True); last = s
        if j["state"] in ("done", "error", "cancelled"):
            return j
        time.sleep(1)
    raise TimeoutError

STROKES = {"first": INP / "ainvfx_tank_fx_first.png", "mid1": INP / "ainvfx_tank_fx_025.png", "mid2": INP / "ainvfx_tank_fx_049.png",
           "mid3": INP / "ainvfx_tank_fx_073.png", "mid4": INP / "ainvfx_tank_fx_097.png", "last": INP / "ainvfx_tank_fx_last.png"}
CASES = {
    # 名称: (底图模式, 参考, 时长, 方案, 中文场景?)
    "m0_img_s2": (0, "img", 3, 2, False),
    "m1_vid_s1": (1, "vid", 4, 1, False),
    "m2_img_s0": (2, "img", 2, 0, True),
    "m1_img_s1_5s": (1, "img", 5, 1, False),
}

def run_case(name):
    mode, ref, secs, scheme, zh = CASES[name]
    print(f"== {name}", flush=True)
    pid = call("POST", "/api/projects", {"name": f"e2e {name}"})["id"]
    upload(pid, INP / ("ainvfx_tank_demo.png" if ref == "img" else "ainvfx_demo_video.mp4"))
    p = call("GET", f"/api/projects/{pid}")["project"]
    tl = call("GET", f"/api/timeline?seconds={secs}&scheme={scheme}")
    idxs = tl["scheme_indices"]
    kfs = []
    for i in idxs:
        if i == 0: kfs.append({"id": "k_first", "index": 0})
        elif i == tl["last"]: kfs.append({"id": "k_tail", "index": -1, "tail": True})
        else: kfs.append({"id": f"k_m{i}", "index": i})
    p.update(seconds=secs, scheme=scheme, keyframes=kfs, base_mode=mode, seed=42)
    if zh:
        p["prompt"].update(scene="雪地上一辆白色坦克，晴朗的蓝天", effect="explosion")
        tr = call("POST", "/api/prompt/translate", {"text": p["prompt"]["scene"]})
        j = wait_job(tr["job"])
        assert j["state"] == "done", j
        p["prompt"]["scene_en"] = j["result"]["english"]
        print("    translate:", j["result"], flush=True)
    else:
        p["prompt"].update(scene_en="a white winter-camouflaged tank on a snowy grass field, clear blue sky", effect="explosion")
    comp = call("POST", "/api/prompt/compose", {"form": p["prompt"], "base_mode": mode})
    p["prompt"]["final"] = comp["final"]
    call("PUT", f"/api/projects/{pid}", p)
    order = ["first", "mid1", "mid2", "mid3", "mid4"]
    for n, k in enumerate(kfs):
        src = STROKES["last"] if k.get("tail") else STROKES[order[min(n, 4)]]
        call("PUT", f"/api/projects/{pid}/strokes/{k['id']}", raw=png(src, (p["width"], p["height"])), ctype="image/png")
    t0 = time.time()
    j = wait_job(call("POST", f"/api/projects/{pid}/generate")["job"])
    res = {"case": name, "state": j["state"], "error": j.get("error"), "notes": j.get("notes"), "sec": round(time.time() - t0),
           "prompt": comp["final"], "file": (j.get("result") or {}).get("file"), "project": pid}
    if j["state"] == "done" and mode == 0:
        res["overlay"] = call("POST", "/api/results/overlay", {"file": res["file"], "blend": "screen"})["file"]
    if j["state"] == "done":
        res["results_listed"] = len(call("GET", f"/api/projects/{pid}/results"))
    print(json.dumps(res, ensure_ascii=False), flush=True)
    (ROOT / "runtime" / "logs" / f"e2e_{name}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res

if __name__ == "__main__":
    print(json.dumps(call("GET", "/api/status"), ensure_ascii=False)[:300])
    for c in sys.argv[2:]:
        run_case(c)
