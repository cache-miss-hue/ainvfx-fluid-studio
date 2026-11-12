"""打包脚本（开发者用）：生成可分发的软件包文件夹（可选再压成 zip）。

用法（在项目根目录）：
  engine\\python\\python.exe scripts\\pack.py --out D:\\dist                # 完整离线包（含模型）
  engine\\python\\python.exe scripts\\pack.py --out D:\\dist --no-models    # 不含模型的精简包
  可加 --zip 生成 zip（store 模式，ZIP64）；--yes 跳过确认（不推荐）。

流程：
  1. 打印模型清单并等待确认（不会自动开始）；
  2. 计算模型 SHA256 并回填 models.manifest.json（首次）；
  3. 复制程序文件；模型做“解引用复制”（读取真实内容，绝不复制链接本身）；
  4. 校验：每个模型比对大小与 SHA256；包内出现清单外的大文件会报警；
  5. 提醒模型再分发许可。
只读取开发目录与模型源文件，永不修改或删除源模型。
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "models.manifest.json"

INCLUDE = ["start.bat", "start_lan.bat", "docs/README-原始说明.txt", "models.manifest.json", ".env.example", "app", "engine", "tools", "licenses"]
EXCLUDE = [".env", "__pycache__", "*.pyc",   # .env 含个人密钥，绝不打包（对方首次启动时由 .env.example 生成）
           "app/web/node_modules", "app/web/src", "app/web/tests", "app/web/package*.json",
           "app/web/vite.config.*", "app/web/index.html", "engine/extra_model_paths.dev.yaml", "engine/build.log",
           "engine/_dl", "*.tmp"]
BIG = 200 * 1024 * 1024


def excluded(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    parts = rel.split("/")
    for pat in EXCLUDE:
        if "/" in pat:
            if rel == pat or rel.startswith(pat + "/") or fnmatch.fnmatch(rel, pat):
                return True
        elif any(fnmatch.fnmatch(p, pat) for p in parts):
            return True
    return False


def sha256(f: Path) -> str:
    h = hashlib.sha256()
    with open(f, "rb") as fh:
        while b := fh.read(32 * 1024 * 1024):
            h.update(b)
    return h.hexdigest()


def model_source(e: dict) -> Path | None:
    f = ROOT / "models" / e["path"]
    if f.exists():
        return f.resolve()          # 解析符号链接
    if e.get("dev_source") and Path(e["dev_source"]).exists():
        return Path(e["dev_source"])
    return None


def gb(n):
    return f"{n / 1024 ** 3:.2f} GB"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-models", action="store_true")
    ap.add_argument("--zip", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--skip-optional", action="store_true", help="不带可选模型")
    a = ap.parse_args()

    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    name = "AInVFX-Fluid-Studio" + ("-lite" if a.no_models else "")
    out = Path(a.out) / name
    if out.exists():
        sys.exit(f"目标已存在：{out}（请换目录或手动删除后再打包）")
    if not (ROOT / "app" / "web" / "dist" / "index.html").exists():
        sys.exit("前端尚未构建（app/web/dist 不存在），请先在 app/web 下 npm run build")

    print("=" * 70)
    print("模型清单（models.manifest.json）：")
    total = 0
    chosen = []
    for e in man["models"]:
        src = model_source(e)
        take = not a.no_models and (e["required"] or not a.skip_optional)
        flag = "带" if take else "不带"
        print(f"  [{flag}] {e['path']:<80} {gb(e['size']):>9}  必需={'是' if e['required'] else '否'}")
        print(f"         来源：{src or '!! 缺失'}")
        print(f"         许可：{e.get('license', '')}")
        if take:
            if src is None:
                sys.exit(f"缺少模型：{e['path']}")
            chosen.append((e, src))
            total += e["size"]
    print(f"  不打包：{', '.join(man.get('exclude', []))}")
    print(f"模型合计：{gb(total)}；输出：{out}{'（并压缩为 zip）' if a.zip else ''}")
    print("【提醒】再分发前请确认各模型许可允许转发（见 licenses/README-许可说明.txt）。")
    print("=" * 70)
    if not a.yes and input("确认开始打包？输入 y 回车继续：").strip().lower() != "y":
        sys.exit("已取消。")

    # 回填 SHA256
    changed = False
    for e, src in chosen:
        if not e.get("sha256"):
            print(f"计算 SHA256：{e['path']} …", flush=True)
            e["sha256"] = sha256(src)
            changed = True
    if changed:
        MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")

    t0 = time.time()
    out.mkdir(parents=True)
    n = 0
    for item in INCLUDE:
        src = ROOT / item
        if not src.exists():
            print(f"  （跳过不存在的 {item}）")
            continue
        if src.is_file():
            shutil.copy2(src, out / item)
            n += 1
            continue
        for dp, dns, fns in os.walk(src):
            reld = Path(dp).relative_to(ROOT).as_posix()
            dns[:] = [d for d in dns if not excluded(f"{reld}/{d}")]
            for fn in fns:
                rel = f"{reld}/{fn}"
                if excluded(rel):
                    continue
                dst = out / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(Path(dp) / fn, dst)    # copy2 跟随链接，复制真实内容
                n += 1
    for d in ("projects", "output", "models/diffusion_models", "models/text_encoders", "models/vae", "models/loras"):
        (out / d).mkdir(parents=True, exist_ok=True)
    print(f"程序文件 {n} 个，用时 {time.time() - t0:.0f}s")

    for e, src in chosen:
        dst = out / "models" / e["path"]
        print(f"复制模型（解引用）：{e['path']} …", flush=True)
        shutil.copyfile(src, dst)

    # 校验
    errors = []
    for e, _src in chosen:
        dst = out / "models" / e["path"]
        if dst.is_symlink():
            errors.append(f"{e['path']} 是链接（应为真实文件）")
        elif not dst.exists():
            errors.append(f"{e['path']} 缺失")
        elif dst.stat().st_size != e["size"]:
            errors.append(f"{e['path']} 大小不符")
        else:
            print(f"校验 SHA256：{e['path']} …", flush=True)
            if sha256(dst) != e["sha256"]:
                errors.append(f"{e['path']} SHA256 不一致")
    listed = {(out / "models" / e["path"]).resolve() for e in man["models"]}
    for dp, _, fns in os.walk(out):
        for fn in fns:
            f = Path(dp) / fn
            if f.stat().st_size > BIG and f.resolve() not in listed:
                rel = f.relative_to(out).as_posix()
                if not rel.startswith("engine/python/"):      # torch 的 CUDA 运行库本来就大
                    errors.append(f"清单外的大文件：{rel}（{gb(f.stat().st_size)}）")
    if errors:
        print("!! 校验发现问题：")
        for x in errors:
            print("   -", x)
        sys.exit(1)
    print("校验通过。")

    if a.zip:
        zf = out.with_suffix(".zip")
        print(f"压缩为 {zf} …", flush=True)
        with zipfile.ZipFile(zf, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
            for dp, _, fns in os.walk(out):
                for fn in fns:
                    f = Path(dp) / fn
                    z.write(f, Path(name) / f.relative_to(out))
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"完成：{out}（{gb(size)}），用时 {time.time() - t0:.0f}s")
    print("【提醒】再分发前请确认模型许可（licenses/README-许可说明.txt）。")


if __name__ == "__main__":
    main()
