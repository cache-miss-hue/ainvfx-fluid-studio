"""应用服务（FastAPI）：项目、底图、参考画面、提示词、任务、结果。前端静态文件同源提供。"""
from __future__ import annotations

import asyncio
import hmac
import io
import json
import re
import time
from html import escape
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from urllib.parse import urlencode, urlsplit
from PIL import Image

from . import __version__, imaging, llm, paths, projects, prompt as promptmod, selfcheck, timeline, video
from .jobs import JobManager

app = FastAPI(title="AInVFX Fluid Studio", version=__version__)
llm.ensure_env_file()
jm = JobManager()


# ---------------- 访问保护 ----------------
# 只允许本软件自己的页面调用接口：别的网站的页面（跨站请求）一律拒绝，防止被恶意网页借浏览器调用
# （例如让软件把已保存的翻译密钥发到别处）。LOCAL_ONLY=True（默认启动方式）时还要求 Host 是本机地址，
# 防 DNS 重绑定；--lan 模式由 __main__ 设为 False，允许用局域网 IP 访问。
LOCAL_ONLY = False
_LOCAL_NAMES = {"127.0.0.1", "localhost", "::1", "[::1]"}


def _hostname(netloc: str) -> str:
    try:
        return (urlsplit("//" + netloc).hostname or "").lower()
    except ValueError:
        return ""


def _request_allowed(headers) -> str | None:
    host = headers.get("host", "")
    if LOCAL_ONLY and _hostname(host) not in _LOCAL_NAMES:
        return "只允许本机访问（需要平板访问请用 start_lan.bat 启动）"
    origin = headers.get("origin")
    if origin and origin != "null":
        try:
            o = urlsplit(origin)
        except ValueError:
            return "来源不合法"
        if o.netloc.lower() != host.lower() and (o.hostname or "").lower() not in _LOCAL_NAMES:
            return "拒绝来自其他网站的请求"
    elif origin == "null":
        return "拒绝来自其他网站的请求"
    return None


# ---------------- 局域网访问口令（start_lan.bat） ----------------
# 局域网模式下，除电脑本机（127.0.0.1）外，必须带口令才能打开：第一次用 ?k=口令 打开（或在提示页里输入），
# 之后浏览器记住一年（Cookie）。同一设备 5 分钟内输错 10 次暂时锁住。口令由 __main__ 生成并保存在
# runtime/lan_token.txt（删掉它再启动就换新口令）。LAN_TOKEN 为 None = 不是局域网模式，不检查。
LAN_TOKEN: str | None = None
LAN_URLS: list[str] = []
LAN_EXEMPT_LOOPBACK = True          # 电脑本机免口令（仅测试时关掉，用来在本机模拟平板）
_LAN_COOKIE = "fx_lan"
_LAN_FAIL_LIMIT, _LAN_FAIL_WINDOW = 10, 300
_lan_fails: dict[str, list[float]] = {}


def _same(a: str, b: str) -> bool:
    return hmac.compare_digest(str(a).encode("utf-8"), str(b).encode("utf-8"))


def _lan_state(client_host: str, cookies, k: str | None) -> str:
    """ok = 放行；grant = 口令正确（种 Cookie 后跳转）；need = 没带口令；wrong = 口令不对；locked = 输错太多次。"""
    if not LAN_TOKEN:
        return "ok"
    now = time.time()
    fails = [t for t in _lan_fails.get(client_host, []) if now - t < _LAN_FAIL_WINDOW]
    locked = len(fails) >= _LAN_FAIL_LIMIT
    if k is not None and not locked and _same(k.strip().lower(), LAN_TOKEN):
        _lan_fails.pop(client_host, None)
        return "grant"            # 带了正确口令：（重新）记住，并跳转去掉地址栏里的口令
    if LAN_EXEMPT_LOOPBACK and client_host in ("127.0.0.1", "::1"):
        return "ok"
    if _same(cookies.get(_LAN_COOKIE, ""), LAN_TOKEN):
        return "ok"
    if k is None:
        return "need"
    if locked:
        _lan_fails[client_host] = fails
        return "locked"
    fails.append(now)
    _lan_fails[client_host] = fails
    return "wrong"


_LAN_PAGE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>输入访问口令</title>
<style>body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#15171b;color:#dfe3ea;
font:16px/1.6 "Microsoft YaHei UI","PingFang SC",system-ui,sans-serif}}.b{{background:#1c1f25;border:1px solid #333844;border-radius:10px;
padding:24px 26px;width:min(380px,90vw)}}h1{{font-size:19px;margin:0 0 6px;color:#ff7a1a}}p{{margin:6px 0;color:#8d94a3;font-size:14px}}
.e{{color:#ff8080}}input{{width:100%;box-sizing:border-box;font-size:22px;letter-spacing:3px;padding:8px 10px;margin:12px 0;background:#15171b;
color:#fff;border:1px solid #4c9aff;border-radius:6px}}button{{width:100%;font-size:17px;padding:9px;border:0;border-radius:6px;
background:#ff7a1a;color:#1a1007;font-weight:700}}</style></head><body><form class="b" method="get" action="/">
<h1>AInVFX Fluid Studio</h1><p>局域网访问需要口令。口令显示在电脑上的软件黑色窗口里，也可以在电脑界面顶栏点“平板访问”查看。</p>
{msg}<input name="k" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="8 位口令" autofocus>
<button type="submit">进入</button></form></body></html>"""


def _lan_denied(request_path: str, state: str):
    msg = {"wrong": '<p class="e">口令不对，请再看一下电脑上显示的口令。</p>',
           "locked": '<p class="e">输错太多次，请 5 分钟后再试。</p>'}.get(state, "")
    if request_path.startswith(("/api/", "/media/")):
        return JSONResponse({"detail": "局域网访问需要口令：请用电脑上显示的带口令地址打开"}, status_code=401)
    return HTMLResponse(_LAN_PAGE.format(msg=msg), status_code=401, headers={"Cache-Control": "no-store"})


@app.middleware("http")
async def _guard(request: Request, call_next):
    why = _request_allowed(request.headers)
    if why:
        return JSONResponse({"detail": why}, status_code=403)
    state = _lan_state(request.client.host if request.client else "", request.cookies, request.query_params.get("k"))
    if state == "grant":
        rest = [(a, b) for a, b in request.query_params.multi_items() if a != "k"]
        target = request.url.path + ("?" + urlencode(rest) if rest else "")
        resp = RedirectResponse(target, status_code=303)       # 去掉地址栏里的口令
        resp.set_cookie(_LAN_COOKIE, LAN_TOKEN, max_age=365 * 86400, httponly=True, samesite="lax")
        return resp
    if state != "ok":
        return _lan_denied(request.url.path, state)
    return await call_next(request)


@app.get("/api/lan")
def lan_info(request: Request):
    """电脑界面顶栏“平板访问”：局域网模式下给出带口令的地址（只告诉电脑本机或已经有口令的设备）。"""
    if not LAN_TOKEN:
        return {"enabled": False}
    return {"enabled": True, "token": LAN_TOKEN, "urls": LAN_URLS}


@app.exception_handler(ValueError)
async def _value_error(_req, ex):
    return JSONResponse({"detail": str(ex)}, status_code=400)


@app.exception_handler(FileNotFoundError)
async def _nf_error(_req, ex):
    return JSONResponse({"detail": str(ex)}, status_code=404)


# ---------------- 状态 ----------------
@app.get("/api/status")
def status():
    return {"version": __version__, "engine": jm.engine_state, "engine_error": jm.engine_error,
            "models_ready": jm.models is not None, "first_load_pending": not jm.models_loaded_once,
            "busy": jm._current is not None,
            "queue": [j.snapshot() for j in jm.jobs.values() if j.state in ("queued", "running")]}


@app.post("/api/engine/restart")
def engine_restart():
    jm.manual_restart()
    return {"ok": True}


@app.post("/api/engine/free")
def engine_free():
    jm.free_vram()
    return {"ok": True}


@app.get("/api/selfcheck")
def get_selfcheck(full: bool = False):
    pid = jm.engine.proc.pid if jm.engine and jm.engine.proc else None
    return selfcheck.run(full_hash=full, engine_pid=pid)


@app.get("/api/meta")
def meta():
    return {"effects": promptmod.EFFECTS, "schemes": timeline.SCHEMES, "fps": timeline.FPS,
            "size_presets": [{"label": "横屏 1024×576（默认）", "w": 1024, "h": 576},
                             {"label": "竖屏 576×1024", "w": 576, "h": 1024},
                             {"label": "横屏 768×448（省显存）", "w": 768, "h": 448},
                             {"label": "竖屏 448×768（省显存）", "w": 448, "h": 768},
                             {"label": "方形 768×768", "w": 768, "h": 768},
                             {"label": "横屏 1280×704", "w": 1280, "h": 704}],
            "default_palette": projects.DEFAULT_PALETTE}


@app.get("/api/timeline")
def get_timeline(seconds: int, scheme: int | None = None):
    return {"total": timeline.total_frames(seconds), "last": timeline.last_index(seconds),
            "grid": timeline.grid_positions(seconds),
            "scheme_indices": timeline.scheme_indices(seconds, scheme) if scheme is not None else None}


# ---------------- 项目 ----------------
@app.get("/api/projects")
def list_projects():
    return projects.list_projects()


@app.post("/api/projects")
async def create_project(req: Request):
    body = await req.json()
    pid = projects.create(body.get("name", ""))
    return {"id": pid, "project": projects.load(pid)}


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    p = projects.load(pid)
    return {"id": pid, "project": p, "resolved_keyframes": projects.resolved_keyframes(p),
            "strokes": [k["id"] for k in p["keyframes"] if projects.strokes_path(pid, k["id"]).exists()],
            "video_warning": projects.check_video_length(p)}


@app.put("/api/projects/{pid}")
async def put_project(pid: str, req: Request):
    data = await req.json()
    old = projects.load(pid)
    # 参考文件信息以服务器为准（由上传接口写入），前端只能改视频起始帧
    ref = old.get("reference")
    if ref:
        ref = dict(ref)
        if isinstance(data.get("reference"), dict):
            ref["start25"] = max(0, int(data["reference"].get("start25", ref.get("start25", 0))))
    data["reference"] = ref
    projects.save(pid, data)
    return get_project(pid)


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    projects.load(pid)
    if any(j.payload.get("pid") == pid and j.state in ("queued", "running") for j in jm.jobs.values()):
        raise ValueError("这个项目正在生成，不能删除；请先取消生成")
    box = projects.delete_project(pid)
    return {"ok": True, "trash": _rel(box)}


@app.post("/api/projects/{pid}/duplicate")
async def duplicate_project(pid: str, req: Request):
    import shutil, uuid
    body = await req.json()
    src = projects.project_dir(pid)
    newpid = projects.create(body.get("name") or projects.load(pid)["name"] + " 副本")
    dst = paths.PROJECTS_DIR / newpid
    shutil.rmtree(dst)
    shutil.copytree(src, dst)
    p = projects.load(newpid)
    p["name"] = body.get("name") or p["name"] + " 副本"
    projects.save(newpid, p)
    return {"id": newpid}


# ---------------- 笔触层 ----------------
@app.get("/api/projects/{pid}/strokes/{kid}")
def get_strokes(pid: str, kid: str):
    f = projects.strokes_path(pid, kid)
    if not f.exists():
        return Response(status_code=204)
    return FileResponse(f, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.put("/api/projects/{pid}/strokes/{kid}")
async def put_strokes(pid: str, kid: str, req: Request):
    data = await req.body()
    p = projects.load(pid)
    im = Image.open(io.BytesIO(data))
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    if im.size != (int(p["width"]), int(p["height"])):
        raise ValueError(f"笔触层尺寸 {im.size} 与输出尺寸 {p['width']}x{p['height']} 不一致")
    f = projects.strokes_path(pid, kid)
    if im.getbbox() is None:          # 全透明 = 没画
        f.unlink(missing_ok=True)
        return {"saved": False, "empty": True}
    im.save(f)
    return {"saved": True}


@app.delete("/api/projects/{pid}/strokes/{kid}")
def del_strokes(pid: str, kid: str):
    projects.strokes_path(pid, kid).unlink(missing_ok=True)
    return {"ok": True}


# ---------------- 参考画面与底图 ----------------
@app.post("/api/projects/{pid}/reference")
async def upload_reference(pid: str, file: UploadFile = File(...)):
    data = await file.read()
    return projects.set_reference(pid, file.filename or "upload", data)


@app.post("/api/projects/{pid}/frame_ref/{slot}")
async def upload_frame_ref(pid: str, slot: str, file: UploadFile = File(...)):
    data = await file.read()
    return projects.set_frame_ref(pid, slot, file.filename or "upload", data)


@app.delete("/api/projects/{pid}/frame_ref/{slot}")
def delete_frame_ref(pid: str, slot: str):
    projects.clear_frame_ref(pid, slot)
    return {"ok": True}


@app.get("/api/projects/{pid}/frame_ref/{slot}/file")
def frame_ref_file(pid: str, slot: str):
    fr = (projects.load(pid).get("frame_refs") or {}).get(slot)
    f = projects.project_dir(pid) / fr["file"] if fr else None
    if not f or not f.exists():
        raise HTTPException(404, "没有这张图")
    return FileResponse(f, headers={"Cache-Control": "no-cache"})


@app.delete("/api/projects/{pid}/reference")
def delete_reference(pid: str):
    projects.clear_reference(pid)
    return {"ok": True}


@app.get("/api/projects/{pid}/reference/file")
def reference_file(pid: str):
    f = projects.reference_file(pid)
    if not f or not f.exists():
        raise HTTPException(404, "没有参考文件")
    return FileResponse(f)


def _revalidated_jpeg(request: Request, f: Path):
    """预览图：要求浏览器每次校验（换参考、刷新页面后同一地址可能对应新图），没变就回 304 不重传。"""
    st = f.stat()
    etag = f'"{st.st_mtime_ns:x}-{st.st_size:x}"'
    headers = {"Cache-Control": "no-cache", "ETag": etag}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return FileResponse(f, media_type="image/jpeg", headers=headers)


@app.get("/api/projects/{pid}/reference/frame/{n25}")
def reference_frame(pid: str, n25: int, request: Request, w: int = 640):
    """整段参考视频的第 n25 帧缩略图（浏览/选起始帧用，近似画面）。w=160 为小图。"""
    return _revalidated_jpeg(request, projects.video_thumb(pid, n25, w))


@app.get("/api/projects/{pid}/clip/{start25}/{index}")
def clip_frame(pid: str, start25: int, index: int, request: Request):
    """时间轴预览帧：起始帧 start25 往后第 index 帧，与生成实际用的帧一致（按输出画幅裁切的缩小图）。"""
    return _revalidated_jpeg(request, projects.clip_frame(pid, start25, index))


@app.get("/api/projects/{pid}/base/{index}")
def base_image(pid: str, index: int):
    """当前设置下某帧号的底图（PNG，精确输出尺寸）。"""
    img = projects.base_images(pid, None, [index])[index]
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/api/projects/{pid}/flat/{kid}")
def flat_image(pid: str, kid: str):
    """拍平后的画板图（底图 + 笔触），与送进引擎的完全相同，可下载核对。"""
    p = projects.load(pid)
    k = next((k for k in projects.resolved_keyframes(p) if k["id"] == kid), None)
    if not k:
        raise HTTPException(404, "该关键帧当前未使用")
    base = projects.base_images(pid, p, [k["index"]])[k["index"]]
    sp = projects.strokes_path(pid, kid)
    img = imaging.composite(base, Image.open(sp) if sp.exists() else None)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png")


# ---------------- 提示词 ----------------
@app.post("/api/prompt/compose")
async def compose(req: Request):
    b = await req.json()
    text = promptmod.compose(b.get("form", {}), int(b.get("base_mode", 1)))
    final, notes = promptmod.normalize_final(text, int(b.get("base_mode", 1)))
    return {"final": final, "notes": notes, "has_chinese": promptmod.has_chinese(final)}


@app.post("/api/prompt/check")
async def check_prompt(req: Request):
    b = await req.json()
    final, notes = promptmod.normalize_final(b.get("text", ""), int(b.get("base_mode", 1)))
    return {"final": final, "notes": notes, "has_chinese": promptmod.has_chinese(final)}


@app.post("/api/prompt/translate")
async def translate(req: Request):
    b = await req.json()
    text = (b.get("text") or "").strip()
    if not text:
        return {"job": None, "result": {"english": "", "glossary_applied": ""}}
    job = jm.submit("translate", {"text": text})
    return {"job": job.id}


@app.get("/api/translate/config")
def translate_config():
    """翻译接口当前配置（密钥只给打码形式）。配置写在包根目录 .env。"""
    return llm.public_config()


@app.put("/api/translate/config")
async def put_translate_config(req: Request):
    """设置界面保存翻译接口配置：写回 .env，立即生效，不用重启。"""
    b = await req.json()
    return llm.save_config(b)


@app.post("/api/translate/test")
async def translate_test(req: Request):
    """发一句测试翻译。可带 config（设置界面当前表单值，密钥打码形式自动沿用已保存的）。"""
    from . import translate as tr
    b = await req.json() if (await req.body()) else {}
    text = (b.get("text") or "浓烟从坦克上冲天而起，橙色火球爆开").strip()
    overrides = llm.resolve_overrides(b["config"]) if isinstance(b.get("config"), dict) else None
    return await asyncio.to_thread(tr.translate_text, text, overrides)


@app.post("/api/translate/models")
async def translate_models(req: Request):
    """拉取上游可选模型列表（设置界面「拉取模型」）。可带 config 表单覆盖值。"""
    b = await req.json() if (await req.body()) else {}
    overrides = llm.resolve_overrides(b["config"]) if isinstance(b.get("config"), dict) else None
    return await asyncio.to_thread(llm.list_models, overrides)


@app.get("/api/glossary")
def get_glossary():
    return {"builtin": json.loads(promptmod.GLOSSARY_FILE.read_text(encoding="utf-8")),
            "user": json.loads(promptmod.USER_GLOSSARY.read_text(encoding="utf-8")) if promptmod.USER_GLOSSARY.exists() else {}}


@app.put("/api/glossary")
async def put_glossary(req: Request):
    b = await req.json()
    entries = {str(k).strip(): str(v).strip() for k, v in (b.get("user") or {}).items() if str(k).strip()}
    promptmod.save_user_glossary(entries)
    return {"ok": True, "count": len(entries)}


# ---------------- 任务 ----------------
@app.post("/api/projects/{pid}/generate")
def generate(pid: str):
    projects.load(pid)
    job = jm.submit("generate", {"pid": pid})
    return {"job": job.id}


@app.post("/api/test/block")
def test_block(seconds: int = 300):
    import os
    if os.environ.get("FX_TEST_NODES") != "1":
        raise HTTPException(404, "not found")
    return {"job": jm.submit("test_block", {"seconds": seconds}).id}


@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    j = jm.jobs.get(jid)
    if not j:
        raise HTTPException(404, "任务不存在")
    return j.snapshot()


@app.post("/api/jobs/{jid}/cancel")
def cancel_job(jid: str):
    if jid not in jm.jobs:
        raise HTTPException(404, "任务不存在")
    jm.cancel(jid)
    return jm.jobs[jid].snapshot()


@app.websocket("/api/ws")
async def ws(sock: WebSocket):
    if _request_allowed(sock.headers) or \
            _lan_state(sock.client.host if sock.client else "", sock.cookies, None) != "ok":
        await sock.close(code=1008)
        return
    await sock.accept()
    seen: dict[str, int] = {}
    last_status = -1
    try:
        while True:
            if jm.version != last_status:
                last_status = jm.version
                await sock.send_json({"type": "status", "data": status()})
            for j in list(jm.jobs.values()):
                if seen.get(j.id) != j.version:
                    seen[j.id] = j.version
                    await sock.send_json({"type": "job", "data": j.snapshot()})
            await asyncio.sleep(0.25)
    except (WebSocketDisconnect, RuntimeError):
        pass


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(paths.ROOT))
    except ValueError:
        return str(p)


# ---------------- 结果 ----------------
_RESULT_RE = re.compile(r"^[\w\-一-鿿]+/[\w\-一-鿿]+\.mp4$")


def _result_path(rel: str) -> Path:
    if not _RESULT_RE.match(rel):
        raise ValueError("结果文件名不合法")
    f = paths.OUTPUT_DIR / rel
    if not f.exists():
        raise FileNotFoundError("结果文件不存在")
    return f


@app.get("/api/projects/{pid}/results")
def list_results(pid: str):
    d = paths.OUTPUT_DIR / pid
    out = []
    if d.exists():
        for f in sorted(d.glob("*.mp4"), key=lambda x: -x.stat().st_mtime):
            if "_screen" in f.stem or "_addition" in f.stem:
                continue
            pj = f.with_suffix(".json")
            params = json.loads(pj.read_text(encoding="utf-8")) if pj.exists() else {}
            comps = {m: f"{pid}/{f.stem}_{m}.mp4" for m in ("screen", "addition") if (d / f"{f.stem}_{m}.mp4").exists()}
            out.append({"file": f"{pid}/{f.name}", "params": params, "composites": comps})
    return out


@app.delete("/api/results")
def delete_result(file: str):
    """把一次生成的结果（MP4、参数 JSON、导出的合成版）移到回收站。"""
    src = _result_path(file)
    files = [src, src.with_suffix(".json")] + [src.with_name(f"{src.stem}_{m}.mp4") for m in ("screen", "addition")]
    box = projects.move_to_trash(files, f"result_{src.parent.name}_{src.stem}")
    return {"ok": True, "trash": _rel(box)}


@app.get("/media/{rel:path}")
def media(rel: str):
    return FileResponse(_result_path(rel), media_type="video/mp4")


@app.post("/api/results/overlay")
async def overlay(req: Request):
    """黑底素材叠加到参考画面（滤色 / 相加），导出合成版 MP4。"""
    b = await req.json()
    src = _result_path(b["file"])
    blend = b.get("blend", "screen")
    pid = b["file"].split("/")[0]
    params = json.loads(src.with_suffix(".json").read_text(encoding="utf-8"))
    ref = params.get("reference")
    if not ref:
        raise ValueError("这次生成没有参考画面，无法叠加")
    plate = projects.project_dir(pid) / ref["file"]
    if not plate.exists():
        raise ValueError("参考文件已被替换或删除，无法叠加")
    out = src.with_name(f"{src.stem}_{blend}.mp4")
    await asyncio.to_thread(video.overlay, src, plate, out, blend, int(ref.get("start25", 0)),
                            ref["type"] == "image", int(params["width"]), int(params["height"]))
    return {"file": f"{pid}/{out.name}"}


# ---------------- 前端 ----------------
if paths.WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=str(paths.WEB_DIST), html=True), name="web")
