# -*- coding: utf-8 -*-
"""学习闭环调参中心（单一来源）。

背景：Agent 学习闭环（tracking → weekly_optimizer → evolution_engine → 参数回写）
长期无法启动，根因之一是「样本口径」散落在各模块、且完成窗口定得太长：

- 原 `tracking.update_performance()` 只在 **第 20 个交易日**结束跟踪并标记 completed；
  每周 1-2 只推荐 × 20 交易日 ≈ 数周才有 1 条 completed 样本。
- 原 `weekly_optimizer` 要求 ≥5 条、`evolution_engine` 要求 ≥10 条 completed（按 day5 收益），
  叠加 20 日完成窗口后，这两道门在冷启动期永远打不开 → 优化器只输出
  「样本不足，继续收集数据」，进化引擎永不进化。

本模块把这套口径集中到一处，避免各模块各写各的魔法数字：

- `COMPLETION_DAY = 3`：一条记录在 **第 3 个交易日**即可标记 completed，
  供周度优化 / 进化 / 权重优化消费；更长的 5/10/20 日收益字段仍照常计算，
  用于绩效报告，互不冲突。
- `MIN_COMPLETED_SAMPLES`：冷启动期使用的样本下限，样本攒够后应回调到 `MIN_SAMPLES_FULL`。
- `COMPLETION_DAY_FIELD`：completed 判定所用的收益字段，需与 `COMPLETION_DAY` 对应。

注意：本模块不引入任何第三方依赖，不读文件，可安全离线导入。
"""
from __future__ import annotations

# 完成窗口：第 N 个交易日即视为「可用于优化的完成样本」
COMPLETION_DAY = 3

# completed 判定读取的收益字段，必须与 COMPLETION_DAY 对齐
# （3 日窗口 → day3_return_pct；改回 20 日窗口时改为 day20_return_pct）
COMPLETION_DAY_FIELD = f"day{COMPLETION_DAY}_return_pct"

# 绩效跟踪最长观察期（保留长周期指标：5/10/20 日收益、MAE/MFE 等）
FULL_TRACK_DAYS = 20

# 样本下限：冷启动期（当前）/ 样本充足后的正式值
MIN_COMPLETED_SAMPLES = 3
MIN_SAMPLES_FULL = 5

# 周度优化 / 权重优化分别使用的样本下限（冷启动期统一取低值）
WEEKLY_OPTIMIZER_MIN_SAMPLES = MIN_COMPLETED_SAMPLES
EVOLUTION_MIN_SAMPLES = MIN_COMPLETED_SAMPLES
WEIGHT_MIN_SAMPLES = MIN_COMPLETED_SAMPLES

# 冷启动阶段标记：True 表示正在用低样本下限，攒够样本后应翻回 False
COLD_START = True


def min_samples_for(kind: str) -> int:
    """按用途返回当前样本下限。

    Args:
        kind: "weekly" / "evolution" / "weight"
    """
    return {
        "weekly": WEEKLY_OPTIMIZER_MIN_SAMPLES,
        "evolution": EVOLUTION_MIN_SAMPLES,
        "weight": WEIGHT_MIN_SAMPLES,
        # "full" = 冷启动结束后应恢复到的正式下限（把 COLD_START 翻回 False 时用）
        "full": MIN_SAMPLES_FULL,
    }.get(kind, MIN_COMPLETED_SAMPLES)


def completion_summary() -> dict:
    """当前完成口径摘要（供报告 / 单测读取）。"""
    return {
        "completion_day": COMPLETION_DAY,
        "completion_field": COMPLETION_DAY_FIELD,
        "full_track_days": FULL_TRACK_DAYS,
        "min_samples": {
            "weekly": WEEKLY_OPTIMIZER_MIN_SAMPLES,
            "evolution": EVOLUTION_MIN_SAMPLES,
            "weight": WEIGHT_MIN_SAMPLES,
        },
        "cold_start": COLD_START,
    }
