"""中文 → 英文：调用外接大模型接口（llm.py，配置在 .env），不占本地显存、不经过生成引擎。

术语表的作用：把命中的特效词汇连同固定英文说法一起交给模型，要求照用，保证说法稳定、贴合 LoRA。
接口未配置或调用失败时退到“仅术语表替换”，并明确提示剩余中文需手写。
"""
from __future__ import annotations

from . import llm
from . import prompt as P

SYSTEM = ("You translate Chinese descriptions into concise, natural English for an AI video generation prompt "
          "(fluid visual effects: fire, explosions, smoke, steam, water, dust, fog, clouds). "
          "Keep any English words unchanged. Do not add, explain or omit content. "
          "Output only the English translation on a single line, without quotes or a trailing period.")


def _system_with_terms(text: str) -> tuple[str, dict]:
    g = P.load_glossary()
    hits = {zh: en for zh, en in sorted(g.items(), key=lambda kv: -len(kv[0])) if zh and zh in text}
    # 长词已覆盖的短词不再重复列出（例如“浓烟”已命中就不再列“烟”）
    terms = {}
    for zh, en in hits.items():
        if not any(zh in longer for longer in terms):
            terms[zh] = en
    sys = SYSTEM
    if terms:
        sys += " Use these fixed translations for the following terms: " + "; ".join(f"{zh} = {en}" for zh, en in terms.items()) + "."
    return sys, terms


def translate_text(text: str, overrides: dict | None = None, transport=None) -> dict:
    text = (text or "").strip()
    if not text:
        return {"english": "", "method": "empty"}
    if not P.has_chinese(text):
        return {"english": P.clean_translation(text), "method": "unchanged"}
    system, terms = _system_with_terms(text)
    res = llm.complete(system, text, overrides, transport)
    if res["ok"]:
        lines = [l for l in res["text"].splitlines() if l.strip()]
        out = P.clean_translation(lines[0] if lines else "").rstrip(" .。")
        r = {"english": out, "method": "api", "wire": res["wire"], "model": res["model"],
             "elapsed": res["elapsed"], "terms": terms}
        if P.has_chinese(out):
            r["warning"] = "翻译结果里仍有中文，请检查并手动修改。"
        return r
    glossed = P.apply_glossary(text)
    return {"english": glossed, "method": "glossary-only", "terms": terms,
            "warning": f"{res['error']}。已只按术语表替换了特效词汇，剩余中文请手动改成英文。"}
