"""外接翻译接口的协议测试：本机模拟三种上游（不联网、不需要真实密钥）。"""
import sys, os, json, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from fxstudio import llm, translate

KEY = "sk-test-0123456789"
LOG = []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        mode, _, rest = self.path.strip("/").partition("/")
        LOG.append((mode, "/" + rest, sorted(body.keys())))
        auth = self.headers.get("Authorization", "") + self.headers.get("x-api-key", "")
        if KEY not in auth:
            return self._send(401, {"error": "invalid api key"})
        if mode == "slow":
            time.sleep(8)
        system = body.get("system") or body.get("instructions") or next(
            (m["content"] for m in body.get("messages", []) if m["role"] == "system"), "")
        user = body.get("input") or next((m["content"] for m in body.get("messages", []) if m["role"] == "user"), "")
        terms = system.count(" = ")
        text = f"EN[{len(user)}chars,{terms}terms] thick black smoke billows upward."
        if rest == "v1/chat/completions" and mode in ("chat", "nothink", "slow"):
            if mode == "nothink" and "thinking" in body:
                return self._send(400, {"error": {"message": "Unrecognized request argument supplied: thinking"}})
            return self._send(200, {"choices": [{"message": {"content": text}, "finish_reason": "stop"}]})
        if rest == "v1/responses" and mode == "resp":
            return self._send(200, {"output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]})
        if rest == "v1/messages" and mode == "anth":
            return self._send(200, {"content": [{"type": "text", "text": text}], "stop_reason": "end_turn"})
        return self._send(404, {"error": "not found"})


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
B = f"http://127.0.0.1:{srv.server_address[1]}"
ZH = "浓密的黑烟从坦克上冲天而起，橙色火球爆开"
res = []


def case(name, ok, detail):
    res.append((name, ok)); print(("PASS " if ok else "FAIL ") + name, "|", detail)


def run(base, **kw):
    o = {"base_url": base, "api_key": KEY, "model": "mock-model", "proxy": "none"}
    o.update(kw)
    llm._wire_cache.clear(); LOG.clear()
    return translate.translate_text(ZH, overrides=o)


r = run(B + "/chat"); case("chat 协议（自动探测首选）", r["method"] == "api" and r["wire"] == "chat", r)
import re as _re; _m = _re.search(r",(\d+)terms", r["english"]); case("术语表随请求下发（命中的词带固定译法）", bool(_m) and int(_m.group(1)) >= 2, r.get("terms"))
case("翻译结果去掉句末句号", not r["english"].endswith("."), r["english"])
r = run(B + "/resp"); case("responses 协议（chat 404 后自动换）", r.get("wire") == "responses", [l[1] for l in LOG])
r = run(B + "/anth"); case("anthropic 协议（自动探测）", r.get("wire") == "anthropic", [l[1] for l in LOG])
r = run(B + "/anth", model="claude-x"); case("模型名含 claude 时先试 anthropic", LOG[0][1] == "/v1/messages", [l[1] for l in LOG])
r = run(B + "/chat/v1"); case("Base URL 带 /v1 也能用", r.get("wire") == "chat" and LOG[0][1] == "/v1/chat/completions", LOG[0])
r = run(B + "/nothink"); case("中转站拒绝 thinking 字段时去掉重试", r.get("wire") == "chat" and "thinking" in LOG[0][2] and "thinking" not in LOG[-1][2], [l[2] for l in LOG])
r = run(B + "/chat", wire="responses"); case("指定协议时只试这一种", r["method"] == "glossary-only" and [l[1] for l in LOG] == ["/v1/responses"], [l[1] for l in LOG])
r = run(B + "/chat", api_key="wrong"); case("密钥错误 → 中文提示 + 术语表兜底", r["method"] == "glossary-only" and "鉴权失败" in r["warning"] and "thick black smoke" in r["english"], r)
r = run(B + "/slow", timeout=5); case("超时 → 中文提示", r["method"] == "glossary-only" and "超时" in r["warning"], r["warning"])
r = run("http://127.0.0.1:9"); case("地址不通 → 中文提示", r["method"] == "glossary-only" and "连不上" in r["warning"], r["warning"])
r = translate.translate_text(ZH, overrides={"base_url": "", "model": ""})
case("未配置 → 提示去配置文件填写", r["method"] == "glossary-only" and llm.ENV_FILE.name in r["warning"] and "未配置" in r["warning"], r["warning"][:60])
case("密钥打码", llm.mask_key(KEY) == "sk-…6789", llm.mask_key(KEY))
r = translate.translate_text("already english text."); case("纯英文不调用接口", r["method"] == "unchanged", r)
print(f"共 {len(res)} 项，失败 {sum(1 for _, ok in res if not ok)}")
srv.shutdown()
