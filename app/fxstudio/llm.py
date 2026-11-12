"""外接大模型接口（中文 → 英文翻译用），不占本地显存。

配置写在包根目录的 .env（每次调用都重新读取，改完不用重启）。可以在界面「翻译设置」里
填写并保存（save_config 写回 .env），也可以直接编辑 .env。兼容三种上游格式，
可指定也可自动探测（思路参考 G:\\统一中转绘图框架 的 unidraw/optimizer.py）：

    chat       POST {base}/v1/chat/completions   OpenAI Chat Completions（DeepSeek、绝大多数中转站）
    responses  POST {base}/v1/responses          OpenAI Responses
    anthropic  POST {base}/v1/messages           Anthropic Messages

- Base URL 填到 /v1 或不带 /v1 都行。
- 可关闭深度推理（DeepSeek 等推理模型实测 thinking=disabled 才真正不思考，更快更省）。
- 中转站拒绝可选字段（thinking/reasoning）时自动去掉重试。
- 密钥只从 .env 读取，不写日志、不回传前端（只给打码后的形式）。
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any

import httpx

from . import paths

ENV_FILE = Path(os.environ.get("FX_ENV_FILE") or (paths.ROOT / ".env"))   # FX_ENV_FILE 仅供测试指向别的配置文件
ENV_EXAMPLE = paths.ROOT / ".env.example"
PREFIX = "FX_TRANSLATE_"
DEFAULTS = {
    "BASE_URL": "", "API_KEY": "", "MODEL": "", "WIRE": "auto", "THINKING": "off",
    "TIMEOUT": "60", "TEMPERATURE": "0.2", "MAX_TOKENS": "1000", "PROXY": "",
}
WIRES = ("chat", "responses", "anthropic")
_wire_cache: dict[tuple, str] = {}


class LLMError(Exception):
    def __init__(self, msg: str, try_next: bool = False, status: int | None = None):
        super().__init__(msg)
        self.try_next = try_next
        self.status = status


# ---------------- 配置 ----------------
def read_env(path: Path = ENV_FILE) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[k.strip()] = v
    return out


def ensure_env_file():
    """首次运行：没有 .env 就从 .env.example 复制一份（分发包里从不带 .env，避免泄露密钥）。"""
    if not ENV_FILE.exists() and ENV_EXAMPLE.exists():
        ENV_FILE.write_text(ENV_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")


def config(overrides: dict | None = None) -> dict[str, Any]:
    env = read_env()
    c = {k.lower(): (env.get(PREFIX + k, d) or d) for k, d in DEFAULTS.items()}
    if overrides:
        # 空串也算有效覆盖（例如设置界面里“清空密钥后测试”）；只有 None 表示“不改这项”
        c.update({k: v for k, v in overrides.items() if v is not None})
    c["base_url"] = str(c["base_url"]).strip().rstrip("/")
    c["wire"] = c["wire"].strip().lower() if c["wire"].strip().lower() in WIRES else "auto"
    c["thinking"] = "auto" if str(c["thinking"]).strip().lower() == "auto" else "off"
    for k, f, lo, hi in (("timeout", float, 5, 600), ("temperature", float, 0, 2), ("max_tokens", int, 50, 32000)):
        try:
            c[k] = min(hi, max(lo, f(c[k])))
        except ValueError:
            c[k] = f(DEFAULTS[k.upper()])
    c["configured"] = bool(c["base_url"] and c["model"])
    return c


def mask_key(key: str) -> str:
    key = key or ""
    if not key:
        return ""
    return key[:3] + "…" + key[-4:] if len(key) > 10 else "…" * 3


def public_config() -> dict:
    c = config()
    return {"configured": c["configured"], "base_url": c["base_url"], "model": c["model"], "wire": c["wire"],
            "thinking": c["thinking"], "timeout": c["timeout"], "temperature": c["temperature"],
            "max_tokens": c["max_tokens"], "proxy": c["proxy"],
            "key": mask_key(c["api_key"]), "env_file": str(ENV_FILE), "env_exists": ENV_FILE.exists()}


# ---------------- 保存配置（设置界面 → .env） ----------------
def _clean_str(v: Any, name: str) -> str:
    s = str(v if v is not None else "").strip()
    if "\n" in s or "\r" in s:
        raise ValueError(f"{name}里不能包含换行")
    return s


def _num(s: str, f, lo, hi, name: str):
    try:
        v = f(s)
    except (TypeError, ValueError):
        raise ValueError(f"{name}要是数字") from None
    if not lo <= v <= hi:
        raise ValueError(f"{name}要在 {lo}–{hi} 之间")
    return v


def _host(url: str) -> str:
    try:
        return (urlsplit(str(url or "").strip()).hostname or "").lower()
    except ValueError:
        return ""


def key_follows(new_base_url, saved_base_url: str) -> bool:
    """已保存的密钥能否跟着用到 new_base_url 上：只认主机名（补 /v1、换端口不算换接口）。

    防止“只改接口地址、密钥沿用打码形式”就把已保存的密钥发到别的服务器（局域网模式下尤其要紧）。
    new_base_url 为 None 表示没改地址。
    """
    if new_base_url is None or not _host(saved_base_url):
        return True                                       # 没改地址，或密钥还没绑定到任何接口
    return _host(new_base_url) == _host(saved_base_url)


def save_config(values: dict) -> dict:
    """把设置界面提交的配置写回 .env：只改 FX_TRANSLATE_* 各项，保留注释和其他行。

    密钥约定：不传或仍为打码形式 = 沿用旧密钥；空串 = 删除密钥；其他 = 换成新密钥。
    例外：接口地址换到了另一台主机而密钥没有重新填写时，旧密钥作废（清空），需要重新填写。
    保存后立即生效（每次调用都重新读 .env），返回新的 public_config()。
    """
    if not isinstance(values, dict):
        raise ValueError("配置格式不正确")
    cur = config()
    out: dict[str, str] = {}
    for k in DEFAULTS:
        lk = k.lower()
        if lk not in values or values[lk] is None:
            continue
        if lk == "api_key":
            if str(values[lk]) == mask_key(cur["api_key"]):
                continue                                   # 打码形式原样传回 = 没改密钥
            out[PREFIX + k] = _clean_str(values[lk], "API Key")
            continue
        s = _clean_str(values[lk], lk)
        if lk == "base_url":
            s = s.rstrip("/")
            if s and not re.match(r"^https?://\S+$", s):
                raise ValueError("接口地址要以 http:// 或 https:// 开头（本机 Ollama 填 http://127.0.0.1:11434/v1）")
        elif lk == "wire":
            s = s.lower() or "auto"
            if s not in ("auto",) + WIRES:
                raise ValueError("接口格式只能是 auto / chat / responses / anthropic")
        elif lk == "thinking":
            s = s.lower() or "off"
            if s not in ("off", "auto"):
                raise ValueError("深度推理只能是 off（关闭）或 auto（按模型默认）")
        elif lk == "proxy":
            if s and s.lower() not in ("none", "direct", "off") and not re.match(r"^https?://\S+$", s):
                raise ValueError("代理要留空（跟随系统）、填 none（强制直连），或 http://127.0.0.1:7890 这样的地址")
        elif lk == "timeout":
            v = _num(s or DEFAULTS[k], float, 5, 600, "超时秒数")
            s = str(int(v)) if v.is_integer() else str(v)
        elif lk == "temperature":
            s = str(_num(s or DEFAULTS[k], float, 0, 2, "随机性"))
        elif lk == "max_tokens":
            s = str(_num(s or DEFAULTS[k], int, 50, 32000, "最大输出长度"))
        out[PREFIX + k] = s
    new_base = out.get(PREFIX + "BASE_URL")
    if ((PREFIX + "API_KEY") not in out and cur["api_key"] and new_base is not None
            and not key_follows(new_base, cur["base_url"])):
        out[PREFIX + "API_KEY"] = ""                     # 换了接口主机：旧密钥不跟过去
    if not out:
        return public_config()
    ensure_env_file()
    lines = ENV_FILE.read_text(encoding="utf-8-sig").splitlines() if ENV_FILE.exists() else []
    seen: set[str] = set()
    new_lines = []
    for line in lines:
        t = line.strip()
        if t and not t.startswith("#") and "=" in t:
            key = t.split("=", 1)[0].strip()
            if key in out:
                new_lines.append(f"{key}={out[key]}")
                seen.add(key)
                continue
        new_lines.append(line)
    for key, v in out.items():
        if key not in seen:
            new_lines.append(f"{key}={v}")
    tmp = ENV_FILE.with_name(ENV_FILE.name + ".tmp")
    tmp.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    tmp.replace(ENV_FILE)                                  # 原子替换，避免写一半被读到
    _wire_cache.clear()
    return public_config()


def resolve_overrides(values: dict) -> dict:
    """设置界面的表单值 → complete() 的 overrides：密钥仍为打码形式时沿用已保存的密钥。

    与 save_config 的密钥约定一致，让“测试”按钮不用先保存就能测当前表单。
    接口地址换到另一台主机时，打码密钥不再还原成真实密钥（按空密钥请求，需重新填写）。
    """
    cur = config()
    follows = key_follows(values.get("base_url"), cur["base_url"])
    o: dict = {}
    for k in DEFAULTS:
        lk = k.lower()
        if lk not in values or values[lk] is None:
            continue
        v = values[lk]
        if lk == "api_key" and str(v) == mask_key(cur["api_key"]):
            v = cur["api_key"] if follows else ""
        o[lk] = v
    if "api_key" not in o and not follows:
        o["api_key"] = ""                                # 没传密钥也不能把已存密钥带到别的主机
    return o


# ---------------- 请求 ----------------
def _endpoint(base: str, bare: str, versioned: str) -> str:
    return base + (bare if base.endswith("/v1") else versioned)


def _join(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join((b if isinstance(b, str) else str(b.get("text") or "")) for b in content
                       if isinstance(b, (str, dict)))
    return ""


def _extract(wire: str, data: Any) -> str:
    if not isinstance(data, dict):
        raise LLMError("上游返回的不是 JSON 对象", try_next=True)
    if wire == "chat":
        ch = data.get("choices")
        if isinstance(ch, list) and ch and isinstance(ch[0], dict):
            if ch[0].get("finish_reason") == "length":
                raise LLMError("模型输出被 max_tokens 截断，请在「翻译设置」里调大最大输出长度")
            t = _join((ch[0].get("message") or {}).get("content"))
            if t.strip():
                return t
        raise LLMError("Chat Completions 返回中没有 choices[0].message.content", try_next=True)
    if wire == "responses":
        t = data.get("output_text")
        if isinstance(t, str) and t.strip():
            return t
        parts = [str(b.get("text") or "") for it in (data.get("output") or []) if isinstance(it, dict)
                 for b in (it.get("content") or []) if isinstance(b, dict) and b.get("type") in ("output_text", "text")]
        if "".join(parts).strip():
            return "".join(parts)
        raise LLMError("Responses 返回中没有文本", try_next=True)
    if data.get("stop_reason") == "max_tokens":
        raise LLMError("模型输出被 max_tokens 截断，请在「翻译设置」里调大最大输出长度")
    parts = [str(b.get("text") or "") for b in (data.get("content") or []) if isinstance(b, dict) and b.get("type") == "text"]
    if "".join(parts).strip():
        return "".join(parts)
    raise LLMError("Anthropic Messages 返回中没有 text 内容", try_next=True)


def _raise_for_status(status: int, body: str, wire: str):
    snippet = " ".join(str(body or "").split())[:200]
    low = snippet.lower()
    if status in (401, 403):
        raise LLMError(f"鉴权失败 HTTP {status}：请在「翻译设置」里检查 API Key", status=status)
    if status == 402 or status == 429:
        raise LLMError(f"上游限流或余额不足 HTTP {status}。{snippet}", status=status)
    if status in (404, 405, 501) or (status in (400, 422) and any(
            t in low for t in ("not found", "unsupported", "invalid url", "no such", "not supported", "unknown request"))):
        raise LLMError(f"{wire} 接口不可用 HTTP {status}", try_next=True, status=status)
    raise LLMError(f"上游返回 HTTP {status}：{snippet}", status=status)


def _client_kw(c: dict, transport=None) -> dict:
    kw: dict = {"timeout": c["timeout"], "follow_redirects": True}
    proxy = str(c.get("proxy") or "").strip()
    if proxy.lower() in ("none", "direct", "off"):
        kw["trust_env"] = False                 # 直连，忽略系统代理
    elif proxy:
        kw["proxy"] = proxy
    if transport is not None:
        kw["transport"] = transport
    return kw


def _request(wire: str, c: dict, system: str, user: str, transport=None) -> str:
    base, key, model = c["base_url"], c["api_key"], c["model"]
    headers = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "AInVFX-Fluid-Studio"}
    if wire == "anthropic":
        url = _endpoint(base, "/messages", "/v1/messages")
        if key:
            headers["x-api-key"] = key
            headers["Authorization"] = f"Bearer {key}"
        headers["anthropic-version"] = "2023-06-01"
        payload: dict = {"model": model, "max_tokens": c["max_tokens"], "system": system,
                         "temperature": c["temperature"], "messages": [{"role": "user", "content": user}]}
    elif wire == "responses":
        url = _endpoint(base, "/responses", "/v1/responses")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        payload = {"model": model, "instructions": system, "input": user,
                   "temperature": c["temperature"], "max_output_tokens": c["max_tokens"]}
    else:
        url = _endpoint(base, "/chat/completions", "/v1/chat/completions")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        payload = {"model": model, "temperature": c["temperature"], "max_tokens": c["max_tokens"],
                   "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if c["thinking"] == "off":
        if wire == "responses":
            payload["reasoning"] = {"effort": "none"}
        else:
            payload["thinking"] = {"type": "disabled"}

    with httpx.Client(**_client_kw(c, transport)) as client:
        optional = [k for k in ("thinking", "reasoning") if k in payload]
        attempts = [payload]
        body = payload
        for name in optional:
            body = {k: v for k, v in body.items() if k != name}
            attempts.append(body)
        last: LLMError | None = None
        for body in attempts:
            r = client.post(url, headers=headers, json=body)
            if r.status_code == 200:
                try:
                    data = r.json()
                except ValueError:
                    raise LLMError(f"{wire} 返回的不是 JSON", try_next=True) from None
                return _extract(wire, data)
            try:
                _raise_for_status(r.status_code, r.text, wire)
            except LLMError as ex:
                if ex.status in (400, 422) and any(k in body for k in optional):
                    last = ex
                    continue
                raise
        raise last or LLMError("上游请求失败")


def complete(system: str, user: str, overrides: dict | None = None, transport=None) -> dict:
    """返回 {"ok", "text"|"error", "wire", "model", "elapsed"}；不抛异常。"""
    c = config(overrides)
    if not c["configured"]:
        return {"ok": False, "error": f"翻译接口未配置：请在界面「翻译设置」里填写接口地址和模型名（或直接编辑 {ENV_FILE.name}）"}
    order = [c["wire"]] if c["wire"] in WIRES else (
        ["anthropic", "chat", "responses"] if "claude" in c["model"].lower() else ["chat", "responses", "anthropic"])
    cached = _wire_cache.get((c["base_url"], c["model"]))
    if c["wire"] == "auto" and cached in order:
        order.remove(cached)
        order.insert(0, cached)
    t0 = time.time()
    tried = []
    for wire in order:
        try:
            text = _request(wire, c, system, user, transport)
        except LLMError as ex:
            tried.append(f"{wire}: {ex}")
            if ex.try_next:
                continue
            return {"ok": False, "error": str(ex), "wire": wire, "tried": tried, "elapsed": round(time.time() - t0, 2)}
        except httpx.TimeoutException:
            return {"ok": False, "error": f"翻译接口超时（{c['timeout']:.0f} 秒）", "wire": wire}
        except httpx.HTTPError as ex:
            return {"ok": False, "error": f"连不上翻译接口：{type(ex).__name__}（检查网络、接口地址，或在「翻译设置」里配置代理）", "wire": wire}
        _wire_cache[(c["base_url"], c["model"])] = wire
        return {"ok": True, "text": text, "wire": wire, "model": c["model"], "elapsed": round(time.time() - t0, 2)}
    return {"ok": False, "error": "所有接口格式都不可用：" + "；".join(tried), "tried": tried, "elapsed": round(time.time() - t0, 2)}


# ---------------- 拉取模型列表 ----------------
def _model_ids(data: Any) -> list[str]:
    """兼容 OpenAI / Anthropic 的 {"data":[{id}]}、Ollama 原生 {"models":[{name}]} 与裸数组。"""
    items = data.get("data") or data.get("models") if isinstance(data, dict) else data
    out: list[str] = []
    for it in items or []:
        if isinstance(it, str):
            mid = it
        elif isinstance(it, dict):
            mid = it.get("id") or it.get("name") or it.get("model")
        else:
            continue
        if isinstance(mid, str) and mid.strip():
            out.append(mid.strip())
    seen: set[str] = set()
    uniq = []
    for m in out:
        if m not in seen:
            seen.add(m)
            uniq.append(m)
    return sorted(uniq)


def list_models(overrides: dict | None = None, transport=None) -> dict:
    """GET {base}/v1/models 拉取可选模型，返回 {"ok", "models"|"error"}；不抛异常。

    同时带 Bearer 与 x-api-key 两种鉴权头，OpenAI 系与 Anthropic 系的 /models 都能用。
    """
    c = config(overrides)
    if not c["base_url"]:
        return {"ok": False, "error": "先填写接口地址（Base URL）再拉取模型"}
    url = _endpoint(c["base_url"], "/models", "/v1/models")
    headers = {"Accept": "application/json", "User-Agent": "AInVFX-Fluid-Studio", "anthropic-version": "2023-06-01"}
    if c["api_key"]:
        headers["Authorization"] = f"Bearer {c['api_key']}"
        headers["x-api-key"] = c["api_key"]
    try:
        with httpx.Client(**_client_kw(c, transport)) as client:
            r = client.get(url, headers=headers)
    except httpx.TimeoutException:
        return {"ok": False, "error": f"拉取模型超时（{c['timeout']:.0f} 秒）"}
    except httpx.HTTPError as ex:
        return {"ok": False, "error": f"连不上接口：{type(ex).__name__}（检查网络、接口地址，或在「翻译设置」里配置代理）"}
    if r.status_code != 200:
        try:
            _raise_for_status(r.status_code, r.text, "models")
        except LLMError as ex:
            return {"ok": False, "error": f"{ex}（该接口可能不支持 /models，请手动填模型名）"}
    try:
        data = r.json()
    except ValueError:
        return {"ok": False, "error": "接口返回的不是 JSON，可能不支持 /models，请手动填模型名"}
    ids = _model_ids(data)
    if not ids:
        return {"ok": False, "error": "接口没有返回模型列表，请手动填模型名"}
    return {"ok": True, "models": ids}
