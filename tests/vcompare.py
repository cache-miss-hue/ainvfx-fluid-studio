"""逐帧对比两段视频：PSNR / SSIM（灰度，高斯窗）/ 帧数 / 尺寸。用法：vcompare.py a.mp4 b.mp4 [json输出]"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import numpy as np
from scipy.ndimage import gaussian_filter
from fxstudio import video


def ssim(a, b):
    a = a.astype(np.float64); b = b.astype(np.float64)
    C1, C2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    mu_a, mu_b = gaussian_filter(a, 1.5), gaussian_filter(b, 1.5)
    saa = gaussian_filter(a * a, 1.5) - mu_a ** 2
    sbb = gaussian_filter(b * b, 1.5) - mu_b ** 2
    sab = gaussian_filter(a * b, 1.5) - mu_a * mu_b
    m = ((2 * mu_a * mu_b + C1) * (2 * sab + C2)) / ((mu_a ** 2 + mu_b ** 2 + C1) * (saa + sbb + C2))
    return float(m.mean())


def gray(f):
    return f[..., 0] * 0.299 + f[..., 1] * 0.587 + f[..., 2] * 0.114


def compare(pa, pb):
    A, B = video.read_frames_rgb(pa), video.read_frames_rgb(pb)
    res = {"frames": [int(A.shape[0]), int(B.shape[0])], "size": [list(A.shape[1:3]), list(B.shape[1:3])]}
    n = min(len(A), len(B))
    ps, ss = [], []
    for i in range(n):
        mse = np.mean((A[i].astype(np.float64) - B[i].astype(np.float64)) ** 2)
        ps.append(99.0 if mse == 0 else 10 * np.log10(255 ** 2 / mse))
        ss.append(ssim(gray(A[i]), gray(B[i])))
    res.update(psnr_mean=round(float(np.mean(ps)), 2), psnr_min=round(float(np.min(ps)), 2),
               ssim_mean=round(float(np.mean(ss)), 4), ssim_min=round(float(np.min(ss)), 4),
               psnr_first_mid_last=[round(ps[0], 2), round(ps[n // 2], 2), round(ps[-1], 2)])
    return res


if __name__ == "__main__":
    r = compare(sys.argv[1], sys.argv[2])
    print(json.dumps(r, ensure_ascii=False))
    if len(sys.argv) > 3:
        open(sys.argv[3], "w", encoding="utf-8").write(json.dumps(r, ensure_ascii=False, indent=1))
