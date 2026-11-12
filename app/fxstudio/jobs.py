"""任务队列：生成与翻译都排进同一个工作线程（共用一张显卡，严格串行）。"""
from __future__ import annotations

import json
import os
import queue
import shutil
import threading
import time
import traceback
import urllib.error
import uuid
from datetime import datetime
from pathlib import Path

from . import paths, projects, prompt as promptmod, workflow
from .engine import Engine, EngineError

STAGES = {
    "unet": "加载主模型", "lora": "加载 IC-LoRA", "vae": "加载 VAE", "avae": "加载 VAE", "te": "加载文本编码器",
    "ctrl": "读取控制帧", "pos": "编码提示词", "guide": "编码引导帧", "i2v": "准备潜空间", "aenc": "准备音轨",
    "sample": "采样", "vdec": "解码视频", "adec": "解码音轨", "out": "封装", "save": "保存",
}

OOM_MARKERS = ("out of memory", "outofmemory", "cuda error: out of memory", "allocation on device")


class Job:
    def __init__(self, kind: str, payload: dict):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.payload = payload
        self.state = "queued"          # queued / running / done / error / cancelled
        self.stage = "排队中"
        self.progress = 0.0            # 0..1（整体）
        self.step = None               # 采样步 "3/8"
        self.message = ""
        self.result: dict | None = None
        self.error: str | None = None
        self.created = time.time()
        self.started = None
        self.finished = None
        self.prompt_id: str | None = None
        self.notes: list[str] = []
        self.version = 0
        self.cancel_requested = False

    def touch(self):
        self.version += 1

    def snapshot(self) -> dict:
        return {k: getattr(self, k) for k in ("id", "kind", "state", "stage", "progress", "step", "message", "result",
                                              "error", "created", "started", "finished", "notes", "version")} | \
               {"project": self.payload.get("pid")}


class JobManager:
    def __init__(self):
        self.engine: Engine | None = None
        self.engine_state = "stopped"     # stopped / starting / ready / error
        self.engine_error = ""
        self.jobs: dict[str, Job] = {}
        self.q: "queue.Queue[Job]" = queue.Queue()
        self.models: dict | None = None
        self.models_loaded_once = False
        self._ws_stop = threading.Event()
        self._current: Job | None = None
        self.version = 0
        self._restart_lock = threading.Lock()     # 看门狗、崩溃自愈、手动重启共用：同一时刻只有一次重启
        self._bg_lock = threading.Lock()
        self._ws_started = False                  # 进度线程只启动一次（它每轮都读 self.engine，换引擎后自动跟上）
        self._monitor_started = False
        self._auto_restarts: list[float] = []
        self._worker = threading.Thread(target=self._loop, daemon=True)
        self._worker.start()

    # ---------- 引擎 ----------
    def start_engine(self):
        def run():
            with self._restart_lock:
                self.engine_state = "starting"
                self.version += 1
                try:
                    e = Engine()
                    e.start()
                    self.engine = e
                    try:
                        self.models = workflow.resolve_models(e)
                    except FileNotFoundError as ex:
                        self.engine_error = str(ex)
                    self.engine_state = "ready"
                except Exception as ex:
                    self.engine_state = "error"
                    self.engine_error = str(ex)
                self.version += 1
            self._ensure_background()
        threading.Thread(target=run, daemon=True).start()

    def _ensure_background(self):
        """进度线程与引擎看护线程各只启动一次。"""
        with self._bg_lock:
            if not self._ws_started:
                self._ws_started = True
                threading.Thread(target=self._ws_loop, daemon=True).start()
            if not self._monitor_started:
                self._monitor_started = True
                threading.Thread(target=self._monitor, daemon=True).start()

    AUTO_RESTART_LIMIT = 3        # 10 分钟内最多自动重启 3 次；再崩就停下等用户处理，避免无限重启
    AUTO_RESTART_WINDOW = 600

    def _monitor(self):
        """引擎进程意外退出（崩溃、被系统结束）时自动重启，不让之后每次生成都失败。"""
        while not self._ws_stop.wait(3.0):
            self._monitor_tick()

    def _monitor_tick(self):
        e = self.engine
        code = e.exited() if e else None
        if self.engine_state != "ready" or code is None:
            return
        now = time.time()
        self._auto_restarts = [t for t in self._auto_restarts if now - t < self.AUTO_RESTART_WINDOW]
        if len(self._auto_restarts) >= self.AUTO_RESTART_LIMIT:
            self.engine_state = "error"
            self.engine_error = (f"引擎 10 分钟内意外退出了 {len(self._auto_restarts) + 1} 次（最后一次退出码 {code}），"
                                 "已停止自动重启。日志在 runtime\\logs\\engine.log；处理后点顶栏“重启引擎”再试。")
            self.version += 1
            return
        self._auto_restarts.append(now)
        self.restart_engine(f"engine exited unexpectedly (code {code})")

    def manual_restart(self):
        """界面上的“重启引擎”：引擎出错、启动失败时用。后台进行，立即返回。"""
        if self._current is not None:
            raise ValueError("正在生成，不能重启引擎；请先取消当前任务")
        if self.engine_state == "starting":
            raise ValueError("引擎正在启动，请稍等")
        self._auto_restarts.clear()
        threading.Thread(target=self.restart_engine, args=("manual restart",), daemon=True).start()

    def free_vram(self):
        """卸载已加载的模型、释放显存（不关软件）。下次生成会重新加载模型。"""
        if self._current is not None:
            raise ValueError("正在生成，不能释放显存；请等生成结束或先取消")
        if self.engine_state != "ready" or not self.engine:
            raise ValueError("引擎没有就绪，没有可释放的显存")
        self.engine.free(unload_models=True)
        self.models_loaded_once = False
        self.version += 1

    def stop_engine(self):
        self._ws_stop.set()
        if self.engine:
            self.engine.stop()
        self.engine_state = "stopped"

    def _ws_loop(self):
        """把引擎的进度事件映射到当前任务。断线自动重连。"""
        while not self._ws_stop.is_set():
            try:
                for ev in self.engine.ws_events(self._ws_stop):
                    self._on_event(ev)
            except Exception:
                time.sleep(1.0)

    def _on_event(self, ev: dict):
        job = self._current
        if not job or not job.prompt_id:
            return
        t, d = ev.get("type"), ev.get("data", {}) or {}
        if d.get("prompt_id") and d.get("prompt_id") != job.prompt_id:
            return
        if t == "executing" and d.get("node"):
            node = str(d["node"]).split(":")[0]
            job.stage = STAGES.get(node, job.stage)
            if job.kind == "generate":
                order = ["unet", "lora", "vae", "te", "ctrl", "pos", "guide", "sample", "vdec", "adec", "out", "save"]
                if node in order and node != "sample":
                    base = {"sample": 0.15, "vdec": 0.85, "adec": 0.95, "out": 0.97, "save": 0.98}.get(node)
                    if base is None:
                        base = 0.02 + 0.13 * order.index(node) / 7
                    job.progress = max(job.progress, base)
            job.touch()
        elif t == "progress":
            node = str(d.get("node", "")).split(":")[0]
            v, m = d.get("value", 0), max(1, d.get("max", 1))
            if node == "sample":
                job.step = f"{v}/{m}"
                job.stage = "采样"
                job.progress = max(job.progress, 0.15 + 0.70 * v / m)
            elif node == "vdec":
                job.progress = max(job.progress, 0.85 + 0.10 * v / m)
            job.touch()

    # ---------- 提交 ----------
    def submit(self, kind: str, payload: dict) -> Job:
        job = Job(kind, payload)
        self.jobs[job.id] = job
        if kind == "translate":
            # 翻译走外接接口，不用显卡：立即在独立线程执行，不排在生成后面
            threading.Thread(target=self._run_translate, args=(job,), daemon=True).start()
        else:
            self.q.put(job)
        self.version += 1
        return job

    def cancel(self, jid: str):
        job = self.jobs.get(jid)
        if not job:
            raise KeyError(jid)
        job.cancel_requested = True
        if job.state == "queued":
            job.state, job.stage = "cancelled", "已取消"
        elif job.state == "running" and self.engine:
            try:
                self.engine.interrupt()
            except Exception:
                pass
        job.touch()

    def _loop(self):
        while True:
            job = self.q.get()
            if job.state == "cancelled":
                continue
            self._current = job
            job.state, job.started = "running", time.time()
            job.touch()
            try:
                self._wait_engine(job)
                if job.kind == "generate":
                    self._run_generate(job)
                elif job.kind == "test_block" and os.environ.get("FX_TEST_NODES") == "1":
                    # 仅测试看门狗/取消重启：提交一个不响应中断的阻塞节点
                    self._queue_and_wait(job, {"b": {"class_type": "FXTestBlock",
                                                     "inputs": {"seconds": int(job.payload.get("seconds", 300)),
                                                                "nonce": job.id}}})
                if job.cancel_requested:
                    job.state, job.stage = "cancelled", "已取消"
                else:
                    job.state, job.stage, job.progress = "done", "完成", 1.0
            except CancelledError:
                job.state, job.stage = "cancelled", "已取消"
                self._clean_after_cancel(job)
            except Exception as ex:
                job.state, job.stage = "error", "出错"
                job.error = friendly_error(ex)
                (paths.LOG_DIR / f"job_{job.id}.log").write_text(traceback.format_exc(), encoding="utf-8")
            job.finished = time.time()
            job.touch()
            self._current = None
            self.version += 1

    def _clean_after_cancel(self, job: Job):
        """取消后把引擎里的模型和中间结果卸掉：中断可能发生在加载/采样中途，残留的模型会占着显存，
        下一次生成就可能显存不足。代价是下次生成要重新加载模型。"""
        if job.kind != "generate" or not job.prompt_id or self.engine_state != "ready" or not self.engine:
            return
        try:
            self.engine.free(unload_models=True)
            self.models_loaded_once = False
        except Exception:
            pass

    def _wait_engine(self, job: Job):
        t0 = time.time()
        while self.engine_state in ("starting", "stopped"):
            if job.cancel_requested:
                raise CancelledError()
            if job.stage != "等待引擎启动":
                job.stage = "等待引擎启动"
                job.touch()
            if time.time() - t0 > 300:
                raise RuntimeError("引擎启动超时")
            time.sleep(0.5)
        if self.engine_state == "ready" and self.engine and self.engine.exited() is not None:
            job.stage = "引擎意外退出，正在重启"
            job.touch()
            self.restart_engine(f"engine found dead before job (code {self.engine.exited()})")
        if self.engine_state != "ready":
            raise UserError("引擎没有启动：" + (self.engine_error or "原因未知") +
                            "（可以点顶栏的“重启引擎”再试；日志在 runtime\\logs\\engine.log）")
        if self.models is None:
            self.models = workflow.resolve_models(self.engine)

    def restart_engine(self, reason: str):
        """引擎卡死、中断无效或意外退出时：结束进程并重启（显存随进程释放）。"""
        with self._restart_lock:
            with (paths.LOG_DIR / "engine_restarts.log").open("a", encoding="utf-8") as f:
                f.write(f"{datetime.now().isoformat()} {reason}\n")
            self.engine_state = "starting"
            self.version += 1
            try:
                old = self.engine
                if old:
                    old.stop()
                e = Engine()
                e.start()
                self.engine = e
                self.models = workflow.resolve_models(e)
                self.engine_state = "ready"
                self.engine_error = ""
            except Exception as ex:
                self.engine_state = "error"
                self.engine_error = str(ex)
            self.models_loaded_once = False
            self.version += 1
        self._ensure_background()

    STALL_SECONDS = int(os.environ.get("FX_STALL_SECONDS", "600"))   # 10 分钟没有任何进度事件 = 判定卡死（环境变量仅供测试）
    CANCEL_GRACE = 10            # 取消后 10 秒仍未停下 = 重启引擎
    INTERRUPT_EVERY = 2.0        # 取消后每 2 秒重发一次中断（引擎开始执行任务时会清掉此前收到的中断）

    def _queue_and_wait(self, job: Job, wf: dict, extra: dict | None = None) -> dict:
        if job.cancel_requested:                 # 还没交给引擎就取消了：直接结束，不必中断/重启引擎
            raise CancelledError()
        job.prompt_id = self.engine.queue(wf)
        last_version, last_change = job.version, time.time()
        cancel_at = last_interrupt = None
        while True:
            if job.version != last_version:
                last_version, last_change = job.version, time.time()
            if job.cancel_requested:
                now = time.time()
                if cancel_at is None:
                    cancel_at = now
                    try:
                        self.engine.delete_queued(job.prompt_id)   # 还在引擎队列里没开始：直接移出
                    except Exception:
                        pass
                if last_interrupt is None or now - last_interrupt >= self.INTERRUPT_EVERY:
                    last_interrupt = now
                    try:
                        self.engine.interrupt()
                    except Exception:
                        pass
                if now - cancel_at > self.CANCEL_GRACE:
                    job.stage = "正在重启引擎以停止任务"
                    job.touch()
                    self.restart_engine("cancel did not take effect")
                    raise CancelledError()
            elif time.time() - last_change > self.STALL_SECONDS:
                stalled_at = job.stage
                job.stage = "引擎无响应，正在重启"
                job.touch()
                self.restart_engine(f"stalled at stage {stalled_at}")
                raise UserError("引擎超过 10 分钟没有进展（多半是显存不足，被其他程序占用），已自动重启引擎。"
                                "请关闭占用显卡的程序（游戏、其他 AI 软件、硬件加速的浏览器标签）或降低输出尺寸后重试。")
            h = self.engine.history(job.prompt_id)
            st = h.get("status", {}) if h else {}
            if not h and cancel_at is not None:
                # 已从引擎队列移除、从未开始执行：不会有执行记录，直接按已取消结束
                try:
                    gone = not self.engine.in_queue(job.prompt_id)
                except Exception:
                    gone = False
                if gone:
                    raise CancelledError()
            if st.get("completed") is not None or st.get("status_str") in ("success", "error"):
                if st.get("status_str") == "error":
                    if job.cancel_requested:
                        raise CancelledError()
                    msgs = st.get("messages", [])
                    detail = ""
                    for m in msgs:
                        if m[0] == "execution_error":
                            detail = f'{m[1].get("exception_type", "")}: {m[1].get("exception_message", "")}'
                        if m[0] == "execution_interrupted":
                            raise CancelledError()
                    raise EngineRunError(detail or json.dumps(msgs, ensure_ascii=False)[:500])
                if job.cancel_requested:
                    raise CancelledError()
                return h
            time.sleep(0.4)

    # ---------- 生成 ----------
    def _run_generate(self, job: Job):
        pid = job.payload["pid"]
        p = projects.load(pid)
        job.stage = "准备控制帧"
        job.touch()
        warn = projects.check_video_length(p)
        if warn:
            raise UserError(warn)
        jdir = paths.JOBS_DIR / job.id
        info = projects.prepare_job(pid, jdir)
        if job.cancel_requested:
            shutil.rmtree(jdir, ignore_errors=True)
            raise CancelledError()
        if info["empty_keyframes"]:
            job.notes.append("这些关键帧没画任何东西（= 此刻无特效）：" +
                             "、".join(str(i) for i in info["empty_keyframes"]))
        final = p["prompt"].get("final") or promptmod.compose(
            {**p["prompt"]}, int(p["base_mode"]))
        final, notes = promptmod.normalize_final(final, int(p["base_mode"]))
        job.notes += [n for n in notes if "中文" not in n]
        if promptmod.has_chinese(final):
            raise UserError("提示词里还有中文：请先在右侧点“转英文”，确认英文稿后再生成。")
        if not self.models_loaded_once:
            job.message = "首次生成需要把约 30GB 模型读进内存，通常要多等 1–2 分钟。"
        seed = int(p["seed"])
        tile = int(p.get("tile_size", 512))
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = f"jobs/{job.id}/fx"
        for attempt in range(2):
            wf = workflow.build(jdir, final, seed, self.models, float(p.get("lora_strength", 1.0)), tile, prefix,
                                tail_idx=info["tail_idx"], tail_strength=float(p.get("tail_strength", 0.4)))
            (jdir / "api_prompt.json").write_text(json.dumps(wf, ensure_ascii=False, indent=1), encoding="utf-8")
            try:
                h = self._queue_and_wait(job, wf)
                break
            except EngineRunError as ex:
                if attempt == 0 and any(m in str(ex).lower() for m in OOM_MARKERS):
                    try:                                 # 先卸掉残留模型再重试（常见原因是上次取消留下的占用）
                        self.engine.free(unload_models=True)
                    except Exception:
                        pass
                    time.sleep(2)
                    tile = min(tile, 256)
                    job.notes.append("显存不足：已自动把解码分块降到 256 并重试。若仍不足，请降低输出尺寸。")
                    job.progress = 0.0
                    job.touch()
                    continue
                raise
        self.models_loaded_once = True
        out = h["outputs"]["save"]["images"][0]
        src = paths.RUNTIME_DIR / "engine" / "output" / out.get("subfolder", "") / out["filename"]
        dst_dir = paths.OUTPUT_DIR / pid
        dst_dir.mkdir(parents=True, exist_ok=True)
        name = f"{stamp}_seed{seed}"
        dst = dst_dir / f"{name}.mp4"
        shutil.move(str(src), dst)
        params = {"project": p["name"], "project_id": pid, "created": stamp, "seed": seed, "prompt": final,
                  "seconds": p["seconds"], "frames": info["frames"], "width": p["width"], "height": p["height"],
                  "base_mode": p["base_mode"], "keyframes": info["keyframes"], "lora_strength": p.get("lora_strength", 1.0),
                  "tile_size": tile, "reference": p.get("reference"), "blur_radius": p["blur_radius"],
                  "blur_sigma": p["blur_sigma"], "colors": p["colors"], "notes": job.notes,
                  "seconds_taken": round(time.time() - job.started, 1)}
        (dst_dir / f"{name}.json").write_text(json.dumps(params, ensure_ascii=False, indent=1), encoding="utf-8")
        shutil.rmtree(jdir, ignore_errors=True)
        job.result = {"file": f"{pid}/{name}.mp4", "params": params}

    # ---------- 翻译（外接接口，独立线程）----------
    def _run_translate(self, job: Job):
        from . import translate
        job.state, job.started, job.stage = "running", time.time(), "翻译中"
        job.touch()
        try:
            job.result = translate.translate_text(job.payload["text"])
            if job.cancel_requested:
                job.state, job.stage = "cancelled", "已取消"
            else:
                job.state, job.stage, job.progress = "done", "完成", 1.0
        except Exception as ex:
            job.state, job.stage, job.error = "error", "出错", friendly_error(ex)
            (paths.LOG_DIR / f"job_{job.id}.log").write_text(traceback.format_exc(), encoding="utf-8")
        job.finished = time.time()
        job.touch()
        self.version += 1


class CancelledError(Exception):
    pass


class EngineRunError(Exception):
    pass


class UserError(Exception):
    pass


def friendly_error(ex: Exception) -> str:
    s = str(ex)
    low = s.lower()
    if isinstance(ex, UserError):
        return s
    if isinstance(ex, (urllib.error.URLError, ConnectionError, TimeoutError)):
        return "连不上生成引擎（它可能刚刚意外退出）。软件会自动重启引擎，请等顶栏显示“引擎就绪”后重试。"
    if any(m in low for m in OOM_MARKERS):
        return "显存不足。请降低输出尺寸（如 768×448），或关闭其他占用显卡的程序后重试。"
    if isinstance(ex, FileNotFoundError):
        return "缺少文件：" + s
    if isinstance(ex, EngineError):
        return "引擎拒绝了这次请求（参数不合法）。详情已写入日志。"
    if isinstance(ex, EngineRunError):
        return "生成失败：" + s[:300]
    return s[:400] or ex.__class__.__name__
