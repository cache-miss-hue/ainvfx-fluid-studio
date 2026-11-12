"""后端单元测试（不占 GPU、不启动引擎、不联网、不碰真实项目和 .env）。

覆盖：参考画面替换失败不丢旧参考；预览帧/底图并发只生成一次；时间轴预览帧与生成用帧一致；
关键帧换算与前端同一份期望结果；翻译密钥绑定接口主机；跨站请求拦截；删除进回收站；启动清理；
取消（提交前取消、重发中断）；引擎意外退出自愈与次数上限；错误提示。

用法：engine\\python\\python.exe -s tests\\unit_backend_test.py
"""
import io, json, os, shutil, subprocess, sys, tempfile, threading, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
TMP = Path(tempfile.mkdtemp(prefix="fx_unit_"))
os.environ["FX_ENV_FILE"] = str(TMP / ".env")          # 必须在 import llm/server 之前

from fxstudio import paths
# 所有数据目录指到临时目录
paths.PROJECTS_DIR = TMP / "projects"
paths.OUTPUT_DIR = TMP / "output"
paths.RUNTIME_DIR = TMP / "runtime"
paths.LOG_DIR = paths.RUNTIME_DIR / "logs"
paths.JOBS_DIR = paths.RUNTIME_DIR / "jobs"
paths.CACHE_DIR = paths.RUNTIME_DIR / "cache"
paths.ensure_dirs()

import numpy as np
from PIL import Image
from fxstudio import projects, video, llm, jobs, prompt as promptmod

res = []


def case(name, ok, detail=""):
    res.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name, "|", str(detail)[:300])


def make_video(path: Path, fps=24, secs=9, size="854x480"):
    subprocess.run([video.ffmpeg_exe(), "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc2=size={size}:rate={fps}:duration={secs}", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


VID = make_video(TMP / "t24.mp4")

# ---------------- 参考画面：替换失败不丢旧参考 ----------------
pid = projects.create("单测 项目")
info = projects.set_reference(pid, "片段.mp4", VID.read_bytes())
case("上传视频成功", info["type"] == "video" and info["frames25"] > 100, info)
old_file = projects.reference_file(pid)
for name, data in (("坏视频.mp4", b"not a video at all" * 100), ("坏图.png", b"\x89PNG broken"), ("空.mp4", b"")):
    try:
        projects.set_reference(pid, name, data)
        case(f"坏文件被拒绝：{name}", False)
    except ValueError as ex:
        p = projects.load(pid)
        case(f"坏文件被拒绝且旧参考保留：{name}", p["reference"]["original_name"] == "片段.mp4" and old_file.exists()
             and not list(projects.project_dir(pid).glob(".upload_tmp*")), ex)

# ---------------- 时间轴预览帧：并发只抽一次，且与生成用帧一致 ----------------
calls = {"clip": 0, "refs": 0}
_orig_clip, _orig_refs = video.clip_previews, video.keyframe_refs


def counting_clip(*a, **k):
    calls["clip"] += 1
    time.sleep(0.3)
    return _orig_clip(*a, **k)


def counting_refs(*a, **k):
    calls["refs"] += 1
    time.sleep(0.3)
    return _orig_refs(*a, **k)


video.clip_previews, video.keyframe_refs = counting_clip, counting_refs
errs = []


def grab(i):
    try:
        projects.clip_frame(pid, 130, i)
    except Exception as ex:
        errs.append(ex)


ts = [threading.Thread(target=grab, args=(i,)) for i in (0, 5, 10, 40, 40, 72)]
[t.start() for t in ts]; [t.join() for t in ts]
case("预览帧并发请求只抽一次", calls["clip"] == 1 and not errs, (calls, errs))
try:
    projects.clip_frame(pid, 130, 120)
    case("超出视频长度的预览帧报 404", False)
except FileNotFoundError as ex:
    case("超出视频长度的预览帧报找不到（视频只剩约 3.8 秒）", True, ex)

# 取帧一致性：预览 JPEG 与生成用的参考帧（同样裁切缩小）应是同一帧，而不是相邻帧
p = projects.load(pid)
W, H = int(p["width"]), int(p["height"])
refs = _orig_refs(VID, 130, [0, 1, 39, 40, 41])


def small(arr):
    im = Image.fromarray(np.clip(arr * 255.0 + 0.5, 0, 255).astype(np.uint8))
    return np.asarray(im.resize((640, round(640 * H / W)), Image.Resampling.BILINEAR)).astype(np.float32)


for i, nb in ((0, 1), (40, 39), (40, 41)):
    jpg = np.asarray(Image.open(projects.clip_frame(pid, 130, i)).convert("RGB")).astype(np.float32)
    d_same, d_nb = np.abs(jpg - small(refs[i])).mean(), np.abs(jpg - small(refs[nb])).mean()
    case(f"预览帧 {i} 与生成用帧一致（差 {d_same:.2f}，相邻帧 {nb} 差 {d_nb:.2f}）", d_same < 4 and d_same * 2 < d_nb)

# 底图并发只算一次
calls["refs"] = 0
p["reference"]["start25"] = 20
projects.save(pid, p)
outs, errs = [], []


def base(i):
    try:
        outs.append(projects.base_images(pid, None, [0, 25])[25].size)
    except Exception as ex:
        errs.append(ex)


ts = [threading.Thread(target=base, args=(i,)) for i in range(4)]
[t.start() for t in ts]; [t.join() for t in ts]
case("底图并发只解码一次", calls["refs"] == 1 and len(outs) == 4 and not errs, (calls, errs))
video.clip_previews, video.keyframe_refs = _orig_clip, _orig_refs

thumb = projects.video_thumb(pid, 100, 160)
case("整段视频缩略图（选起始帧用）", thumb.exists() and Image.open(thumb).width == 160, thumb)

# 换掉参考：旧缓存一起删
vk = projects._video_cache_key(projects.reference_file(pid))
projects.set_reference(pid, "新片段.mp4", make_video(TMP / "t25.mp4", fps=25, secs=3).read_bytes())
left = [d for sub in ("clip", "thumb", "base") for d in (paths.CACHE_DIR / sub).glob(f"{vk}*")]
case("换参考后旧视频的缓存被清掉", not left, left)

# ---------------- 关键帧换算：与前端同一份期望结果 ----------------
fx = json.loads((ROOT / "tests" / "fixtures" / "keyframes_cases.json").read_text(encoding="utf-8"))
bad = [c["name"] for c in fx if projects.resolved_keyframes(c["project"]) != c["expected"]]
case(f"关键帧换算 {len(fx)} 例与期望一致", not bad, bad)

# ---------------- 翻译密钥绑定接口主机 ----------------
KEY = "sk-unit-0123456789"
llm.ENV_FILE.write_text(f"FX_TRANSLATE_BASE_URL=https://api.deepseek.com\nFX_TRANSLATE_API_KEY={KEY}\nFX_TRANSLATE_MODEL=m\n",
                        encoding="utf-8")
m = llm.mask_key(KEY)
o = llm.resolve_overrides({"base_url": "https://evil.example.com", "api_key": m})
case("换了主机：打码密钥不还原成真实密钥", o["api_key"] == "", o)
o = llm.resolve_overrides({"base_url": "https://evil.example.com"})
case("换了主机且没传密钥：也不带已存密钥", o.get("api_key") == "", o)
o = llm.resolve_overrides({"base_url": "https://api.deepseek.com/v1", "api_key": m})
case("同一主机（补 /v1）：沿用已存密钥", o["api_key"] == KEY)
llm.save_config({"base_url": "https://api.deepseek.com:443/v1", "api_key": m})
case("保存同一主机：密钥保留", llm.read_env()["FX_TRANSLATE_API_KEY"] == KEY)
llm.save_config({"base_url": "https://relay.example.net", "api_key": m})
case("保存到别的主机而没重填密钥：旧密钥作废", llm.read_env()["FX_TRANSLATE_API_KEY"] == "")
llm.save_config({"base_url": "https://relay2.example.net", "api_key": "sk-new-123456789"})
case("换主机同时填了新密钥：用新密钥", llm.read_env()["FX_TRANSLATE_API_KEY"] == "sk-new-123456789")

# ---------------- HTTP：跨站拦截、删除、新接口 ----------------
from fastapi.testclient import TestClient
from fxstudio import server
c = TestClient(server.app)
r = c.post("/api/translate/test", content=json.dumps({"config": {"base_url": "https://evil.example.com"}}),
           headers={"Origin": "https://evil.example.com", "Content-Type": "text/plain"})
case("别的网站发来的请求被拒绝（403）", r.status_code == 403, r.text)
r = c.get("/api/status", headers={"Origin": "http://testserver"})
case("本软件页面自己的请求放行", r.status_code == 200 and "busy" in r.json(), r.text[:100])
r = c.get("/api/status", headers={"Origin": "http://localhost:5173"})
case("前端开发服务器（localhost）放行", r.status_code == 200)
server.LOCAL_ONLY = True
r = c.get("/api/status")
case("仅本机模式：非本机 Host 被拒（防 DNS 重绑定）", r.status_code == 403, r.text)
r = c.get("/api/status", headers={"Host": "127.0.0.1:7860"})
case("仅本机模式：127.0.0.1 放行", r.status_code == 200)
server.LOCAL_ONLY = False
r = c.get(f"/api/projects/{pid}/clip/0/10")
case("时间轴预览帧接口", r.status_code == 200 and r.headers["content-type"] == "image/jpeg", r.status_code)
r = c.get(f"/api/projects/{pid}/reference/frame/10", params={"w": 160})
case("缩略图接口", r.status_code == 200, r.status_code)
# 浏览器缓存：每次都要校验（换参考、刷新页面后 URL 可能和以前一样，不能直接用旧图）
r1 = c.get(f"/api/projects/{pid}/clip/0/10")
et = r1.headers.get("etag")
r2 = c.get(f"/api/projects/{pid}/clip/0/10", headers={"If-None-Match": et or ""})
case("预览图要求浏览器每次校验（no-cache + ETag，未变化时 304）",
     r1.headers.get("cache-control") == "no-cache" and et and r2.status_code == 304, (r1.headers.get("cache-control"), et, r2.status_code))
projects.set_reference(pid, "换一个.mp4", make_video(TMP / "t30.mp4", fps=30, secs=3, size="640x360").read_bytes())
r3 = c.get(f"/api/projects/{pid}/clip/0/10", headers={"If-None-Match": et or ""})
case("换参考后同一个预览地址返回新画面（不会 304 成旧图）", r3.status_code == 200 and r3.content != r1.content, r3.status_code)
r = c.post("/api/jobs/nope/cancel")
case("取消不存在的任务返回 404", r.status_code == 404, r.status_code)
r = c.post("/api/engine/free")
case("引擎没启动时释放显存给中文提示", r.status_code == 400 and "引擎" in r.json()["detail"], r.text)

# ---------------- 局域网访问口令 ----------------
from fxstudio import __main__ as entry
t1 = entry.lan_token(); t2 = entry.lan_token()
case("口令首次生成后保存并沿用", t1 == t2 and len(t1) == 8 and (paths.RUNTIME_DIR / "lan_token.txt").read_text().strip() == t1, t1)
server.LAN_TOKEN, server.LAN_URLS = t1, [f"http://192.168.1.5:7860/?k={t1}"]
lc = TestClient(server.app)                                   # 客户端地址是 testclient = 模拟平板
r = lc.get("/")
case("局域网：没口令打开页面 → 口令输入页", r.status_code == 401 and 'name="k"' in r.text, r.status_code)
r = lc.get("/api/status")
case("局域网：没口令调接口 → 401", r.status_code == 401, r.status_code)
r = lc.get("/", params={"k": "wrongpass"})
case("局域网：口令不对有提示", r.status_code == 401 and "口令不对" in r.text)
r = lc.get("/", params={"k": t1.upper(), "x": "1"}, follow_redirects=False)
case("局域网：口令正确（不分大小写）→ 记住并跳转去掉口令", r.status_code == 303 and r.headers["location"] == "/?x=1"
     and "fx_lan=" in r.headers.get("set-cookie", ""), (r.status_code, r.headers.get("location")))
r = lc.get("/api/status")
case("局域网：记住口令后正常使用", r.status_code == 200, r.status_code)
with lc.websocket_connect("/api/ws") as w:
    case("局域网：有口令的实时连接正常", w.receive_json()["type"] == "status")
bad = TestClient(server.app, client=("10.0.0.9", 50000))
try:
    with bad.websocket_connect("/api/ws") as w:
        w.receive_json()
    case("局域网：没口令的实时连接被拒绝", False)
except Exception:
    case("局域网：没口令的实时连接被拒绝", True)
for _ in range(10):
    bad.get("/", params={"k": "nope0000"})
r = bad.get("/", params={"k": t1}, follow_redirects=False)
case("局域网：输错 10 次后暂时锁住（正确口令也不行）", r.status_code == 401 and "太多次" in r.text, r.status_code)
local = TestClient(server.app, client=("127.0.0.1", 50001))
r = local.get("/api/lan")
case("局域网：电脑本机免口令，并能查到带口令的地址", r.status_code == 200 and r.json()["token"] == t1 and r.json()["urls"], r.text[:80])
server.LAN_TOKEN, server.LAN_URLS = None, []
r = TestClient(server.app, client=("10.0.0.9", 50002)).get("/api/lan")
case("非局域网模式不检查口令", r.status_code == 200 and r.json() == {"enabled": False}, r.text)

# 删除结果与项目 → 回收站
od = paths.OUTPUT_DIR / pid
od.mkdir(parents=True, exist_ok=True)
(od / "20260101_000000_seed1.mp4").write_bytes(b"x")
(od / "20260101_000000_seed1.json").write_text("{}")
(od / "20260101_000000_seed1_screen.mp4").write_bytes(b"x")
old = time.time() - 90 * 86400
os.utime(od / "20260101_000000_seed1.mp4", (old, old))
r = c.delete("/api/results", params={"file": f"{pid}/20260101_000000_seed1.mp4"})
case("删除结果：三个文件都进回收站", r.status_code == 200 and not list(od.glob("*")), r.text)
r = c.delete(f"/api/projects/{pid}")
trash = paths.RUNTIME_DIR / "trash"
case("删除项目：项目与成片移进回收站", r.status_code == 200 and not (paths.PROJECTS_DIR / pid).exists()
     and any((d / "project" / "project.json").exists() for d in trash.iterdir()), r.text)

# ---------------- 启动清理 ----------------
stale = paths.CACHE_DIR / "clip" / "stale"; stale.mkdir(parents=True)
fresh = paths.CACHE_DIR / "clip" / "fresh"; fresh.mkdir(parents=True)
oldjob = paths.JOBS_DIR / "oldjob"; oldjob.mkdir(parents=True)
for d in (stale, oldjob):
    os.utime(d, (old, old))
rm = projects.cleanup_runtime()
case("启动清理：旧缓存与旧任务目录删除，新的保留，刚删的结果仍在回收站",
     not stale.exists() and fresh.exists() and not oldjob.exists() and len(list(trash.iterdir())) == 2, rm)

# ---------------- 取消与引擎自愈（假引擎） ----------------
class FakeEngine:
    def __init__(self, start_after=None):
        self.queued, self.interrupts, self.deleted = [], 0, []
        self.t0 = None
        self.start_after = start_after       # None = 永远排队不执行
        self.code = None

    def queue(self, wf):
        self.queued.append(wf); self.t0 = time.time(); return "p1"

    def interrupt(self):
        self.interrupts += 1

    def delete_queued(self, pid):
        self.deleted.append(pid)

    def in_queue(self, pid):
        return self.start_after is not None

    def history(self, pid):
        if self.start_after is not None and self.interrupts >= 2:
            return {"status": {"status_str": "error", "messages": [["execution_interrupted", {}]]}}
        return {}

    def exited(self):
        return self.code


jm = jobs.JobManager()
jm.INTERRUPT_EVERY = 0.2
job = jobs.Job("generate", {"pid": "x"})
job.cancel_requested = True
jm.engine = FakeEngine()
try:
    jm._queue_and_wait(job, {})
    case("提交前已取消：不提交给引擎", False)
except jobs.CancelledError:
    case("提交前已取消：不提交给引擎", not jm.engine.queued)

job = jobs.Job("generate", {"pid": "x"})
jm.engine = FakeEngine(start_after=None)
threading.Timer(0.3, lambda: setattr(job, "cancel_requested", True)).start()
t0 = time.time()
try:
    jm._queue_and_wait(job, {})
except jobs.CancelledError:
    pass
case("排队中取消：移出引擎队列并结束，不重启引擎", jm.engine.deleted == ["p1"] and time.time() - t0 < 3,
     f"{time.time() - t0:.1f}s")

job = jobs.Job("generate", {"pid": "x"})
jm.engine = FakeEngine(start_after=0)
threading.Timer(0.3, lambda: setattr(job, "cancel_requested", True)).start()
try:
    jm._queue_and_wait(job, {})
except jobs.CancelledError:
    pass
case("执行中取消：中断会重发（第一次被引擎清掉也能停下）", jm.engine.interrupts >= 2, jm.engine.interrupts)

restarts = []
jm.restart_engine = lambda reason: restarts.append(reason)
jm.engine = FakeEngine(); jm.engine.code = 3221225477
jm.engine_state = "ready"
for _ in range(5):
    jm._monitor_tick()
case("引擎意外退出：自动重启，10 分钟内最多 3 次后停下报错",
     len(restarts) == 3 and jm.engine_state == "error" and "停止自动重启" in jm.engine_error, (restarts, jm.engine_error))

import urllib.error
case("连不上引擎的错误是中文", "引擎" in jobs.friendly_error(urllib.error.URLError("refused")))

# 首帧/尾帧图片：各自作为首/尾关键帧的底图（比例不同的图整幅缩放到输出尺寸，不裁切）
def _solid(c, size):
    b = io.BytesIO(); Image.new("RGB", size, c).save(b, "PNG"); return b.getvalue()


pid_ff = projects.create("首尾帧")
r1 = projects.set_frame_ref(pid_ff, "first", "a.png", _solid((255, 0, 0), (1600, 1200)))
projects.set_frame_ref(pid_ff, "tail", "b.png", _solid((0, 0, 255), (1920, 1080)))
case("首帧图 4:3 给出 768×576 建议尺寸", r1["fit_size"] == [768, 576], r1["fit_size"])
p_ff = projects.load(pid_ff)
p_ff.update(width=768, height=576, seconds=2, base_mode=1,
            keyframes=[{"id": "k_first", "index": 0}, {"id": "k_m", "index": 24}, {"id": "k_tail", "index": -1, "tail": True}])
projects.save(pid_ff, p_ff)
bs = projects.base_images(pid_ff, None, [0, 25, 48])
case("首帧用首帧图、尾帧用尾帧图、中间帧退回首帧图",
     [bs[i].getpixel((5, 5)) for i in (0, 25, 48)] == [(255, 0, 0), (255, 0, 0), (0, 0, 255)] and bs[0].size == (768, 576))
projects.clear_frame_ref(pid_ff, "first")
case("移除首帧图后首帧退回尾帧图", projects.base_images(pid_ff, None, [0])[0].getpixel((5, 5)) == (0, 0, 255))
try:
    projects.set_frame_ref(pid_ff, "first", "v.mp4", b"x"); case("首帧不收视频", False)
except ValueError:
    case("首帧不收视频", True)

shutil.rmtree(TMP, ignore_errors=True)
fails = [n for n, ok in res if not ok]
print(f"\n共 {len(res)} 项，失败 {len(fails)}")
sys.exit(1 if fails else 0)
