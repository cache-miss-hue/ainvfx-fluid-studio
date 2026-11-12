"""提示词：结构化表单 → 英文提示词；术语表；最终稿规则检查。中文 → 英文见 translate.py（外接接口）。"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import paths

PREFIX = "ainvfxfluid"
BLACK_BG = "against a black background"
NOTHING_ELSE = "nothing else in sight"

# 特效类型：下拉选项 → 内置英文短语（贴合 ainvfx-fluid LoRA 的说法，来自原使用说明示例）
EFFECTS = [
    {"id": "explosion", "zh": "爆炸火球", "en": "an orange fireball explosion bursts and thick black smoke billows upward"},
    {"id": "fire", "zh": "火焰", "en": "orange and yellow flames burn and flicker"},
    {"id": "black_smoke", "zh": "浓烟", "en": "thick black smoke billows upward"},
    {"id": "smoke", "zh": "轻烟", "en": "light gray smoke drifts upward"},
    {"id": "steam", "zh": "蒸汽", "en": "white steam rises and swirls"},
    {"id": "water", "zh": "水", "en": "light blue water splashes and flows"},
    {"id": "dust", "zh": "尘土", "en": "a cloud of dust kicks up and spreads"},
    {"id": "fog", "zh": "雾", "en": "soft white fog rolls slowly"},
    {"id": "cloud", "zh": "云", "en": "white clouds billow and drift"},
    {"id": "custom", "zh": "自定义（只用下面的描述）", "en": ""},
]

GLOSSARY_FILE = Path(__file__).with_name("glossary.json")
USER_GLOSSARY = paths.ROOT / "projects" / "glossary.user.json"

CJK = re.compile(r"[㐀-鿿豈-﫿　-〿＀-￯]")


def has_chinese(s: str) -> bool:
    return bool(CJK.search(s or ""))


def load_glossary() -> dict[str, str]:
    g = json.loads(GLOSSARY_FILE.read_text(encoding="utf-8"))
    if USER_GLOSSARY.exists():
        try:
            g.update(json.loads(USER_GLOSSARY.read_text(encoding="utf-8")))
        except Exception:
            pass
    return g


def save_user_glossary(entries: dict[str, str]):
    USER_GLOSSARY.parent.mkdir(parents=True, exist_ok=True)
    USER_GLOSSARY.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")


def apply_glossary(text: str, glossary: dict[str, str] | None = None) -> str:
    """长词优先，把术语替换成固定英文说法（两侧补空格，交给模型翻译剩余部分）。"""
    glossary = glossary or load_glossary()
    for zh in sorted(glossary, key=len, reverse=True):
        if zh and zh in text:
            text = text.replace(zh, f" {glossary[zh]} ")
    return re.sub(r"\s+", " ", text).strip()


def compose(form: dict, base_mode: int) -> str:
    """form: scene_en, effect, effect_desc_en, camera, nothing_else。已是英文的字段。"""
    parts = [PREFIX]
    scene = (form.get("scene_en") or "").strip().strip(",")
    if base_mode != 0 and scene:
        parts.append(scene)
    eff = next((e for e in EFFECTS if e["id"] == form.get("effect")), None)
    desc = (form.get("effect_desc_en") or "").strip().strip(",")
    if desc:
        parts.append(desc)
    elif eff and eff["en"]:
        parts.append(eff["en"])
    if base_mode == 0:
        parts.append(BLACK_BG)
    cam = (form.get("camera") or "static camera").strip()
    if cam:
        parts.append(cam)
    if form.get("nothing_else", True):
        parts.append(NOTHING_ELSE)
    return ", ".join(_tidy(p) for p in parts if p)


def _tidy(s: str) -> str:
    """拼接时去掉句末标点；句首大写（非专有缩写）改小写，让各段读起来是一句提示词。"""
    s = s.strip().rstrip(".。,，;；").strip()
    if len(s) > 1 and s[0].isupper() and (s[1].islower() or s[1] == " "):
        s = s[0].lower() + s[1:]
    return s


def normalize_final(text: str, base_mode: int) -> tuple[str, list[str]]:
    """生成前的最终规则检查：补前缀；黑底模式补黑色背景。返回 (文本, 提示信息列表)。"""
    notes = []
    t = (text or "").strip()
    if not t.lower().startswith(PREFIX):
        t = f"{PREFIX}, {t}" if t else PREFIX
        notes.append("已自动在开头补上 ainvfxfluid,")
    if base_mode == 0 and BLACK_BG not in t.lower():
        t = t.rstrip(", ") + f", {BLACK_BG}"
        notes.append("黑底模式：已自动追加 against a black background")
    if has_chinese(t):
        notes.append("最终提示词里还有中文，请先点“转英文”")
    return t, notes


def clean_translation(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"^(translation|english)\s*:\s*", "", s, flags=re.I)
    s = s.strip().strip('"“”').strip()
    return re.sub(r"\s+", " ", s)
