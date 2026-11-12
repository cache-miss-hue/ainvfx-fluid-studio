"""翻译设置（界面 → .env）的保存/打码/校验与 HTTP 接口测试。不联网（本机模拟上游）、不碰真实 .env。"""
import sys, os, json, shutil, tempfile, threading
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
TMP = tempfile.mkdtemp(prefix="fx_cfg_test_")
os.environ["FX_ENV_FILE"] = os.path.join(TMP, ".env")   # 必须在 import llm 之前设置
from fxstudio import llm

res = []


def case(name, ok, detail=""):
    res.append((name, ok)); print(("PASS " if ok else "FAIL ") + name, "|", detail)


ENV = llm.ENV_FILE
KEY = "sk-test-0123456789"
SEED = """# 注释保留测试
FX_TRANSLATE_BASE_URL=
FX_TRANSLATE_API_KEY=sk-test-0123456789
FX_TRANSLATE_MODEL=
OTHER_KEY=keepme
# FX_TRANSLATE_MODEL=注释里的假键
"""
ENV.write_text(SEED, encoding="utf-8")

# ---------------- 保存与写回 ----------------
c = llm.save_config({"base_url": "https://api.deepseek.com/", "model": "deepseek-chat", "wire": "chat"})
env = llm.read_env()
case("保存写回 .env（地址去掉末尾斜杠）", env["FX_TRANSLATE_BASE_URL"] == "https://api.deepseek.com" and env["FX_TRANSLATE_MODEL"] == "deepseek-chat", env)
text = ENV.read_text(encoding="utf-8")
case("注释与其他键保留", "# 注释保留测试" in text and "OTHER_KEY=keepme" in text and "# FX_TRANSLATE_MODEL=注释里的假键" in text, text)
case("未提交的密钥不动", env["FX_TRANSLATE_API_KEY"] == KEY, env["FX_TRANSLATE_API_KEY"])
case("返回打码密钥与配置状态", c["key"] == "sk-…6789" and c["configured"], c)
case("没有残留临时文件", not ENV.with_name(ENV.name + ".tmp").exists())
case("公开配置带高级选项", all(k in c for k in ("timeout", "temperature", "max_tokens", "proxy")), sorted(c))

# ---------------- 密钥约定 ----------------
llm.save_config({"api_key": llm.mask_key(KEY)})
case("打码形式传回 = 沿用旧密钥", llm.read_env()["FX_TRANSLATE_API_KEY"] == KEY)
llm.save_config({"api_key": "sk-new-9876543210"})
case("填新密钥 = 更换", llm.read_env()["FX_TRANSLATE_API_KEY"] == "sk-new-9876543210")
llm.save_config({"api_key": ""})
case("清空 = 删除密钥", llm.read_env()["FX_TRANSLATE_API_KEY"] == "")


# ---------------- 校验（失败时文件不能被改动） ----------------
def bad(name, values):
    before = ENV.read_text(encoding="utf-8")
    try:
        llm.save_config(values)
        ok = False
    except ValueError:
        ok = ENV.read_text(encoding="utf-8") == before
    case(name, ok)


bad("非法接口格式被拒绝", {"wire": "grpc"})
bad("接口地址缺协议被拒绝", {"base_url": "api.deepseek.com"})
bad("超时越界被拒绝", {"timeout": 9999})
bad("随机性越界被拒绝", {"temperature": 3})
bad("最大输出长度越界被拒绝", {"max_tokens": 10})
bad("代理格式被拒绝", {"proxy": "127.0.0.1:7890"})
bad("换行被拒绝", {"model": "a\nb"})

llm.save_config({"timeout": "", "temperature": "", "max_tokens": ""})
env = llm.read_env()
case("数字留空 = 恢复默认", env["FX_TRANSLATE_TIMEOUT"] == "60" and env["FX_TRANSLATE_TEMPERATURE"] == "0.2" and env["FX_TRANSLATE_MAX_TOKENS"] == "1000", env)

ENV.write_text("# 只有注释\n", encoding="utf-8")
llm.save_config({"base_url": "http://127.0.0.1:11434/v1", "model": "qwen2.5:7b"})
env = llm.read_env()
case("缺少的键自动补上", env["FX_TRANSLATE_BASE_URL"] == "http://127.0.0.1:11434/v1" and env["FX_TRANSLATE_MODEL"] == "qwen2.5:7b", env)

# ---------------- 测试按钮的覆盖值解析 ----------------
llm.save_config({"api_key": KEY})
o = llm.resolve_overrides({"api_key": llm.mask_key(KEY), "model": "m", "base_url": None})
case("覆盖值：打码密钥还原成真实密钥", o["api_key"] == KEY and "base_url" not in o, o)
o = llm.resolve_overrides({"api_key": ""})
case("覆盖值：清空密钥按空串传", o["api_key"] == "", o)
case("空串覆盖可清空配置（未配置判定）", not llm.config({"base_url": "", "model": ""})["configured"])

# ---------------- 模型列表解析 ----------------
case("解析 OpenAI data[].id", llm._model_ids({"data": [{"id": "b"}, {"id": "a"}]}) == ["a", "b"])
case("解析 Ollama models[].name", llm._model_ids({"models": [{"name": "qwen2.5:7b"}]}) == ["qwen2.5:7b"])
case("解析裸数组与去重", llm._model_ids(["x", "x", "y"]) == ["x", "y"])
case("空返回解析为空", llm._model_ids({"data": []}) == [] and llm._model_ids(None) == [])

# ---------------- HTTP 接口（本机模拟上游） ----------------
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            auth = self.headers.get("Authorization", "") + self.headers.get("x-api-key", "")
            if KEY not in auth:
                return self._send(401, {"error": "bad key"})
            return self._send(200, {"data": [{"id": "mock-model-v2"}, {"id": "mock-model"}, {"id": "other"}]})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if KEY not in self.headers.get("Authorization", ""):
            return self._send(401, {"error": "bad key"})
        return self._send(200, {"choices": [{"message": {"content": "Thick black smoke billows upward"}, "finish_reason": "stop"}]})


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
B = f"http://127.0.0.1:{srv.server_address[1]}"

from fastapi.testclient import TestClient
from fxstudio.server import app
client = TestClient(app)

r = client.get("/api/translate/config")
case("GET 配置接口（密钥打码）", r.status_code == 200 and r.json()["key"] == llm.mask_key(KEY), r.text)
r = client.put("/api/translate/config", json={"base_url": B, "model": "mock-model", "wire": "chat", "proxy": "none"})
case("PUT 保存接口", r.status_code == 200 and r.json()["configured"], r.text)
r = client.put("/api/translate/config", json={"wire": "grpc"})
case("PUT 校验失败返回 400 中文信息", r.status_code == 400 and "接口格式" in r.json()["detail"], r.text)
r = client.post("/api/translate/test", json={"text": "浓烟从坦克上冲天而起", "config": {"api_key": llm.mask_key(KEY)}})
j = r.json()
case("POST 测试：打码密钥自动沿用已保存的", j.get("method") == "api" and j.get("wire") == "chat", j)
r = client.post("/api/translate/test", json={"text": "浓烟", "config": {"base_url": B, "api_key": "wrong", "model": "mock-model", "proxy": "none"}})
j = r.json()
case("POST 测试：表单覆盖值生效（错密钥→鉴权失败兜底）", j.get("method") == "glossary-only" and "鉴权失败" in j.get("warning", ""), j)

r = client.post("/api/translate/models", json={"config": {"api_key": llm.mask_key(KEY)}})
j = r.json()
case("POST 拉取模型：打码密钥沿用已保存的", j.get("ok") and j.get("models") == ["mock-model", "mock-model-v2", "other"], j)
r = client.post("/api/translate/models", json={"config": {"base_url": B, "api_key": "wrong", "proxy": "none"}})
j = r.json()
case("POST 拉取模型：错密钥返回中文错误", not j.get("ok") and "鉴权失败" in j.get("error", ""), j)
r = client.post("/api/translate/models", json={"config": {"base_url": ""}})
j = r.json()
case("POST 拉取模型：没填地址先提示", not j.get("ok") and "接口地址" in j.get("error", ""), j)
j = llm.list_models({"base_url": B, "api_key": KEY, "proxy": "none"})
case("llm.list_models 直连可用", j.get("ok") and "mock-model" in j.get("models", []), j)

srv.shutdown()
shutil.rmtree(TMP, ignore_errors=True)
fails = sum(1 for _, ok in res if not ok)
print(f"共 {len(res)} 项，失败 {fails}")
sys.exit(1 if fails else 0)