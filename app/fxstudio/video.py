"""参考视频与结果视频处理（内置 ffmpeg）。

抽帧参数与原工作流的 VHS_LoadVideoPath（ffmpeg 生成器）一致：
16 位 RGB 解码、fps=25 滤镜、按 起始帧/25 秒 seek。
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from . import paths

_NOWIN = 0x08000000  # CREATE_NO_WINDOW


def _run(args, **kw):
    return subprocess.run(args, capture_output=True, creationflags=_NOWIN, **kw)


def ffmpeg_exe() -> str:
    return str(paths.FFMPEG) if paths.FFMPEG.exists() else "ffmpeg"


def ffprobe_exe() -> str:
    return str(paths.FFPROBE) if paths.FFPROBE.exists() else "ffprobe"


def probe(video: Path) -> dict:
    r = _run([ffprobe_exe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
              "stream=width,height,r_frame_rate,avg_frame_rate,nb_frames,duration:stream_side_data=rotation"
              ":stream_tags=rotate:format=duration",
              "-of", "json", str(video)])
    if r.returncode != 0:
        raise ValueError("无法读取视频：" + r.stderr.decode("utf-8", "replace")[-300:])
    j = json.loads(r.stdout.decode("utf-8"))
    if not j.get("streams"):
        raise ValueError("文件里没有视频画面（可能是纯音频或损坏的文件）")
    st = j["streams"][0]
    num, den = (st.get("avg_frame_rate") or st.get("r_frame_rate") or "25/1").split("/")
    fps = float(num) / float(den) if float(den) else 25.0
    dur = float(st.get("duration") or j.get("format", {}).get("duration") or 0)
    w, h = int(st["width"]), int(st["height"])
    rot = (st.get("tags") or {}).get("rotate")
    for sd in st.get("side_data_list") or []:
        rot = sd.get("rotation", rot)
    try:
        if abs(int(float(rot or 0))) % 180 == 90:       # 手机竖拍：ffmpeg 解码时自动转正，帧的宽高要对调
            w, h = h, w
    except ValueError:
        pass
    return {"width": w, "height": h, "fps": fps, "duration": dur, "frames25": int(dur * 25)}


def _clip_args(video: Path, start25: int, count: int, pix_fmt: str) -> list[str]:
    """与 VHS 的 ffmpeg 生成器一致的 seek/滤镜（生成用的参考帧与时间轴预览帧都走这一条，保证取到同一帧）。"""
    start_time = start25 * (1 / 25)
    args_input = ["-i", str(video)]
    if start_time > 0:
        if start_time > 4:
            post_seek = ["-ss", "4"]
            args_input = ["-ss", str(start_time - 4)] + args_input
        else:
            post_seek = ["-ss", str(start_time)]
    else:
        post_seek = []
    return [ffmpeg_exe(), "-v", "error", "-an"] + args_input + ["-pix_fmt", pix_fmt] + post_seek + \
           ["-vf", "fps=fps=25", "-frames:v", str(count), "-f", "rawvideo", "-"]


def _stream_frames(video: Path, start25: int, count: int, pix_fmt: str = "rgb48le"):
    """逐帧产出 (序号, 原始字节)。一次只在内存里放一帧（原来是把全部帧一起读进内存）。"""
    info = probe(video)
    w, h = info["width"], info["height"]
    frame_bytes = w * h * 3 * (2 if pix_fmt == "rgb48le" else 1)
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(_clip_args(video, start25, count, pix_fmt), stdout=subprocess.PIPE, stderr=err,
                                creationflags=_NOWIN)
        try:
            for i in range(count):
                buf = proc.stdout.read(frame_bytes)
                if len(buf) < frame_bytes:
                    break
                yield i, w, h, buf
            proc.stdout.close()
            rc = proc.wait()
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        if rc != 0:
            err.seek(0)
            raise ValueError("视频抽帧失败：" + err.read().decode("utf-8", "replace")[-300:])


def frames_at_25(video: Path, start25: int, count: int) -> np.ndarray:
    """返回 [count,H,W,3] float32（0–1）。与 VHS 的 ffmpeg 生成器一致的 seek/滤镜。
    注意会把全部帧放进内存，只给测试和对比用；生成用 keyframe_refs（只保留需要的帧）。"""
    fr = [np.frombuffer(b, dtype=np.uint16).reshape(h, w, 3).astype(np.float32) / 65535.0
          for _, w, h, b in _stream_frames(video, start25, count)]
    if not fr:
        info = probe(video)
        return np.zeros((0, info["height"], info["width"], 3), dtype=np.float32)
    return np.stack(fr)


def keyframe_refs(video: Path, start25: int, indices: list[int]) -> dict[int, np.ndarray]:
    """为每个关键帧帧号取参考帧（起始帧 + 帧号）。长度不足时抛出中文错误。
    逐帧读取、只留下需要的帧：4K 素材也只占几帧的内存。数值与原实现逐位相同。"""
    need = max(indices) + 1
    want = set(indices)
    out: dict[int, np.ndarray] = {}
    have = 0
    for i, w, h, b in _stream_frames(video, start25, need):
        have = i + 1
        if i in want:
            out[i] = np.frombuffer(b, dtype=np.uint16).reshape(h, w, 3).astype(np.float32) / 65535.0
    if have < need:
        raise ValueError(f"参考视频从起始帧往后只有 {have} 帧（{have / 25:.2f} 秒），"
                         f"不够所选时长需要的 {need} 帧；请把起始帧往前调，或缩短时长。")
    return out


def center_crop_box(src_w: int, src_h: int, width: int, height: int) -> tuple[int, int, int, int]:
    """与 imaging.scale_center_crop（ImageScale crop=center）相同的裁切框 (左, 上, 右, 下)。"""
    old_aspect, new_aspect = src_w / src_h, width / height
    x = y = 0
    if old_aspect > new_aspect:
        x = round((src_w - src_w * (new_aspect / old_aspect)) / 2)
    elif old_aspect < new_aspect:
        y = round((src_h - src_h * (old_aspect / new_aspect)) / 2)
    return x, y, src_w - x, src_h - y


def clip_previews(video: Path, start25: int, count: int, out_dir: Path, width: int, height: int,
                  max_w: int = 640) -> int:
    """时间轴预览帧：从起始帧起的 count 帧，取帧方式与生成完全相同（同一套 seek/fps 参数），
    按输出画幅居中裁切后缩小存成 JPEG（000.jpg …）。返回实际帧数（视频不够长时少于 count）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    pw = min(max_w, width)
    ph = max(2, round(pw * height / width))
    n = 0
    for i, w, h, b in _stream_frames(video, start25, count, pix_fmt="rgb24"):
        im = Image.frombuffer("RGB", (w, h), b, "raw", "RGB", 0, 1)
        im = im.resize((pw, ph), Image.Resampling.BILINEAR)      # 整幅缩放，不裁切
        im.save(out_dir / f"{i:03d}.jpg", quality=85)
        n = i + 1
    return n


def single_frame(video: Path, n25: int, out: Path, max_w: int = 640):
    """取第 n25 帧（按 25fps 计时）的缩略图，用于浏览整段视频（选起始帧）。直接 seek，快但只是近似：
    非 25fps 素材可能和生成实际用的帧差一帧；精确画面以时间轴预览帧（clip_previews）为准。"""
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".part.jpg")
    r = _run([ffmpeg_exe(), "-v", "error", "-y", "-ss", f"{n25 / 25:.4f}", "-i", str(video), "-frames:v", "1",
              "-vf", f"scale='min({max_w},iw)':-2", "-q:v", "4", str(tmp)])
    if r.returncode != 0 or not tmp.exists():
        raise FileNotFoundError("取不到这一帧：" + r.stderr.decode("utf-8", "replace")[-200:])
    tmp.replace(out)
    return out


def overlay(fx_video: Path, plate: Path, out: Path, blend: str = "screen", start25: int = 0,
            plate_is_image: bool = False, width: int | None = None, height: int | None = None):
    """把黑底特效叠加到参考画面上（滤色 screen / 相加 addition），输出 MP4（保留特效的音轨）。"""
    if blend not in ("screen", "addition"):
        raise ValueError("混合方式只支持 screen / addition")
    info = probe(fx_video)
    w, h = width or info["width"], height or info["height"]
    sc = f"scale={w}:{h}:flags=lanczos,setsar=1,format=gbrp"      # 整幅缩放，不裁切
    if plate_is_image:
        plate_in = ["-loop", "1", "-i", str(plate)]
        pf = f"[0:v]{sc}[p]"
    else:
        plate_in = ["-ss", str(start25 / 25), "-i", str(plate)]
        pf = f"[0:v]fps=fps=25,{sc}[p]"
    fc = f"{pf};[1:v]format=gbrp[f];[p][f]blend=all_mode={blend}:shortest=1,format=yuv420p[v]"
    args = [ffmpeg_exe(), "-v", "error", "-y"] + plate_in + ["-i", str(fx_video), "-filter_complex", fc,
            "-map", "[v]", "-map", "1:a?", "-c:v", "libx264", "-crf", "16", "-preset", "medium",
            "-c:a", "aac", "-shortest", "-r", "25", str(out)]
    r = _run(args)
    if r.returncode != 0:
        raise ValueError("合成导出失败：" + r.stderr.decode("utf-8", "replace")[-400:])
    return out


def read_frames_rgb(video: Path) -> np.ndarray:
    info = probe(video)
    w, h = info["width"], info["height"]
    r = _run([ffmpeg_exe(), "-v", "error", "-i", str(video), "-pix_fmt", "rgb24", "-f", "rawvideo", "-"])
    buf = np.frombuffer(r.stdout, dtype=np.uint8)
    n = buf.size // (w * h * 3)
    return buf[: n * w * h * 3].reshape(n, h, w, 3)
