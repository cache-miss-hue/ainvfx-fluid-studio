#!/usr/bin/env bash
# 一键构建 engine/ 与 tools/ffmpeg/：精简 Python + 固定版 ComfyUI + 节点包 + FFmpeg。
# 通常由根目录的 setup.bat 调用；可重复运行（已完成的步骤会跳过）。需要网络（可设 HTTPS_PROXY）。
# 不下载模型（模型由用户自行下载，见 README）。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENG="$ROOT/engine"; PY="$ENG/python"; FF="$ROOT/tools/ffmpeg"
SRC_COMFY="${SRC_COMFY:-}"   # 可选：本机已有 ComfyUI 仓库路径；留空则从 GitHub 获取
COMFY_REV=7a2833204; LTX_REV=220e1d4; GGUF_REV=b601643
mkdir -p "$ENG/_dl"

# 解压 zip（Git Bash 没有 unzip，用 Windows 自带的 PowerShell）
unzip_to() { # zip dest
  powershell -NoProfile -Command "Expand-Archive -LiteralPath '$(cygpath -w "$1")' -DestinationPath '$(cygpath -w "$2")' -Force"
}

echo "== [1/4] Python 3.12 嵌入版"
if [ ! -x "$PY/python.exe" ]; then
  curl -fL -o "$ENG/_dl/py.zip" https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip
  mkdir -p "$PY"; unzip_to "$ENG/_dl/py.zip" "$PY"
  # ._pth：隔离环境（embeddable 版本忽略 PYTHONPATH/PYTHONHOME），并启用 site-packages
  printf 'python312.zip\n.\nLib\\site-packages\n../ComfyUI\n../../app\nimport site\n' > "$PY/python312._pth"
  curl -fL -o "$ENG/_dl/get-pip.py" https://bootstrap.pypa.io/get-pip.py
  "$PY/python.exe" "$ENG/_dl/get-pip.py" --no-warn-script-location
fi

echo "== [2/4] Python 依赖（含 PyTorch CUDA 版，下载量较大，请耐心等待）"
"$PY/python.exe" -m pip install --no-warn-script-location \
  --extra-index-url https://download.pytorch.org/whl/cu130 \
  -r "$ENG/requirements.in" -c "$ENG/constraints.lock"

echo "== [3/4] ComfyUI 与节点包（固定版本）"
fetch_repo() { # url rev dst [local_src]
  local url="$1" rev="$2" dst="$3" src="${4:-}" tmp
  if [ -f "$dst/.revision" ] && [ "$(cat "$dst/.revision")" = "$rev" ]; then echo "  已是 $rev，跳过：$(basename "$dst")"; return; fi
  rm -rf "$dst"; mkdir -p "$dst"
  if [ -n "$src" ] && [ -d "$src/.git" ]; then git -C "$src" archive "$rev" | tar -x -C "$dst"
  else
    tmp="$ENG/_dl/$(basename "$dst").git"; rm -rf "$tmp"
    git clone --quiet --filter=blob:none --no-checkout "$url" "$tmp"
    git -C "$tmp" archive "$rev" | tar -x -C "$dst"
  fi
  echo "$rev" > "$dst/.revision"
}
fetch_repo https://github.com/comfyanonymous/ComfyUI.git $COMFY_REV "$ENG/ComfyUI" "$SRC_COMFY"
fetch_repo https://github.com/Lightricks/ComfyUI-LTXVideo.git $LTX_REV "$ENG/ComfyUI/custom_nodes/ComfyUI-LTXVideo" "${SRC_COMFY:+$SRC_COMFY/custom_nodes/ComfyUI-LTXVideo}"
fetch_repo https://github.com/molbal/ComfyUI-GGUF.git $GGUF_REV "$ENG/ComfyUI/custom_nodes/ComfyUI-GGUF" "${SRC_COMFY:+$SRC_COMFY/custom_nodes/ComfyUI-GGUF}"

echo "== [4/4] FFmpeg"
if [ ! -x "$FF/ffmpeg.exe" ] || [ ! -x "$FF/ffprobe.exe" ]; then
  curl -fL -o "$ENG/_dl/ffmpeg.zip" https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip
  unzip_to "$ENG/_dl/ffmpeg.zip" "$ENG/_dl/ffmpeg"
  mkdir -p "$FF"; cp "$ENG"/_dl/ffmpeg/*/bin/ffmpeg.exe "$ENG"/_dl/ffmpeg/*/bin/ffprobe.exe "$FF/"
fi

rm -rf "$ENG/_dl"
echo
echo "BUILD_OK  引擎与 FFmpeg 已就绪。下一步：把 5 个模型下载到 models/ 对应子目录（见 README），然后双击 start.bat。"
