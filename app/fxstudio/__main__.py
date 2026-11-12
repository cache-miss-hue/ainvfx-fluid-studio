"""启动入口：python -m fxstudio [--port N] [--lan] [--no-browser]

- 应用服务默认只监听 127.0.0.1；--lan 才对局域网开放（引擎永远只在本机）。
- 引擎子进程挂在 Windows 作业对象上：本程序退出（含关窗口、崩溃）时引擎一并结束，不残留占显存。
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import socket
import sys
import threading
import time
import webbrowser

from . import paths


def _job_object_kill_on_close():
    """把当前进程放进“关闭即结束全部子进程”的作业对象；之后启动的子进程自动继承。"""
    if sys.platform != "win32":
        return
    k32 = ctypes.windll.kernel32

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

    class BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", ctypes.c_uint32), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_uint32),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_uint32), ("SchedulingClass", ctypes.c_uint32)]

    class EXT(ctypes.Structure):
        _fields_ = [("Basic", BASIC), ("Io", IO_COUNTERS), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k32.CreateJobObjectW.restype = ctypes.c_void_p
    job = k32.CreateJobObjectW(None, None)
    info = EXT()
    info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    k32.SetInformationJobObject(ctypes.c_void_p(job), 9, ctypes.byref(info), ctypes.sizeof(info))
    k32.AssignProcessToJobObject(ctypes.c_void_p(job), ctypes.c_void_p(k32.GetCurrentProcess()))
    globals()["_JOB_HANDLE"] = job   # 保持句柄存活


def _port_free(host, port):
    with socket.socket() as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _lan_addresses() -> list[str]:
    """本机的局域网 IPv4 地址：默认路由那块网卡排第一，其余（可能含 VPN/虚拟网卡）列在后面。"""
    found: list[str] = []
    try:   # UDP connect 不会真的发包，只是让系统选出默认出口网卡
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            found.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in found and not ip.startswith("127."):
                found.append(ip)
    except OSError:
        pass
    import ipaddress

    def rank(ip: str) -> int:   # 家用/办公局域网网段优先；198.18.x 这类多半是代理软件的虚拟网卡
        a = ipaddress.ip_address(ip)
        if ip.startswith("192.168."):
            return 0
        if a.is_private and not ip.startswith("169.254.") and not ip.startswith("198.18."):
            return 1
        return 2
    ips = [ip for ip in found if not ip.startswith("127.")]
    return sorted(ips, key=lambda ip: (rank(ip), ips.index(ip)))


_TOKEN_CHARS = "abcdefghjkmnpqrstuvwxyz23456789"     # 去掉了容易看错的 0/o、1/l/i


def lan_token() -> str:
    """局域网访问口令：第一次生成后存在 runtime/lan_token.txt，以后沿用（平板不用每次重新输入）。"""
    import secrets
    f = paths.RUNTIME_DIR / "lan_token.txt"
    try:
        t = f.read_text(encoding="utf-8").strip().lower()
        if len(t) >= 6 and all(c in _TOKEN_CHARS for c in t):
            return t
    except OSError:
        pass
    t = "".join(secrets.choice(_TOKEN_CHARS) for _ in range(8))
    f.write_text(t, encoding="utf-8")
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--lan", action="store_true", help="允许局域网内的其他设备（如平板）访问应用界面")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    paths.ensure_dirs()
    lock = paths.RUNTIME_DIR / "app.json"
    if lock.exists():
        try:
            old = json.loads(lock.read_text(encoding="utf-8"))
            import urllib.request
            op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            op.open(f"http://127.0.0.1:{old['port']}/api/status", timeout=2)
            print("软件已经在运行，正在打开浏览器……")
            if not args.no_browser:
                webbrowser.open(f"http://127.0.0.1:{old['port']}/")
            return
        except Exception:
            pass

    _job_object_kill_on_close()
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    port = args.port or next(p for p in [7860, 7861, 7862, 7870, 7880, 7890] + list(range(17860, 17900))
                             if _port_free(host, p))
    lock.write_text(json.dumps({"port": port, "pid": os.getpid()}), encoding="utf-8")

    import uvicorn
    from . import server
    from .server import app, jm

    server.LOCAL_ONLY = not args.lan
    lan_ips: list[str] = []
    if args.lan:
        server.LAN_TOKEN = lan_token()
        lan_ips = _lan_addresses()
        server.LAN_URLS = [f"http://{ip}:{port}/?k={server.LAN_TOKEN}" for ip in lan_ips]
    try:
        from . import projects
        projects.cleanup_runtime()
    except Exception as ex:     # 清理失败不影响启动
        print("  （启动清理跳过：", ex, "）")

    if os.environ.get("FX_NO_ENGINE") != "1":   # 前端开发时可不启动引擎
        jm.start_engine()
    url = f"http://127.0.0.1:{port}/"

    def opener():
        import urllib.request
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(100):
            try:
                op.open(url + "api/status", timeout=1)
                break
            except Exception:
                time.sleep(0.2)
        print(f"\n  AInVFX Fluid Studio 已启动：{url}")
        if args.lan:
            if server.LAN_URLS:
                print(f"  局域网访问地址（平板打开这个，已带口令）：{server.LAN_URLS[0]}")
                for u in server.LAN_URLS[1:]:
                    print(f"      （打不开就试试：{u}）")
            else:
                print("  没找到局域网地址：请确认电脑已连上 Wi-Fi 或网线。")
            print(f"  访问口令：{server.LAN_TOKEN}   （平板记住后一年内不用再输；想换口令就删掉 runtime\\lan_token.txt 再启动）")
            print("  电脑界面顶栏的“平板访问”里也能看到地址和口令。")
            print("  首次使用时 Windows 防火墙可能会询问，请允许“专用网络”访问。")
        print("  关闭本窗口即退出软件。\n")
        if not args.no_browser:
            webbrowser.open(url)

    threading.Thread(target=opener, daemon=True).start()
    try:
        uvicorn.run(app, host=host, port=port, log_level="warning", access_log=False)
    finally:
        jm.stop_engine()
        try:
            lock.unlink()
        except Exception:
            pass


if __name__ == "__main__":
    main()
