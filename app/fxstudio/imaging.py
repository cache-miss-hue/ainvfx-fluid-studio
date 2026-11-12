"""底图制备：与 ComfyUI 的 ImageScale(lanczos, center) / ImageBlur / ImageQuantize(dither none) 逐步对齐。

实现直接移植自 ComfyUI 0.42.0 源码（comfy/utils.py common_upscale/lanczos，
comfy_extras/nodes_post_processing.py gaussian_kernel/Blur/Quantize），在 CPU 上运行，
以免应用进程占用显存。数值对齐由 tests/g3_align.py 验证（G3）。
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image


def snap64(v: int) -> int:
    return max(64, int(round(v / 64.0)) * 64)


PIXEL_BUDGET = 1024 * 576      # 输出面积预算（显存），与默认尺寸相同；比例按素材走，面积不随之放大


def fit_size(src_w: int, src_h: int, budget: int = PIXEL_BUDGET, lo: int = 256, hi: int = 2048) -> tuple[int, int]:
    """按素材宽高比选输出尺寸：64 的倍数、比例误差最小，同等比例下面积最接近预算（16:9→1024×576，4:3→896×672，
    1:1→768×768，9:16→576×1024，21:9→1344×576）。面积超过预算 1.4 倍的候选只在没有别的可选时才用。"""
    import math
    ar = src_w / src_h
    cands = []
    for w in range(lo, hi + 1, 64):
        k = math.floor(w / ar / 64 + 1e-6)
        for h in {max(lo, min(hi, k * 64)), max(lo, min(hi, (k + 1) * 64))}:
            cands.append((abs(math.log((w / h) / ar)), w * h, w, h))
    best = min(c[0] for c in cands)
    near = [c for c in cands if c[0] <= best + 0.004]
    ok = [c for c in near if c[1] <= budget * 1.4] or near
    _, _, w, h = min(ok, key=lambda c: abs(c[1] - budget))
    return w, h


def pil_to_tensor(img: Image.Image) -> torch.Tensor:
    """与 LoadImage 相同：转 RGB、/255、[1,H,W,3]。"""
    arr = np.array(img.convert("RGB")).astype(np.float32) / 255.0
    return torch.from_numpy(arr)[None]


def tensor_to_pil(t: torch.Tensor) -> Image.Image:
    arr = np.clip(255.0 * t[0].cpu().numpy(), 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def _lanczos(samples: torch.Tensor, width: int, height: int) -> torch.Tensor:
    samples = samples.movedim(1, -1)
    images = [Image.fromarray(np.clip(255.0 * im.cpu().numpy(), 0, 255).astype(np.uint8)) for im in samples]
    images = [im.resize((width, height), resample=Image.Resampling.LANCZOS) for im in images]
    images = [torch.from_numpy(np.array(im).astype(np.float32) / 255.0).movedim(-1, 0) for im in images]
    return torch.stack(images)


def scale_center_crop(image: torch.Tensor, width: int, height: int) -> torch.Tensor:
    """ImageScale(upscale_method=lanczos, crop=center)。image: [B,H,W,3]"""
    samples = image.movedim(-1, 1)
    old_width = samples.shape[-1]
    old_height = samples.shape[-2]
    old_aspect = old_width / old_height
    new_aspect = width / height
    x = y = 0
    if old_aspect > new_aspect:
        x = round((old_width - old_width * (new_aspect / old_aspect)) / 2)
    elif old_aspect < new_aspect:
        y = round((old_height - old_height * (old_aspect / new_aspect)) / 2)
    s = samples.narrow(-2, y, old_height - y * 2).narrow(-1, x, old_width - x * 2)
    return _lanczos(s, width, height).movedim(1, -1)


def scale_fit(image: torch.Tensor, width: int, height: int) -> torch.Tensor:
    """整幅 lanczos 缩放到 width×height，不裁切。输出尺寸由 fit_size 按素材比例选出，拉伸可忽略（<1%）。image: [B,H,W,3]"""
    return _lanczos(image.movedim(-1, 1), width, height).movedim(1, -1)


def _gaussian_kernel(kernel_size: int, sigma: float, dtype=torch.float32):
    x, y = torch.meshgrid(torch.linspace(-1, 1, kernel_size), torch.linspace(-1, 1, kernel_size), indexing="ij")
    d = torch.sqrt(x * x + y * y)
    g = torch.exp(-(d * d) / (2.0 * sigma * sigma))
    return (g / g.sum()).to(dtype)


def blur(image: torch.Tensor, blur_radius: int, sigma: float) -> torch.Tensor:
    if blur_radius == 0:
        return image
    b, h, w, c = image.shape
    ks = blur_radius * 2 + 1
    kernel = _gaussian_kernel(ks, sigma, dtype=image.dtype).repeat(c, 1, 1).unsqueeze(1)
    x = image.permute(0, 3, 1, 2)
    padded = F.pad(x, (blur_radius, blur_radius, blur_radius, blur_radius), "reflect")
    out = F.conv2d(padded, kernel, padding=ks // 2, groups=c)[:, :, blur_radius:-blur_radius, blur_radius:-blur_radius]
    return out.permute(0, 2, 3, 1)


def quantize(image: torch.Tensor, colors: int) -> torch.Tensor:
    rgb = image[..., :3]
    result = torch.zeros_like(rgb)
    for i in range(rgb.shape[0]):
        im = Image.fromarray((rgb[i] * 255).to(torch.uint8).numpy(), mode="RGB")
        pal_im = im.quantize(colors=colors)
        q = im.quantize(palette=pal_im, dither=Image.Dither.NONE).convert("RGB")
        result[i] = torch.from_numpy(np.array(q).astype(np.float32) / 255.0)
    return result


def make_base(ref: Image.Image | None, mode: int, width: int, height: int,
              blur_radius: int = 12, blur_sigma: float = 4.0, colors: int = 8) -> Image.Image:
    """底图模式 0 黑底 / 1 原图 / 2 色块化。返回精确输出尺寸的 RGB 图（uint8，与引擎侧一致）。"""
    if mode == 0 or ref is None:
        return Image.new("RGB", (width, height), (0, 0, 0))
    if isinstance(ref, np.ndarray):          # 视频帧：float32 [H,W,3]（16 位解码，与 VHS 一致）
        t = torch.from_numpy(np.ascontiguousarray(ref, dtype=np.float32))[None]
    else:
        t = pil_to_tensor(ref)
    t = scale_fit(t, width, height)
    if mode == 2:
        t = quantize(blur(t, int(blur_radius), float(blur_sigma)), int(colors))
    return tensor_to_pil(t)


def composite(base: Image.Image, strokes: Image.Image | None) -> Image.Image:
    """与 Painter 节点相同的 float 合成，仅用于预览与导出 PNG（生成时由引擎内私有节点做 float 合成）。"""
    if strokes is None:
        return base
    w, h = base.size
    s = strokes.convert("RGBA")
    if s.size != (w, h):
        s = s.resize((w, h), Image.LANCZOS)
    p = np.array(s).astype(np.float32) / 255.0
    b = np.array(base.convert("RGB")).astype(np.float32) / 255.0
    out = p[:, :, :3] * p[:, :, 3:4] + b * (1.0 - p[:, :, 3:4])
    return Image.fromarray(np.clip(255.0 * out, 0, 255).astype(np.uint8))
