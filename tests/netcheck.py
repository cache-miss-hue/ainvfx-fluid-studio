"""监视应用进程树的网络连接：每 2 秒采样一次，记录任何非本机（非 127.0.0.1/::1）的远端连接。
用法：netcheck.py <应用端口> <秒数>"""
import sys, time, json
import psutil

port, dur = int(sys.argv[1]), float(sys.argv[2])
root = None
for c in psutil.net_connections("tcp"):
    if c.laddr and c.laddr.port == port and c.status == psutil.CONN_LISTEN:
        root = psutil.Process(c.pid)
if not root:
    sys.exit("找不到监听该端口的进程")
seen, samples = {}, 0
t0 = time.time()
while time.time() - t0 < dur:
    procs = [root] + root.children(recursive=True)
    for p in procs:
        try:
            for c in p.net_connections("inet"):
                if c.raddr and c.raddr.ip not in ("127.0.0.1", "::1", "0.0.0.0"):
                    seen[f"{p.name()}:{p.pid}->{c.raddr.ip}:{c.raddr.port}"] = c.status
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    samples += 1
    time.sleep(2)
print(json.dumps({"processes": [f"{p.name()}:{p.pid}" for p in [root] + root.children(recursive=True)],
                  "samples": samples, "external_connections": seen}, ensure_ascii=False))
