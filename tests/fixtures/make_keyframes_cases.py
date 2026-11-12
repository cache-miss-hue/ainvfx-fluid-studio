"""生成 keyframes_cases.json：关键帧换算（吸附、尾帧、超出时长、同帧去重）的期望结果。
以后端 projects.resolved_keyframes 为准；前端 app/web/src/lib/keyframes.js 必须给出同样的结果
（app/web/tests/keyframes.test.mjs 与 tests/unit_backend_test.py 都读这份文件）。改了规则就重跑本脚本。"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "app"))
from fxstudio import projects, timeline

K = lambda i, idx, tail=False: ({"id": i, "index": idx, "tail": True} if tail else {"id": i, "index": idx})
cases = [
    ("首尾 5 秒", 5, True, [K("k_first", 0), K("k_tail", -1, True)]),
    ("每秒一帧 3 秒", 3, True, [K("k_first", 0), K("a", 25), K("b", 49), K("k_tail", -1, True)]),
    ("吸附到 8k+1", 5, True, [K("k_first", 0), K("a", 30), K("b", 36), K("c", 44)]),
    ("不吸附保持原位", 5, False, [K("k_first", 0), K("a", 30), K("b", 44)]),
    ("超出时长的被隐藏", 1, True, [K("k_first", 0), K("a", 30), K("k_tail", -1, True)]),
    ("吸附后撞到同一帧：只留一个", 5, True, [K("k_first", 0), K("a", 31), K("b", 35)]),
    ("与尾帧同帧：尾帧优先", 2, False, [K("k_first", 0), K("a", 48), K("k_tail", -1, True)]),
    ("吸附到 1", 5, True, [K("k_first", 0), K("a", 2)]),
    ("最后一个网格点靠近尾帧", 4, True, [K("k_first", 0), K("a", 95), K("k_tail", -1, True)]),
]
out = []
for name, secs, snap, kfs in cases:
    p = {"seconds": secs, "snap": snap, "keyframes": kfs}
    out.append({"name": name, "project": p, "timeline": {"seconds": secs, "last": timeline.last_index(secs),
                "grid": timeline.grid_positions(secs)}, "expected": projects.resolved_keyframes(p)})
f = os.path.join(os.path.dirname(os.path.abspath(__file__)), "keyframes_cases.json")
json.dump(out, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("wrote", len(out), "cases")
