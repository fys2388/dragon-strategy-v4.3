# 2026-09-21 推送审阅修复：LLM 智能分析与 RISK 配置对齐

## 背景

用户审阅 2026-09-21 11:40 的飞书推送，发现 4 类不一致：

1. **止损/目标价与 RISK 配置严重不一致**：万科A 4.19元 报"止损3.8元"=-9.3%（config `stop_loss_pct=0.05`），单票 3000×9.3%=亏 300 元，是设计上限 150 元的 2 倍；天沃 -8.1%、莲花 -9.8% 同样失控
2. **万科A 行业标"综合"而非"房地产"**：数据源返回"万 科Ａ"（半角空格 + 全角Ａ），`"万科" in name` 匹配不到，LLM 分析被误导成多元化企业叙述
3. **资金流出标的未做风险对冲说明**：天沃科技资金流出 🔴 却拿到 85 分推荐，推送文案里无解释
4. **规则打分档位偏乐观**：75 分标"🟢 强"让用户误读为 90% 上涨概率

## 修复内容

| 文件 | 改动 |
|---|---|
| `strategies/macd_resonance/llm_analyzer.py` | (1) 引入 `from .config import LLM, RISK`；(2) `_build_analysis_prompt` 把 `RISK.stop_loss_pct/take_profit_1_pct/take_profit_2_pct` 硬编码进 prompt，明写"不要自造数字"；(3) 新增 `_clamp_risk_fields` staticmethod 后端保险：无条件把止损价夹到 `round(price*(1-stop_loss_pct), 2)`，目标价抬到不低于首档止盈；(4) `_analyze_with_llm` 解析 JSON 后立即 clamp；(5) INDUSTRY_KEYWORDS["房地产"] 新增万科/保利/招商蛇口/金地/新城/龙湖/碧桂园/旭辉/金科/融信/华侨城/首开/华发；(6) 新增 `_normalize_stock_name`：去 Unicode 空白 + 全角转半角（U+FF01~U+FF5E → -0xFEE0，U+3000 跳过）；(7) `_infer_industry` 归一化后再匹配 |
| `scripts/v43_push.py` | `add_multi_dimension_detail`：`moneyflow_state == "outflow"` 时追加 `⚠️MACD滞后于资金面，出现背离；建议按建议仓位的50%以下试仓` |
| `strategies/macd_resonance/ai_scorer.py` | 规则打分档位：**≥85 强🟢 / ≥70 中🟡 / <70 弱⚪**（旧：75/60）；docstring 强调规则打分不是上涨概率 |
| `tests/test_llm_analyzer.py` | 新增 20 项测试：止损 clamp 5 项、行业归一化 5 项、prompt 内容 3 项、打分档位 4 项、prompt 行业归一化 3 项 |

## 测试结果

- 修改前基线：152 passed
- 修改后：**172 passed**（+20 项），1.93s

## 修 4（超跌反弹/趋势突破门槛）本轮未改

`docs/HANDOFF.md:362, 580, 596` 已经诊断过"牛市配 drop_20d_min=20% 结构性不可能"的问题，且 `adaptive_config.py OVERSOLD_PARAMS` 有 regime 分档参数。这是**设计议题而非 bug**——震荡上行/牛市中要求个股先跌 20~25% 才做超跌反弹，本质与"追强"策略冲突。真正修法需要 regime 条件表重构（已记录于 HANDOFF.md 593-597 行），非本轮修复范围。

## 相关历史修复

- 2026-09-21 ai_scorer 打分口径诚实化（`docs/ai_scorer_scoring_fix_2026-09-21.md`）：主字段 `probability → rule_score`，`score_basis="rule_based"`，推送顶部明确标注"规则打分 0~100，非上涨概率"
