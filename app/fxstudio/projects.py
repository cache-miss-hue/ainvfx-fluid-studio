"""项目 = 一个文件夹：project.json + keyframes/<关键帧id>.png（笔触层）+ reference/（参考图或视频）。"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

from PIL import Image, ImageOps

from . import imaging, paths, timeline, video

DEFAULT_PALETTE = [
    {"name": "火焰·橙", "color": "#ff7814"},
    {"name": "火焰·黄", "color": "#ffd73c"},
    {"name": "浓烟·深灰", "color": "#464648"},
    {"name": "浅灰烟", "color": "#a0a0a0"},
    {"name": "白（蒸汽/云）", "color": "#ffffff"},
    {"name": "浅蓝（水）", "color": "#8cc8ff"},
]


def new_project_data(name: str) -> dict:
    return {
        "version": 1, "name": name, "created": time.time(),
        "seconds": 5, "scheme": 1,
        "keyframes": [{"id": "k_first", "index": 0}, {"id": "k_tail", "index": -1, "tail": True}],
        "snap": True,
        "base_mode": 1, "blur_radius": 12, "blur_sigma": 4.0, "colors": 8,
        "reference": None,
        "width": 1024, "height": 576,
        "seed": 42, "lora_strength": 1.0, "tile_size": 512,
        "prompt": {"scene": "", "scene_en": "", "effect": "explosion", "effect_desc": "", "effect_desc_en": "",
                   "camera": "static camera", "nothing_else": True, "final": "", "final_edited": False},
        "palette": DEFAULT_PALETTE,
    }


_SAFE = re.compile(r"[^0-9A-Za-z_\-一-鿿]+")


def _pid_dir(pid: str) -> Path:
    if not pid or "/" in pid or "\\" in pid or pid.startswith(".") or ".." in pid:
        raise ValueError("项目编号不合法")
    d = paths.PROJECTS_DIR / pid
    if not (d / "project.json").exists():
        raise FileNotFoundError("项目不存在")
    return d


def list_projects() -> list[dict]:
    out = []
    if not paths.PROJECTS_DIR.exists():
        return out
    for d in paths.PROJECTS_DIR.iterdir():
        f = d / "project.json"
        if f.exists():
            try:
                j = json.loads(f.read_text(encoding="utf-8"))
                out.append({"id": d.name, "name": j.get("name", d.name), "mtime": f.stat().st_mtime})
            except Exception:
                pass
    return sorted(out, key=lambda x: -x["mtime"])


def create(name: str) -> str:
    name = (name or "未命名项目").strip()[:60] or "未命名项目"
    pid = (_SAFE.sub("_", name).strip("_") or "project")[:40] + "_" + uuid.uuid4().hex[:6]
    d = paths.PROJECTS_DIR / pid
    (d / "keyframes").mkdir(parents=True)
    (d / "reference").mkdir()
    save(pid, new_project_data(name), _create=True)
    return pid


def load(pid: str) -> dict:
    return json.loads((_pid_dir(pid) / "project.json").read_text(encoding="utf-8"))


def save(pid: str, data: dict, _create=False):
    d = paths.PROJECTS_DIR / pid if _create else _pid_dir(pid)
    validate(data)
    tmp = d / "project.json.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(d / "project.json")


def validate(p: dict):
    if not 1 <= int(p["seconds"]) <= 5:
        raise ValueError("时长只支持 1–5 秒")
    if int(p["base_mode"]) not in (0, 1, 2):
        raise ValueError("底图模式只能是 0/1/2")
    for k in ("width", "height"):
        if int(p[k]) % 64 or not 256 <= int(p[k]) <= 2048:
            raise ValueError("输出宽高必须是 64 的倍数（256–2048）")
    ids = [k["id"] for k in p["keyframes"]]
    if len(ids) != len(set(ids)):
        raise ValueError("关键帧编号重复")
    for k in ids:
        if not re.fullmatch(r"[A-Za-z0-9_\-]{1,40}", k):
            raise ValueError("关键帧编号不合法")


def project_dir(pid: str) -> Path:
    return _pid_dir(pid)


def strokes_path(pid: str, kid: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,40}", kid):
        raise ValueError("关键帧编号不合法")
    return _pid_dir(pid) / "keyframes" / f"{kid}.png"


def resolved_keyframes(p: dict) -> list[dict]:
    """把项目里的关键帧换算成实际帧号（尾帧跟随时长；开启吸附时落到 0 / 8k+1 / 尾帧网格）。"""
    secs = int(p["seconds"])
    last = timeline.last_index(secs)
    out = []
    for kf in p["keyframes"]:
        idx = last if kf.get("tail") else int(kf["index"])
        if idx > last or idx < 0:
            continue
        if p.get("snap", True):
            idx = timeline.snap(idx, secs)
        out.append({"id": kf["id"], "index": idx, "tail": bool(kf.get("tail"))})
    seen = {}
    for k in sorted(out, key=lambda k: (k["index"], not k["tail"])):
        seen.setdefault(k["index"], k)
    return sorted(seen.values(), key=lambda k: k["index"])


# ---------- 参考画面 ----------
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}
CLIP_FRAMES = 121          # 时间轴预览一次抽满 5 秒（121 帧），改时长不用重抽

_locks_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}


def _lock_for(key: str) -> threading.Lock:
    """同一份缓存只让一个请求去生成，其余等它做完直接用（拖动滑条时不会并发起多个 ffmpeg）。"""
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def _touch(d: Path):
    """记录缓存最近一次被用到的时间（启动时按它清理长期不用的缓存）。"""
    try:
        os.utime(d)
    except OSError:
        pass


def _validate_reference(f: Path, kind: str) -> dict:
    try:
        if kind == "image":
            with Image.open(f) as im:
                im.verify()
            with Image.open(f) as im:
                im = ImageOps.exif_transpose(im)        # 手机照片的旋转标记：按转正后的宽高算比例
                return {"width": im.width, "height": im.height}
        info = video.probe(f)
        if info["frames25"] < 1:
            raise ValueError("视频时长为 0")
        return info
    except ValueError as ex:
        raise ValueError(f"文件无法读取：{ex}") from None
    except Exception as ex:
        raise ValueError(f"文件无法读取（{ex.__class__.__name__}），可能已损坏或格式不受支持") from None


def set_reference(pid: str, filename: str, data: bytes) -> dict:
    """先把新文件写到临时位置并校验，通过后才替换旧参考；新文件读不了时旧参考原样保留。"""
    d = _pid_dir(pid)
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_EXT:
        kind = "image"
    elif ext in VIDEO_EXT:
        kind = "video"
    else:
        raise ValueError("只支持图片（png/jpg/webp/bmp）或视频（mp4/mov/webm/mkv/avi）")
    if not data:
        raise ValueError("文件是空的")
    tmp = d / f".upload_tmp{ext}"
    tmp.write_bytes(data)
    try:
        info: dict = {"type": kind, "original_name": Path(filename).name, "start25": 0}
        info.update(_validate_reference(tmp, kind))
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    old = reference_file_or_none(pid)
    refdir = d / "reference"
    if old is not None:
        drop_video_caches(old)
    shutil.rmtree(refdir, ignore_errors=True)
    refdir.mkdir(exist_ok=True)
    f = refdir / f"reference{ext}"
    os.replace(tmp, f)
    info["file"] = f"reference/{f.name}"
    p = load(pid)
    p["reference"] = info
    save(pid, p)
    # 建议的输出尺寸：比例跟素材走（不裁切），面积按显存预算；由前端套用（要处理已画的笔触层）
    return {**info, "fit_size": list(imaging.fit_size(int(info["width"]), int(info["height"])))}


def set_frame_ref(pid: str, slot: str, filename: str, data: bytes) -> dict:
    """导入首帧/尾帧图片：只管这一帧的底图，不影响主参考（视频/图片）。"""
    if slot not in FRAME_SLOTS:
        raise ValueError("槽位只能是 first / tail")
    d = _pid_dir(pid)
    ext = Path(filename).suffix.lower()
    if ext not in IMAGE_EXT:
        raise ValueError("首帧/尾帧只支持图片（png/jpg/webp/bmp）")
    if not data:
        raise ValueError("文件是空的")
    fdir = d / "frame_refs"
    fdir.mkdir(exist_ok=True)
    tmp = fdir / f".upload_tmp{ext}"
    tmp.write_bytes(data)
    try:
        info = {"type": "image", "original_name": Path(filename).name, **_validate_reference(tmp, "image")}
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    for old in fdir.glob(f"{slot}.*"):
        drop_video_caches(old)
        old.unlink(missing_ok=True)
    f = fdir / f"{slot}{ext}"
    os.replace(tmp, f)
    info["file"] = f"frame_refs/{f.name}"
    p = load(pid)
    p.setdefault("frame_refs", {})[slot] = info
    save(pid, p)
    return {**info, "fit_size": list(imaging.fit_size(int(info["width"]), int(info["height"])))}


def clear_frame_ref(pid: str, slot: str):
    if slot not in FRAME_SLOTS:
        raise ValueError("槽位只能是 first / tail")
    d = _pid_dir(pid)
    for old in (d / "frame_refs").glob(f"{slot}.*"):
        drop_video_caches(old)
        old.unlink(missing_ok=True)
    p = load(pid)
    (p.get("frame_refs") or {}).pop(slot, None)
    save(pid, p)


def clear_reference(pid: str):
    d = _pid_dir(pid)
    old = reference_file_or_none(pid)
    p = load(pid)
    p["reference"] = None
    save(pid, p)                      # 先改项目：文件被预览或抽帧占用删不掉时，移除也照样生效
    if old is not None:
        drop_video_caches(old)
    shutil.rmtree(d / "reference", ignore_errors=True)
    (d / "reference").mkdir(exist_ok=True)


def reference_file(pid: str) -> Path | None:
    p = load(pid)
    r = p.get("reference")
    return (_pid_dir(pid) / r["file"]) if r else None


def reference_file_or_none(pid: str) -> Path | None:
    """存在的参考文件路径；没有参考或文件已丢失时返回 None。"""
    f = reference_file(pid)
    return f if f is not None and f.exists() else None


def _video_cache_key(f: Path) -> str:
    if not f.exists():
        raise FileNotFoundError("参考文件不见了（可能被移动或删除），请重新拖入参考画面")
    st = f.stat()
    return hashlib.sha1(f"{f}:{st.st_size}:{st.st_mtime}".encode()).hexdigest()[:12]


def drop_video_caches(f: Path):
    """删除某个参考文件的全部缓存（预览帧、缩略图、底图），换掉或移除参考时调用。"""
    try:
        vk = _video_cache_key(f)
    except (FileNotFoundError, OSError):
        return
    for sub in ("clip", "thumb", "base"):
        for d in (paths.CACHE_DIR / sub).glob(f"{vk}*"):
            shutil.rmtree(d, ignore_errors=True)


def _video_ref(pid: str) -> Path:
    p = load(pid)
    r = p.get("reference")
    if not r or r["type"] != "video":
        raise FileNotFoundError("没有参考视频")
    return _pid_dir(pid) / r["file"]


def clip_frame(pid: str, start25: int, index: int) -> Path:
    """时间轴预览帧：从 start25 起第 index 帧，取帧方式与生成完全一致（按输出画幅居中裁切、缩小的 JPEG）。
    start25 由前端直接给（不用等项目自动保存），同一 起始帧+画幅 只抽一次。"""
    f = _video_ref(pid)
    p = load(pid)
    w, h = int(p["width"]), int(p["height"])
    start25, index = max(0, int(start25)), int(index)
    if not 0 <= index < CLIP_FRAMES:
        raise FileNotFoundError("帧号超出范围")
    vk = _video_cache_key(f)
    d = paths.CACHE_DIR / "clip" / f"{vk}_{start25}_{w}x{h}"
    if not (d / "_done").exists():
        with _lock_for(str(d)):
            if not (d / "_done").exists():
                shutil.rmtree(d, ignore_errors=True)
                n = video.clip_previews(f, start25, CLIP_FRAMES, d, w, h)
                (d / "_done").write_text(str(n))
    _touch(d)
    fr = d / f"{index:03d}.jpg"
    if not fr.exists():
        raise FileNotFoundError("这一帧超出了参考视频的长度")
    return fr


def video_thumb(pid: str, n25: int, width: int = 640) -> Path:
    """整段参考视频里第 n25 帧（25fps 计）的缩略图：浏览、选起始帧用（近似画面，单帧 seek，快）。"""
    f = _video_ref(pid)
    p = load(pid)
    n25 = int(n25)
    last = max(0, int(p["reference"].get("frames25", 1)) - 1)
    if not 0 <= n25 <= last:
        raise FileNotFoundError("该帧不存在")
    width = 160 if int(width) <= 160 else 640
    d = paths.CACHE_DIR / "thumb" / _video_cache_key(f)
    out = d / f"{n25:05d}_{width}.jpg"
    if not out.exists():
        with _lock_for(str(out)):
            if not out.exists():
                video.single_frame(f, n25, out, width)
    _touch(d)
    return out


# ---------- 底图 ----------
FRAME_SLOTS = ("first", "tail")


def _slot_of(p: dict, index: int) -> str | None:
    """帧号对应的首/尾帧槽位（首帧 = 0，尾帧 = 所选时长的最后一帧）。"""
    last = timeline.last_index(int(p["seconds"]))
    return "first" if index == 0 else ("tail" if index == last else None)


def base_images(pid: str, p: dict | None = None, indices: list[int] | None = None) -> dict[int, Image.Image]:
    """按参考画面、首/尾帧图与底图模式实时算出各关键帧的底图（不入库，只有磁盘缓存）。
    首帧/尾帧各自有图片时用自己的；其余帧用主参考；没有主参考时退回用首帧图（再退回尾帧图）。"""
    p = p or load(pid)
    if indices is None:
        indices = [k["index"] for k in resolved_keyframes(p)]
    w, h, mode = int(p["width"]), int(p["height"]), int(p["base_mode"])
    frs = p.get("frame_refs") or {}
    if mode == 0 or not (p.get("reference") or frs.get("first") or frs.get("tail")):
        return {i: Image.new("RGB", (w, h), (0, 0, 0)) for i in indices}
    out: dict[int, Image.Image] = {}
    rest: list[int] = []
    for i in indices:
        fr = frs.get(_slot_of(p, i) or "")
        if fr:
            out[i] = _ref_bases(pid, p, fr, [i])[i]
        else:
            rest.append(i)
    if rest:
        main = p.get("reference") or frs.get("first") or frs.get("tail")
        out.update(_ref_bases(pid, p, main, rest))
    return out


def _ref_bases(pid: str, p: dict, ref: dict, indices: list[int]) -> dict[int, Image.Image]:
    w, h, mode = int(p["width"]), int(p["height"]), int(p["base_mode"])
    f = _pid_dir(pid) / ref["file"]
    start = int(ref.get("start25", 0)) if ref["type"] == "video" else 0
    vk = _video_cache_key(f)
    key = json.dumps([vk, w, h, mode, p["blur_radius"], p["blur_sigma"], p["colors"], start])
    hdir = paths.CACHE_DIR / "base" / f"{vk}_{hashlib.sha1(key.encode()).hexdigest()[:16]}"
    name = (lambda i: f"{i:03d}.png") if ref["type"] == "video" else (lambda i: "img.png")

    def cached():
        out, todo = {}, []
        for i in indices:
            c = hdir / name(i)
            if c.exists():
                out[i] = Image.open(c).convert("RGB")
            else:
                todo.append(i)
        return out, todo

    out, todo = cached()
    if todo:
        with _lock_for(str(hdir)):        # 同一份底图只算一次；别的请求等它写完再读
            out, todo = cached()
            if todo:
                hdir.mkdir(parents=True, exist_ok=True)
                args = (mode, w, h, int(p["blur_radius"]), float(p["blur_sigma"]), int(p["colors"]))

                def put(i, img):
                    tmp = hdir / (name(i) + ".tmp")
                    img.save(tmp, "PNG")
                    os.replace(tmp, hdir / name(i))

                if ref["type"] == "image":
                    with Image.open(f) as im:
                        b = imaging.make_base(ImageOps.exif_transpose(im).copy(), *args)
                    put(0, b)
                    for i in todo:
                        out[i] = b
                else:
                    frames = video.keyframe_refs(f, start, todo)
                    for i in todo:
                        out[i] = imaging.make_base(frames[i], *args)
                        put(i, out[i])
    _touch(hdir)
    return out


def check_video_length(p: dict) -> str | None:
    ref = p.get("reference")
    if not ref or ref["type"] != "video" or int(p["base_mode"]) == 0:
        return None
    need = timeline.total_frames(int(p["seconds"]))
    have = int(ref.get("frames25", 0)) - int(ref.get("start25", 0))
    if have < need:
        return (f"参考视频从起始帧往后约 {max(have, 0)} 帧（{max(have, 0) / 25:.2f} 秒），"
                f"所选时长需要 {need} 帧；请把起始帧往前调或缩短时长。")
    return None


def prepare_job(pid: str, job_dir: Path) -> dict:
    """把项目整理成引擎能读的控制描述（job_dir/control.json + PNG），返回摘要。"""
    from . import control
    p = load(pid)
    kfs = resolved_keyframes(p)
    if not kfs:
        raise ValueError("没有任何关键帧")
    frs = p.get("frame_refs") or {}
    if int(p["base_mode"]) != 0 and not (p.get("reference") or frs.get("first") or frs.get("tail")):
        raise ValueError("底图模式 1/2 需要先选择参考图或参考视频（或导入首帧/尾帧图）")
    secs = int(p["seconds"])
    n = timeline.total_frames(secs)
    bases = base_images(pid, p, [k["index"] for k in kfs])
    items, empty = [], []
    for k in kfs:
        sp = strokes_path(pid, k["id"])
        has = sp.exists()
        items.append({"index": k["index"], "base": bases[k["index"]], "strokes": sp if has else None})
        if not has:
            empty.append(k["index"])
    tail_img = None
    tail_ref = frs.get("tail")
    if tail_ref and p.get("tail_guide", True) and any(k["tail"] for k in kfs):
        with Image.open(_pid_dir(pid) / tail_ref["file"]) as im:
            tail_img = ImageOps.fit(ImageOps.exif_transpose(im).convert("RGB"),
                                    (int(p["width"]), int(p["height"])), Image.LANCZOS)
    control.write_control(job_dir, int(p["width"]), int(p["height"]), n, items, tail_img)
    return {"project": p, "keyframes": kfs, "frames": n, "empty_keyframes": empty,
            "tail_idx": n - 1 if tail_img is not None else None}


# ---------- 删除与清理 ----------
TRASH_DIR_NAME = "trash"


def _trash_root() -> Path:
    return paths.RUNTIME_DIR / TRASH_DIR_NAME


def move_to_trash(files: list[Path], label: str) -> Path:
    """移到 runtime/trash/<时间>_<名字>/（不直接删除，30 天内可以手动找回）。
    放进新建的目录里：回收站按这个目录的创建时间过期，不受被删文件本身修改时间的影响。"""
    box = _trash_root() / f"{time.strftime('%Y%m%d_%H%M%S')}_{label}"
    n = 1
    while box.exists():
        n += 1
        box = box.with_name(f"{box.name.rsplit('~', 1)[0]}~{n}")
    box.mkdir(parents=True)
    for f in files:
        if f.exists():
            shutil.move(str(f), str(box / f.name))
    return box


def delete_project(pid: str) -> Path:
    """项目文件夹与它的全部成片一起移到回收站。"""
    d = _pid_dir(pid)
    ref = reference_file_or_none(pid)
    if ref is not None:
        drop_video_caches(ref)
    box = move_to_trash([], pid)
    shutil.move(str(d), str(box / "project"))
    out = paths.OUTPUT_DIR / pid
    if out.exists():
        shutil.move(str(out), str(box / "output"))
    return box


def cleanup_runtime(cache_days: int = 14, job_days: int = 3, trash_days: int = 30) -> dict:
    """启动时清理：长期没用到的缓存、失败任务留下的临时目录、过期的回收站内容。出错不影响启动。"""
    now = time.time()
    removed = {"cache": 0, "jobs": 0, "trash": 0}

    def old(p: Path, days: int) -> bool:
        try:
            return now - p.stat().st_mtime > days * 86400
        except OSError:
            return False

    for sub in ("base", "clip", "thumb", "vprev"):
        root = paths.CACHE_DIR / sub
        if root.exists():
            for d in root.iterdir():
                if sub == "vprev" or old(d, cache_days):      # vprev 是旧版整段抽帧缓存，已不再使用
                    shutil.rmtree(d, ignore_errors=True)
                    removed["cache"] += 1
    if paths.JOBS_DIR.exists():
        for d in paths.JOBS_DIR.iterdir():
            if d.is_dir() and old(d, job_days):
                shutil.rmtree(d, ignore_errors=True)
                removed["jobs"] += 1
    if _trash_root().exists():
        for d in _trash_root().iterdir():
            if old(d, trash_days):
                shutil.rmtree(d, ignore_errors=True) if d.is_dir() else d.unlink(missing_ok=True)
                removed["trash"] += 1
    return removed
