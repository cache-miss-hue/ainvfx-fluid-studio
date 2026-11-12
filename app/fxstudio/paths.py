"""所有路径都从包根目录推导，不写死任何盘符，支持中文和空格路径。"""
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent          # <root>/app
ROOT = APP_DIR.parent                                      # <root>
ENGINE_DIR = ROOT / "engine"
PYTHON_EXE = ENGINE_DIR / "python" / "python.exe"
COMFY_DIR = ENGINE_DIR / "ComfyUI"
ENGINE_NODES_DIR = APP_DIR / "engine_nodes"
MODELS_DIR = ROOT / "models"
PROJECTS_DIR = ROOT / "projects"
OUTPUT_DIR = ROOT / "output"
RUNTIME_DIR = ROOT / "runtime"            # 引擎的 input/output/temp/user 目录、日志、临时任务
LOG_DIR = RUNTIME_DIR / "logs"
JOBS_DIR = RUNTIME_DIR / "jobs"
CACHE_DIR = RUNTIME_DIR / "cache"
WEB_DIST = APP_DIR / "web" / "dist"
MANIFEST = ROOT / "models.manifest.json"
DEV_MODEL_PATHS = ENGINE_DIR / "extra_model_paths.dev.yaml"
TOOLS_DIR = ROOT / "tools"
FFMPEG = TOOLS_DIR / "ffmpeg" / "ffmpeg.exe"
FFPROBE = TOOLS_DIR / "ffmpeg" / "ffprobe.exe"


def ensure_dirs():
    for d in (PROJECTS_DIR, OUTPUT_DIR, RUNTIME_DIR, LOG_DIR, JOBS_DIR, CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True)
