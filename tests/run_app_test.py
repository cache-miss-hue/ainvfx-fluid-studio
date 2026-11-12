"""测试用：在指定端口启动应用服务 + 引擎（绕过单实例锁，供 e2e 使用）。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import uvicorn
from fxstudio.__main__ import _job_object_kill_on_close
from fxstudio.server import app, jm
_job_object_kill_on_close()
jm.start_engine()
try:
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
finally:
    jm.stop_engine()
