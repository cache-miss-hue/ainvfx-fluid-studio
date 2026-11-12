"""把一次生成请求装配成引擎的 API 格式工作流。"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from . import paths

TEMPLATE_PATH = Path(__file__).with_name("workflow_template.json")

# 模板占位符 → manifest key
MODEL_SLOTS = {
    "$UNET": ("unet", "UNETLoader", "unet_name"),
    "$LORA": ("ic_lora", "LTXICLoRALoaderModelOnly", "lora_name"),
    "$VIDEO_VAE": ("video_vae", "VAELoader", "vae_name"),
    "$AUDIO_VAE": ("audio_vae", "VAELoader", "vae_name"),
    "$TEXT_ENCODER": ("text_encoder", "CLIPLoaderGGUF", "clip_name"),
}


def load_manifest() -> dict:
    return json.loads(paths.MANIFEST.read_text(encoding="utf-8"))


def resolve_models(engine) -> dict[str, str]:
    """按文件名在引擎的选项里找到对应条目（包内是扁平名，开发期可能带子目录）。"""
    man = {m["key"]: m for m in load_manifest()["models"]}
    out, missing = {}, []
    cache: dict[tuple, list] = {}
    for ph, (key, node, field) in MODEL_SLOTS.items():
        fname = Path(man[key]["path"]).name
        opts = cache.setdefault((node, field), engine.model_options(node, field))
        hit = [o for o in opts if o.replace("\\", "/").split("/")[-1] == fname]
        if not hit:
            missing.append(fname)
        else:
            hit.sort(key=len)
            out[ph] = hit[0]
    if missing:
        raise FileNotFoundError("引擎里找不到模型：" + "、".join(missing))
    return out


def build(job_dir: Path, prompt_text: str, seed: int, models: dict[str, str],
          lora_strength: float = 1.0, tile_size: int = 512, prefix: str = "fx",
          tail_idx: int | None = None, tail_strength: float = 0.4) -> dict:
    """tail_idx 不为 None 时用 LTXVAddGuide 把尾帧目标图钉在该帧；None 则去掉这个节点。"""
    tpl = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    tpl.pop("_说明", None)
    if tail_idx is None:
        del tpl["tailg"]
        for node in tpl.values():
            node["inputs"] = {k: (["guide", v[1]] if isinstance(v, list) and v[0] == "tailg" else v)
                              for k, v in node["inputs"].items()}
    values = dict(models)
    values.update({"$JOB_DIR": str(job_dir), "$PROMPT": prompt_text, "$SEED": int(seed),
                   "$LORA_STRENGTH": float(lora_strength), "$TILE_SIZE": int(tile_size),
                   "$PREFIX": prefix, "$TAIL_IDX": int(tail_idx or 0), "$TAIL_STRENGTH": float(tail_strength)})

    def fill(v):
        if isinstance(v, str) and v.startswith("$"):
            if v not in values:
                raise KeyError(f"模板占位符没有值：{v}")
            return values[v]
        return v

    wf = copy.deepcopy(tpl)
    for node in wf.values():
        node["inputs"] = {k: fill(v) for k, v in node["inputs"].items()}
    return wf
