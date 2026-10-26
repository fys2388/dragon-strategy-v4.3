# -*- coding: utf-8 -*-
"""修改scanner.py，加入自适应动态参数支持。"""
file_path = r"E:\AI\策略\dragon-strategy-v4.3\strategies\macd_resonance\scanner.py"
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 添加导入
old_import = "from .config import HARD_FILTERS, SIGNAL, RISK, MIN_POOL_SIZE"
new_import = """from .config import HARD_FILTERS, SIGNAL, RISK, MIN_POOL_SIZE
from .adaptive_config import get_macd_params, get_risk_params, get_current_regime, REGIME_LABELS"""
if old_import in content:
    content = content.replace(old_import, new_import)
    print("✅ 导入添加成功")
else:
    print("❌ 未找到导入位置")
    idx = content.find("from .config import")
    print(repr(content[idx:idx+100]))

# 2. 在run方法中，大盘门控通过后，获取动态参数
old_gate = """        # 1. 大盘门控（使用选中源的同一快照）
        score, desc, can_open = get_market_score(market_data=chosen_md)
        result["market_score"] = score
        result["market_desc"] = desc
        result["can_open"] = can_open
        LOG.info(f"大盘评分 {score:.1f}/7，门控{'通过' if can_open else '未通过'}")"""

new_gate = """        # 1. 大盘门控（使用选中源的同一快照）
        score, desc, can_open = get_market_score(market_data=chosen_md)
        result["market_score"] = score
        result["market_desc"] = desc
        result["can_open"] = can_open
        LOG.info(f"大盘评分 {score:.1f}/7，门控{'通过' if can_open else '未通过'}")

        # 1.5 自适应：获取当前市场环境和动态参数
        regime = get_current_regime(chosen_md)
        adaptive_params = get_macd_params(regime)
        risk_params = get_risk_params(regime)
        result["regime"] = regime
        result["regime_label"] = REGIME_LABELS.get(regime, "未知")
        result["adaptive_params"] = adaptive_params
        result["risk_params"] = risk_params
        LOG.info(f"[自适应] 市场环境={regime}({result['regime_label']}) "
                 f"参数={adaptive_params['name']} "
                 f"振幅上限={adaptive_params.get('amplitude_20d_max', 40)}% "
                 f"最低得分={adaptive_params.get('min_score', 60)}")"""

if old_gate in content:
    content = content.replace(old_gate, new_gate)
    print("✅ 大盘门控后添加动态参数成功")
else:
    print("❌ 未找到大盘门控位置")

# 3. 修改硬过滤，使用动态振幅上限
old_hard = """        # 3. 硬过滤（并发补齐 20 日均额/振幅）
        with ThreadPoolExecutor(max_workers=12) as pool:
            enriched = list(pool.map(self._enrich_hard_metrics, candidates))
        passed = []
        reject_reasons = Counter()
        for s in enriched:
            ok, reason = pass_hard_filters(s)
            if ok:
                passed.append(s)
            else:
                reject_reasons[reason] += 1"""

new_hard = """        # 3. 硬过滤（并发补齐 20 日均额/振幅，使用动态振幅上限）
        with ThreadPoolExecutor(max_workers=12) as pool:
            enriched = list(pool.map(self._enrich_hard_metrics, candidates))
        passed = []
        reject_reasons = Counter()
        amp_max = adaptive_params.get("amplitude_20d_max", HARD_FILTERS["amplitude_20d_max"])
        for s in enriched:
            ok, reason = pass_hard_filters(s, amplitude_max=amp_max)
            if ok:
                passed.append(s)
            else:
                reject_reasons[reason] += 1"""

if old_hard in content:
    content = content.replace(old_hard, new_hard)
    print("✅ 硬过滤使用动态振幅成功")
else:
    print("❌ 未找到硬过滤位置")

# 4. 修改信号过滤，使用动态最低得分
old_signal = """        # 5. 共振强度排序，取前 5
        entries.sort(key=lambda x: x.get("score", 0), reverse=True)
        top = entries[:5]"""

new_signal = """        # 5. 共振强度排序，按动态最低得分过滤，取前N
        min_score = adaptive_params.get("min_score", 0)
        max_recs = adaptive_params.get("max_recommendations", 5)
        entries = [e for e in entries if e.get("score", 0) >= min_score]
        entries.sort(key=lambda x: x.get("score", 0), reverse=True)
        top = entries[:max_recs]"""

if old_signal in content:
    content = content.replace(old_signal, new_signal)
    print("✅ 信号过滤使用动态得分成功")
else:
    print("❌ 未找到信号过滤位置")

# 5. 修改build_message，显示市场环境和参数配置
old_msg_title = """    lines.append("【大盘环境】")
    score = result.get("market_score", 0.0)
    can_open = result.get("can_open", False)
    lines.append(f"大盘评分：{score:.1f}/7分 | {'🔴可开仓' if can_open else '🟢观望'}")"""

new_msg_title = """    lines.append("【大盘环境】")
    score = result.get("market_score", 0.0)
    can_open = result.get("can_open", False)
    regime_label = result.get("regime_label", "")
    param_name = ""
    if result.get("adaptive_params"):
        param_name = result["adaptive_params"].get("name", "")
    lines.append(f"大盘评分：{score:.1f}/7分 | {'🔴可开仓' if can_open else '🟢观望'} | {regime_label}·{param_name}")"""

if old_msg_title in content:
    content = content.replace(old_msg_title, new_msg_title)
    print("✅ 消息显示市场环境成功")
else:
    print("❌ 未找到消息标题位置")

# 6. 修改仓位建议，使用动态风控参数
old_risk = """        single = RISK["total_capital"] * RISK["position_pct"]
        lines.append(f"💼 仓位建议（本金{RISK['total_capital']:.0f}元）")
        lines.append(f"  单票≤30%（{single:.0f}元），最多{RISK['max_positions']}只")
        lines.append(f"  止盈：+{RISK['take_profit_1_pct'] * 100:.0f}%减半 / +{RISK['take_profit_2_pct'] * 100:.0f}%清仓 | 止损：-{RISK['stop_loss_pct'] * 100:.0f}%")"""

new_risk = """        risk = result.get("risk_params", RISK)
        single = RISK["total_capital"] * risk.get("position_pct", 0.25)
        lines.append(f"💼 仓位建议（本金{RISK['total_capital']:.0f}元）")
        lines.append(f"  单票≤{risk.get('position_pct', 0.25)*100:.0f}%（{single:.0f}元），最多{risk.get('max_positions', 2)}只")
        lines.append(f"  止盈：+{risk.get('take_profit_1_pct', 0.1) * 100:.0f}%减半 / +{risk.get('take_profit_2_pct', 0.15) * 100:.0f}%清仓 | 止损：-{risk.get('stop_loss_pct', 0.05) * 100:.0f}%")"""

if old_risk in content:
    content = content.replace(old_risk, new_risk)
    print("✅ 仓位建议使用动态风控成功")
else:
    print("❌ 未找到仓位建议位置")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("✅ scanner.py 修改完成")
