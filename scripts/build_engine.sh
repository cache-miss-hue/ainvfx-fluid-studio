#!/usr/bin/env bash
# 开发者用：从零构建 engine/（精简 Python + 固定版 ComfyUI + 节点包）。使用者不需要运行。
# 需要网络（可设 HTTPS_PROXY）。只写入本项目的 engine/ 目录。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENG="$ROOT/engine"; PY="$ENG/python"
SRC_COMFY="${SRC_COMFY:-}"   # 可选：本机已有 ComfyUI 仓库路径；留空则从 GitHub 克隆
COMFY_REV=7a2833204; LTX_REV=220e1d4; GGUF_REV=b601643
mkdir -p "$ENG/_dl"
if [ ! -x "$PY/python.exe" ]; then
  curl -fL -o "$ENG/_dl/py.zip" https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip
  mkdir -p "$PY"; (cd "$PY" && unzip -q -o "$ENG/_dl/py.zip")
  # ._pth：隔离环境（embeddable 版本忽略 PYTHONPATH/PYTHONHOME），并启用 site-packages
  printf 'python312.zip\n.\nLib\site-packages\n../ComfyUI\n../../app\nimport site\n' > "$PY/python312._pth"
  curl -fL -o "$ENG/_dl/get-pip.py" https://bootstrap.pypa.io/get-pip.py
  "$PY/python.exe" "$ENG/_dl/get-pip.py" --no-warn-script-location
fi
"$PY/python.exe" -m pip install --no-warn-script-location \
  --extra-index-url https://download.pytorch.org/whl/cu130 \
  -r "$ENG/requirements.in" -c "$ENG/constraints.lock"
# ComfyUI 与节点包：按固定提交获取（git archive，不含 .git）
fetch_repo() { # url rev dst [local_src]
  local url="$1" rev="$2" dst="$3" src="${4:-}" tmp
  rm -rf "$dst"; mkdir -p "$dst"
  if [ -n "$src" ] && [ -d "$src/.git" ]; then git -C "$src" archive "$rev" | tar -x -C "$dst"
  else tmp="$ENG/_dl/$(basename "$dst").git"; rm -rf "$tmp"; git clone --quiet "$url" "$tmp"; git -C "$tmp" archive "$rev" | tar -x -C "$dst"; fi
  echo "$rev" > "$dst/.revision"
}
fetch_repo https://github.com/comfyanonymous/ComfyUI.git $COMFY_REV "$ENG/ComfyUI" "$SRC_COMFY"
fetch_repo https://github.com/Lightricks/ComfyUI-LTXVideo.git $LTX_REV "$ENG/ComfyUI/custom_nodes/ComfyUI-LTXVideo" "${SRC_COMFY:+$SRC_COMFY/custom_nodes/ComfyUI-LTXVideo}"
fetch_repo https://github.com/molbal/ComfyUI-GGUF.git $GGUF_REV "$ENG/ComfyUI/custom_nodes/ComfyUI-GGUF" "${SRC_COMFY:+$SRC_COMFY/custom_nodes/ComfyUI-GGUF}"
"$PY/python.exe" -m pip freeze > "$ENG/requirements.freeze.txt"
rm -rf "$ENG/_dl"
echo BUILD_OK
