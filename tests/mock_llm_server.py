"""测试用：模拟 OpenAI 兼容翻译接口（只用于界面联调）。用法：mock_llm_server.py <端口>"""
import sys, json, re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
TABLE = {"雪地上一辆白色坦克，晴朗的蓝天": "a white tank on snowy ground under a clear blue sky"}
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        user = next(m["content"] for m in body["messages"] if m["role"] == "user")
        out = TABLE.get(user, "mock translation of: " + re.sub(r"[^\x00-\x7f]", "", user))
        b = json.dumps({"choices": [{"message": {"content": out}, "finish_reason": "stop"}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
