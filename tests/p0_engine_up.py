import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json, sys
from _engine_session import get_engine
from fxstudio import workflow
e = get_engine()
print("port", e.port, e.get("/system_stats")["system"]["comfyui_version"])
tpl = json.loads(workflow.TEMPLATE_PATH.read_text(encoding="utf-8")); tpl.pop("_说明")
missing = []
for k, n in tpl.items():
    try: e.object_info(n["class_type"])
    except Exception as ex: missing.append((k, n["class_type"], str(ex)[:80]))
print("missing nodes:", missing)
print("models:", json.dumps(workflow.resolve_models(e), ensure_ascii=False))
