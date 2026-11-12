import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import io, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
from fastapi.testclient import TestClient
from PIL import Image
from fxstudio.server import app
c = TestClient(app)
def ok(r):
    assert r.status_code < 300, (r.status_code, r.text[:300]); return r
print(ok(c.get("/api/meta")).json()["schemes"])
print(ok(c.get("/api/timeline", params={"seconds": 3, "scheme": 2})).json())
pid = ok(c.post("/api/projects", json={"name": "冒烟 测试"})).json()["id"]; print("pid", pid)
r = ok(c.post(f"/api/projects/{pid}/reference", files={"file": ("tank.png", open(r"tests\input\ainvfx_tank_demo.png","rb").read(), "image/png")})); print(r.json())
for mode in (0, 1, 2):
    p = ok(c.get(f"/api/projects/{pid}")).json()["project"]; p["base_mode"] = mode
    ok(c.put(f"/api/projects/{pid}", json=p))
    im = Image.open(io.BytesIO(ok(c.get(f"/api/projects/{pid}/base/0")).content)); print("mode", mode, im.size, im.getpixel((500, 300)))
s = Image.open(r"tests\input\ainvfx_tank_fx_first.png"); b = io.BytesIO(); s.save(b, "PNG")
print(ok(c.put(f"/api/projects/{pid}/strokes/k_first", content=b.getvalue())).json())
print(ok(c.get(f"/api/projects/{pid}")).json()["strokes"])
print(Image.open(io.BytesIO(ok(c.get(f"/api/projects/{pid}/flat/k_first")).content)).size)
print(ok(c.post("/api/prompt/compose", json={"form": {"scene_en": "a tank in snow", "effect": "explosion"}, "base_mode": 0})).json())
print(ok(c.post("/api/prompt/check", json={"text": "fire", "base_mode": 1})).json())
# 视频参考
r = ok(c.post(f"/api/projects/{pid}/reference", files={"file": ("demo.mp4", open(r"tests\input\ainvfx_demo_video.mp4","rb").read(), "video/mp4")})); print(r.json())
p = ok(c.get(f"/api/projects/{pid}")).json(); print("video_warning", p["video_warning"])
pp = p["project"]; pp["base_mode"] = 1; pp["seconds"] = 4; pp["reference"]["start25"] = 10; ok(c.put(f"/api/projects/{pid}", json=pp))
print(Image.open(io.BytesIO(ok(c.get(f"/api/projects/{pid}/base/96")).content)).size)
print(ok(c.get(f"/api/projects/{pid}/reference/frame/5")).headers["content-type"])
print(ok(c.get("/api/selfcheck")).json()["ok"])
import shutil; from fxstudio import paths; shutil.rmtree(paths.PROJECTS_DIR / pid)
print("SMOKE_OK")
