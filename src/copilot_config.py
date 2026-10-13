# -*- coding: utf-8 -*-
"""Vision Copilot 配置：多服务商 / API Key / Base URL / 视觉模型 / MCP 协同。

- 各服务商统一按 **OpenAI 兼容** 端点调用（DeepSeek / GLM / OpenAI / Gemini /
  Ollama / SiliconFlow / 自定义均提供 /chat/completions 兼容接口），因此只需
  维护「Base URL + 模型名 + API Key」三要素。
- API Key 本地持久化到 `copilot_config.json`（与 exe/脚本同目录），
  写入前做轻量混淆（XOR+Base64，前缀 `obf:`），避免明文直接裸露；注意这并非
  强加密，仅防肉眼直视。
- 配置结构见 default_cfg()；load/normalize 对缺失项补默认值，保证向后兼容。
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import sys

# ---------------------------------------------------------------------------
# 服务商预设：key -> 展示信息。所有 base 均为 OpenAI 兼容端点。
# needs_key=False 表示本地服务（如 Ollama）无需 API Key。
# ---------------------------------------------------------------------------
PROVIDERS = {
    "deepseek": {
        "name": "DeepSeek 深度",
        "desc": "国内直达 · 性价比高",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "needs_key": True,
        "key_url": "https://platform.deepseek.com/api_keys",
    },
    "glm": {
        "name": "智谱 GLM",
        "desc": "国内直达 · glm-4v 支持看图",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4v-plus",
        "models": ["glm-4v-plus", "glm-4v", "glm-4-plus", "glm-4-air", "glm-4-flash"],
        "needs_key": True,
        "key_url": "https://open.bigmodel.cn/",
    },
    "openai": {
        "name": "OpenAI",
        "desc": "gpt-4o 系列支持看图分析",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
        "needs_key": True,
        "key_url": "https://platform.openai.com/api-keys",
    },
    "gemini": {
        "name": "Google Gemini",
        "desc": "gemini · OpenAI 兼容端点",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "default_model": "gemini-1.5-flash",
        "models": ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash"],
        "needs_key": True,
        "key_url": "https://aistudio.google.com/apikey",
    },
    "ollama": {
        "name": "Ollama 本地模型",
        "desc": "本地部署 · 无需 API Key",
        "base_url": "http://localhost:11434/v1",
        "default_model": "llava",
        "models": ["llava", "llama3.2-vision", "qwen2-vl"],
        "needs_key": False,
        "key_url": "",
    },
    "siliconflow": {
        "name": "硅基流动 SiliconFlow",
        "desc": "国内直达 · 聚合多模型",
        "base_url": "https://api.siliconflow.cn/v1",
        "default_model": "Qwen/Qwen2-VL-7B-Instruct",
        "models": ["Qwen/Qwen2-VL-7B-Instruct", "deepseek-ai/deepseek-vl2",
                   "Pro/Qwen/Qwen2.5-VL-7B-Instruct"],
        "needs_key": True,
        "key_url": "https://cloud.siliconflow.cn/",
    },
    "custom": {
        "name": "自定义 / 其它兼容服务",
        "desc": "任意 OpenAI 兼容端点",
        "base_url": "",
        "default_model": "",
        "models": [],
        "needs_key": True,
        "key_url": "",
    },
}

PROVIDER_ORDER = ["deepseek", "glm", "openai", "gemini", "ollama",
                  "siliconflow", "custom"]

# 系统提示词：让模型扮演「工业视觉检测参数调优助手」
SYSTEM_PROMPT = (
    "你是「工业视觉智能助手」，服务于 MLCC / 电子元件视觉检测系统的参数调优与缺陷诊断。"
    "你可以查看用户提供的截图、曲线、节点中间结果或现场不良品照片。"
    "请结合图像与数值，指出当前阈值/参数与目标的差距，给出具体、可执行的调参建议"
    "（含建议数值与理由），并提示验证方法。回答用简体中文，条理清晰、聚焦可操作性。"
)

_OBF_KEY = "TeruoCopilot"  # 轻量混淆密钥（非强加密）


def _obf(s: str) -> str:
    """轻量混淆：XOR + Base64，前缀 obf:。仅防肉眼直视，非安全加密。"""
    if not s:
        return ""
    raw = s.encode("utf-8")
    key = _OBF_KEY.encode("utf-8")
    x = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
    return "obf:" + base64.urlsafe_b64encode(x).decode("ascii")


def _deobf(s: str) -> str:
    if not s:
        return ""
    if not s.startswith("obf:"):
        return s
    try:
        x = base64.urlsafe_b64decode(s[4:].encode("ascii"))
        key = _OBF_KEY.encode("utf-8")
        raw = bytes(b ^ key[i % len(key)] for i, b in enumerate(x))
        return raw.decode("utf-8")
    except Exception:
        return ""


def _config_path() -> str:
    """配置落盘路径：打包后为 exe 所在目录，开发时为模块所在目录。"""
    if getattr(sys, "frozen", False) and getattr(sys, "executable", ""):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "copilot_config.json")


def default_cfg() -> dict:
    return {
        "provider": "deepseek",
        "api_key": "",
        "base_url": "",        # 空 = 用服务商默认
        "vision_model": "",    # 空 = 用服务商默认
        "max_rounds": 30,
        "force_vision": False,  # 视觉输入开关：False=中间态(自动)
        "mcp": {
            "autostart": True,
            "force_token": True,
            "port": 8765,
            "token": secrets.token_hex(16),
        },
    }


def normalize_cfg(cfg: dict | None) -> dict:
    """对读取到的配置补默认值，保证结构完整、向后兼容。"""
    d = default_cfg()
    cfg = cfg or {}
    d["provider"] = cfg.get("provider") or d["provider"]
    if d["provider"] not in PROVIDERS:
        d["provider"] = "deepseek"
    # api_key 以混淆形式存储，读取时还原为明文供调用
    d["api_key"] = _deobf(cfg.get("api_key", "") or "")
    d["base_url"] = cfg.get("base_url", "") or ""
    d["vision_model"] = cfg.get("vision_model", "") or ""
    try:
        d["max_rounds"] = int(cfg.get("max_rounds", d["max_rounds"]))
    except Exception:
        pass
    d["force_vision"] = bool(cfg.get("force_vision", False))
    mcp = cfg.get("mcp") or {}
    dm = d["mcp"]
    dm["autostart"] = bool(mcp.get("autostart", dm["autostart"]))
    dm["force_token"] = bool(mcp.get("force_token", dm["force_token"]))
    try:
        dm["port"] = int(mcp.get("port", dm["port"]))
    except Exception:
        pass
    dm["token"] = mcp.get("token") or dm["token"]
    return d


def load_cfg() -> dict:
    """读取配置；缺失/损坏时回退默认值。"""
    try:
        with open(_config_path(), "r", encoding="utf-8") as f:
            return normalize_cfg(json.load(f))
    except Exception:
        return default_cfg()


def save_cfg(cfg: dict) -> bool:
    """写盘；api_key 以混淆形式保存。"""
    try:
        out = dict(cfg)
        out["api_key"] = _obf(cfg.get("api_key", "") or "")
        with open(_config_path(), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def effective_base_url(cfg: dict) -> str:
    p = PROVIDERS.get(cfg.get("provider", ""), {})
    return (cfg.get("base_url") or "").strip() or p.get("base_url", "")


def effective_model(cfg: dict) -> str:
    p = PROVIDERS.get(cfg.get("provider", ""), {})
    return (cfg.get("vision_model") or "").strip() or p.get("default_model", "")


def needs_key(cfg: dict) -> bool:
    return bool(PROVIDERS.get(cfg.get("provider", ""), {}).get("needs_key", True))
