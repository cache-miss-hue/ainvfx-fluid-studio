"""内嵌 ComfyUI 引擎：启动 / 停止子进程，HTTP + WebSocket 客户端。

- 只监听 127.0.0.1，自动选择空闲端口（不占 8188）。
- 客户端显式不走任何代理（本机可能设置了 HTTP_PROXY）。
- 引擎的 input/output/temp/user 目录都在 runtime/ 下。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from pathlib import Path

from . import paths

_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def free_port(preferred: int | None = None) -> int:
    if preferred:
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", preferred))
                return preferred
            except OSError:
                pass
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Engine:
    def __init__(self, port: int | None = None, extra_args: list[str] | None = None):
        self.port = port or free_port()
        self.extra_args = extra_args or []
        self.proc: subprocess.Popen | None = None
        self.client_id = uuid.uuid4().hex
        self.log_path = paths.LOG_DIR / "engine.log"
        self._lock = threading.Lock()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    # ---------- 进程 ----------
    def command(self) -> list[str]:
        rt = paths.RUNTIME_DIR / "engine"
        for sub in ("input", "output", "temp", "user"):
            (rt / sub).mkdir(parents=True, exist_ok=True)
        cmd = [str(paths.PYTHON_EXE), "-s", str(paths.COMFY_DIR / "main.py"),
               "--listen", "127.0.0.1", "--port", str(self.port),
               "--disable-auto-launch", "--offline",
               "--input-directory", str(rt / "input"),
               "--output-directory", str(rt / "output"),
               "--temp-directory", str(rt / "temp"),
               "--user-directory", str(rt / "user"),
               "--extra-model-paths-config", str(paths.ENGINE_DIR / "extra_paths.yaml")]
        if paths.DEV_MODEL_PATHS.exists() and os.environ.get("FX_NO_DEV_MODELS") != "1":
            cmd += ["--extra-model-paths-config", str(paths.DEV_MODEL_PATHS)]
        if _sage_available() and "--use-sage-attention" not in self.extra_args:
            cmd += ["--use-sage-attention"]        # 注意力加速（默认开启，见 _sage_available）
        return cmd + os.environ.get("FX_ENGINE_ARGS", "").split() + self.extra_args      # FX_ENGINE_ARGS：额外引擎参数（试验用）

    def start(self, wait: float = 180.0):
        paths.ensure_dirs()
        env = clean_env()
        # 上一次的日志改名保留（引擎崩溃或被看门狗重启时，现场就在 engine.prev.log 里）
        if self.log_path.exists():
            try:
                os.replace(self.log_path, self.log_path.with_name("engine.prev.log"))
            except OSError:
                pass
        self._logf = open(self.log_path, "w", encoding="utf-8", errors="replace")
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        self.proc = subprocess.Popen(self.command(), cwd=str(paths.COMFY_DIR), env=env,
                                     stdout=self._logf, stderr=subprocess.STDOUT, creationflags=flags)
        t0 = time.time()
        while time.time() - t0 < wait:
            if self.proc.poll() is not None:
                code = self.proc.returncode
                self._close_log()
                raise RuntimeError(f"引擎启动失败（退出码 {code}），详见 {self.log_path}")
            if self.alive():
                return
            time.sleep(0.5)
        self.stop()                                   # 超时没就绪：别留一个半启动的进程占显存
        raise RuntimeError(f"引擎 {wait:.0f} 秒内没有就绪，详见 {self.log_path}")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        self._close_log()

    def _close_log(self):
        f = getattr(self, "_logf", None)
        if f:
            try:
                f.close()
            except Exception:
                pass
            self._logf = None

    def exited(self) -> int | None:
        """引擎进程已退出则返回退出码，仍在运行（或还没启动）返回 None。"""
        if self.proc is None:
            return None
        return self.proc.poll()

    def alive(self) -> bool:
        try:
            self.get("/system_stats", timeout=2)
            return True
        except Exception:
            return False

    # ---------- HTTP ----------
    def get(self, path: str, timeout: float = 30):
        with _NO_PROXY.open(self.base + path, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def post(self, path: str, data: dict | None = None, timeout: float = 60):
        body = json.dumps(data or {}).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=body, headers={"Content-Type": "application/json"})
        try:
            with _NO_PROXY.open(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            raise EngineError(e.code, e.read().decode("utf-8", "replace")) from None

    def queue(self, prompt: dict) -> str:
        res = self.post("/prompt", {"prompt": prompt, "client_id": self.client_id})
        return res["prompt_id"]

    def interrupt(self):
        self.post("/interrupt", {})

    def delete_queued(self, prompt_id: str):
        """把还在排队、没开始执行的任务从引擎队列里移除（已开始的不受影响）。"""
        self.post("/queue", {"delete": [prompt_id]})

    def in_queue(self, prompt_id: str) -> bool:
        """任务是否还在引擎的执行中/排队列表里。"""
        q = self.get("/queue", timeout=5)
        for item in (q.get("queue_running") or []) + (q.get("queue_pending") or []):
            if len(item) > 1 and item[1] == prompt_id:
                return True
        return False

    def free(self, unload_models=True):
        self.post("/free", {"unload_models": unload_models, "free_memory": True})

    def history(self, prompt_id: str) -> dict:
        return self.get(f"/history/{prompt_id}").get(prompt_id, {})

    def object_info(self, node: str) -> dict:
        return self.get(f"/object_info/{node}")[node]

    def model_options(self, node: str, field: str) -> list[str]:
        spec = self.object_info(node)["input"]["required"][field]
        opts = spec[0] if isinstance(spec[0], list) else spec[1].get("options", [])
        return list(opts)

    def ws_events(self, stop: threading.Event):
        """生成器：逐条产出引擎 WebSocket 事件（dict）。二进制预览帧忽略。"""
        from websockets.sync.client import connect  # type: ignore
        url = f"ws://127.0.0.1:{self.port}/ws?clientId={self.client_id}"
        with connect(url, proxy=None, open_timeout=10, max_size=None) as ws:
            while not stop.is_set():
                try:
                    msg = ws.recv(timeout=1.0)
                except TimeoutError:
                    continue
                if isinstance(msg, str):
                    yield json.loads(msg)


class EngineError(Exception):
    def __init__(self, code, body):
        super().__init__(f"HTTP {code}: {body[:2000]}")
        self.code = code
        self.body = body


def _sage_available() -> bool:
    """引擎的 Python 里装了 sageattention 和 triton 就默认启用（只查有没有安装，不导入）；设环境变量 FX_SAGE=0 可关闭。
    注意：实测在本项目的 1024×576 / 49 帧下不提速（22 秒 vs 21–22 秒），且同一 seed 的结果与关闭时略有不同（PSNR 约 26 dB）。"""
    if os.environ.get("FX_SAGE") == "0":
        return False
    sp = paths.PYTHON_EXE.parent / "Lib" / "site-packages"
    return (sp / "sageattention").is_dir() and (sp / "triton").is_dir()


def clean_env() -> dict:
    """引擎子进程的环境：去掉 Python 相关变量与代理，强制离线。"""
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONUSERBASE",
                                "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "VIRTUAL_ENV", "CONDA_PREFIX")}
    env.update({"PYTHONUTF8": "1", "PYTHONNOUSERSITE": "1", "PYTHONIOENCODING": "utf-8",
                "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1",
                "DO_NOT_TRACK": "1", "NO_PROXY": "127.0.0.1,localhost"})
    return env
