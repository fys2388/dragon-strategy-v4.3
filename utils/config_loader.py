# -*- coding: utf-8 -*-
"""配置加载工具：环境变量占位符替换，集中管理敏感配置。"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict

_PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def resolve_env(value: Any) -> Any:
    """递归解析 ${VAR} 占位符为环境变量值。"""
    if isinstance(value, str):
        def _sub(match):
            var = match.group(1)
            if var not in os.environ:
                raise KeyError(f"环境变量 {var} 未配置")
            return os.environ[var]
        return _PLACEHOLDER_RE.sub(_sub, value)
    if isinstance(value, dict):
        return {k: resolve_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_env(v) for v in value]
    return value


def load_feishu_config(config_path: str = None) -> dict:
    """加载飞书配置。

    从 config/feishu_config.json 读取，将 ${VAR} 替换为环境变量值。
    webhook_url 缺失时抛出明确异常，不静默。

    Returns:
        {"webhook_url": str, "enabled": bool, ...}
    """
    if config_path is None:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(base, "config", "feishu_config.json")

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"飞书配置文件不存在: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    data = resolve_env(raw)

    # 兼容新格式 {"webhook_url": ...} 与旧格式 {"飞书配置": {"webhook": ...}}
    webhook = None
    if isinstance(data.get("webhook_url"), str):
        webhook = data["webhook_url"]
    elif isinstance(data.get("飞书配置"), dict):
        webhook = data["飞书配置"].get("webhook") or data["飞书配置"].get("webhook_url")

    if not webhook:
        raise ValueError(
            "飞书 webhook 未配置：请在 config/feishu_config.json 设置 "
            '"webhook_url": "${FEISHU_WEBHOOK_URL}" 并配置环境变量 FEISHU_WEBHOOK_URL'
        )

    return {
        "webhook_url": webhook,
        "enabled": bool(data.get("enabled", True)),
        "raw": data,
    }


def load_json_with_env(path: str) -> Dict:
    """通用 JSON 加载（含环境变量占位符替换）。"""
    with open(path, "r", encoding="utf-8") as f:
        return resolve_env(json.load(f))
