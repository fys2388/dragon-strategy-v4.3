# -*- coding: utf-8 -*-
"""飞书自定义机器人「是否真的送达」判定。

为什么要这个模块
    飞书自定义机器人成功返回 HTTP 200 + 正文 {"StatusCode": 0}（v2）或 {"code": 0}（v1）。
    但 webhook 被删除 / 停用 / token 过期时，HTTP 往往**仍然是 200**，
    只有正文里的状态码非 0。只看 HTTP 状态码会把「消息根本没送达」误判成「推送成功」。

    2026-09 之前仓库里三个推送函数（v43_push._send_text / v43_push.send_feishu_alert /
    morning_noon_push.send_to_feishu）全是这么写的，且调用方从不读返回值。结果：
    webhook 失效 → 打印「✅ 推送完成，HTTP 200」→ workflow 全绿 → 调度器健康检查
    数到 10 次成功运行 → 报「✅ 正常」。用户可能连着几天一条都没收到，全程零告警。
    见 docs/HANDOFF.md §6.2.1。

保守原则（很重要，别改）
    正文不是 JSON、或没有可识别的状态码字段时，视为**成功**。
    即「只在确定失败时才失败」——避免飞书调整响应格式时误报、把推送链路整体掐断。

依赖
    零。本模块不 import requests，只接收 requests 的 Response 对象（duck typing）。
    这样 scheduler_health_check.py 这类只装了 requests 的轻量工作流也能安全复用同样的判定。
"""
from __future__ import annotations

from typing import Any, Tuple

# 飞书两套响应格式的成功标志：v2 用 StatusCode，v1 用 code。
_STATUS_KEYS = ("StatusCode", "code")


def check_feishu(resp: Any) -> Tuple[bool, str]:
    """校验一次飞书 POST 是否真的成功。

    返回 (是否成功, 失败原因)。失败原因供日志/告警文案直接展示，带 HTTP 状态码与
    飞书返回的 msg，排查时不用再去翻原始响应。
    """
    status = getattr(resp, "status_code", 0)
    if status != 200:
        body = (getattr(resp, "text", "") or "")[:120]
        return False, f"HTTP {status}: {body}"

    try:
        data = resp.json()
    except Exception:
        return True, ""
    if not isinstance(data, dict):
        return True, ""

    code = None
    for key in _STATUS_KEYS:
        if key in data:
            code = data[key]
            break
    if code in (None, 0):
        return True, ""
    return False, f"飞书拒绝 StatusCode={code} msg={data.get('msg', '')}"
