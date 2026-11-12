"""启动自检：显卡、显存、内存、磁盘、驱动、模型文件、引擎文件。全部中文说明，不抛堆栈。"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from . import paths

MIN_DRIVER = 580.0   # CUDA 13.0 (cu130) 需要的最低驱动版本（Windows 580.xx）


def _item(name, ok, detail, advice="", level=None):
    return {"name": name, "ok": bool(ok), "level": level or ("ok" if ok else "error"), "detail": detail, "advice": advice}


def gpu_info():
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.used,driver_version",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10,
                           creationflags=0x08000000)
        name, total, used, drv = [x.strip() for x in r.stdout.strip().splitlines()[0].split(",")]
        return {"name": name, "total_mb": int(total), "used_mb": int(used), "driver": drv}
    except Exception:
        return None


def process_vram_mb(pid: int) -> float:
    """Windows 性能计数器里某进程的专用显存（MB）。取不到时返回 0。"""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            f"((Get-Counter '\\GPU Process Memory(pid_{int(pid)}_*)\\Dedicated Usage' -ErrorAction Stop)"
                            ".CounterSamples | Measure-Object CookedValue -Sum).Sum"],
                           capture_output=True, text=True, timeout=20, creationflags=0x08000000)
        return float(r.stdout.strip() or 0) / 1024 ** 2
    except Exception:
        return 0.0


def model_entries(manifest=None):
    m = manifest or json.loads(paths.MANIFEST.read_text(encoding="utf-8"))
    out = []
    for e in m["models"]:
        f = paths.MODELS_DIR / e["path"]
        src = None
        if f.exists():
            src = f
        elif paths.DEV_MODEL_PATHS.exists() and e.get("dev_source") and Path(e["dev_source"]).exists():
            src = Path(e["dev_source"])
        out.append((e, src))
    return out


def sha256_file(f: Path, chunk=16 * 1024 * 1024):
    h = hashlib.sha256()
    with open(f, "rb") as fh:
        while b := fh.read(chunk):
            h.update(b)
    return h.hexdigest()


def run(full_hash: bool = False, engine_pid: int | None = None) -> dict:
    items = []
    g = gpu_info()
    if not g:
        items.append(_item("显卡", False, "没有检测到 NVIDIA 显卡或驱动（nvidia-smi 不可用）",
                           "本软件需要 NVIDIA 显卡，并安装较新的显卡驱动。"))
    else:
        items.append(_item("显卡", True, g["name"]))
        vram_gb = g["total_mb"] / 1024
        if vram_gb >= 15.5:
            items.append(_item("显存", True, f"{vram_gb:.0f} GB"))
        else:
            items.append(_item("显存", False, f"{vram_gb:.0f} GB（本软件只按 16GB 显存测试）",
                               "可以尝试运行，但可能显存不足；请用较小的输出尺寸（如 768×448）。", level="warn"))
        # 经验阈值（非精确测量）：16GB 显存里，其他程序占用越多，生成越容易显存不足或变慢。
        other = g["used_mb"] - (process_vram_mb(engine_pid) if engine_pid else 0)
        if other > 2500:
            items.append(_item("显存占用", False, f"其他程序已占用约 {other / 1024:.1f} GB 显存（不含本软件）",
                               "建议关闭其他用显卡的程序（游戏、其他 AI 软件、开着很多标签的浏览器）后再生成；"
                               "其他程序占用越多，越容易显存不足。", level="warn"))
        try:
            ok = float(g["driver"].split(".")[0] + "." + g["driver"].split(".")[1]) >= MIN_DRIVER
        except Exception:
            ok = True
        # 580 是 CUDA 13 驱动的公开最低版本，本机（621.14）以外未实测，所以只作提醒不拦截
        items.append(_item("显卡驱动", ok, g["driver"], "" if ok else f"驱动版本可能太旧（建议 {MIN_DRIVER:.0f} 或更新）；若生成失败请先升级驱动。",
                           level=None if ok else "warn"))
    try:
        import psutil
        ram = psutil.virtual_memory().total / 1024 ** 3
        items.append(_item("内存", ram >= 60, f"{ram:.0f} GB",
                           "" if ram >= 60 else "建议 64GB 内存；内存不足时模型加载可能很慢或失败。",
                           level=None if ram >= 60 else "warn"))
    except Exception:
        pass
    du = shutil.disk_usage(paths.ROOT)
    free = du.free / 1024 ** 3
    items.append(_item("磁盘空间", free >= 5, f"剩余 {free:.0f} GB", "" if free >= 5 else "磁盘空间不足 5GB，成片可能无法保存。",
                       level=None if free >= 5 else "warn"))
    for f, label in ((paths.PYTHON_EXE, "引擎 Python"), (paths.COMFY_DIR / "main.py", "引擎程序"),
                     (paths.FFMPEG, "ffmpeg")):
        items.append(_item(label, f.exists(), "正常" if f.exists() else f"缺少 {f.relative_to(paths.ROOT)}",
                           "" if f.exists() else "安装包不完整，请重新解压完整的软件包。"))
    for e, src in model_entries():
        name = Path(e["path"]).name
        if src is None:
            items.append(_item(f"模型 {name}", not e["required"],
                               "缺失" if e["required"] else "缺失（可选）",
                               f"请把 {name} 放到 models/{Path(e['path']).parent.as_posix()}/ 目录" if e["required"] else "",
                               level="error" if e["required"] else "info"))
            continue
        size = src.stat().st_size
        ok = size == e["size"]
        detail = f"{size / 1024 ** 3:.2f} GB" + ("（开发链接）" if not str(src).startswith(str(paths.MODELS_DIR)) else "")
        adv = "" if ok else f"文件大小不对（应为 {e['size']} 字节），可能下载不完整，请重新复制。"
        if ok and full_hash and e.get("sha256"):
            hv = sha256_file(src)
            ok = hv == e["sha256"]
            detail += "，哈希一致" if ok else "，哈希不一致"
            adv = "" if ok else "文件内容与清单不一致，请重新复制该模型。"
        items.append(_item(f"模型 {name}", ok, detail, adv))
    from . import llm
    tc = llm.public_config()
    if tc["configured"]:
        items.append(_item("翻译接口", True, f"{tc['model']} @ {tc['base_url']}" + ("" if tc["key"] else "（未填密钥）")))
    else:
        items.append(_item("翻译接口", False, "未配置（中文转英文只能按术语表替换）",
                           "在软件目录的 .env 里填写 FX_TRANSLATE_BASE_URL / FX_TRANSLATE_API_KEY / FX_TRANSLATE_MODEL，"
                           "改完不用重启。不配置也能用：提示词直接写英文即可。", level="info"))
    blocking = [i for i in items if i["level"] == "error"]
    return {"ok": not blocking, "items": items}
