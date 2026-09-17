# -*- coding: utf-8 -*-
file_path = r"E:\AI\策略\dragon-strategy-v4.3\strategies\macd_resonance\oversold_rebound.py"
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 在run方法中添加动态参数
old = '''    def run(self, max_stocks: int = 2000, need_push: bool = False) -> Dict:
        """执行超跌反弹扫描。"""
        cfg = OVERSOLD_REBOUND
        result = {'''

new = '''    def run(self, max_stocks: int = 2000, need_push: bool = False) -> Dict:
        """执行超跌反弹扫描。"""
        cfg = OVERSOLD_REBOUND.copy()
        # 自适应：获取当前市场环境和动态参数
        from .data_validator import get_data_with_fallback
        try:
            market_data, _ = get_data_with_fallback()
        except Exception:
            market_data = None
        regime = get_current_regime(market_data)
        adaptive_params = get_oversold_params(regime)
        for key in ['drop_20d_min', 'today_gain_min', 'volume_ratio_min', 'daily_dif_floor', 'max_recommendations']:
            if key in adaptive_params:
                cfg[key] = adaptive_params[key]
        LOG.info(f"[自适应] 市场环境={regime}({REGIME_LABELS.get(regime, '未知')}) 参数={adaptive_params['name']} 超跌要求={cfg['drop_20d_min']}% 启动涨幅={cfg['today_gain_min']}%")
        result = {'''

if old in content:
    content = content.replace(old, new)
    print("✅ run方法添加动态参数成功")
else:
    print("❌ 未找到run方法")

# 2. 在result中添加市场环境
old = '''        result["scan_elapsed"] = round(time.time() - t0, 1)
        LOG.info(f"[超跌反弹] {result['summary']}，耗时{result['scan_elapsed']}s")
        return result'''

new = '''        result["scan_elapsed"] = round(time.time() - t0, 1)
        result["regime"] = regime
        result["regime_label"] = REGIME_LABELS.get(regime, "未知")
        result["adaptive_params"] = adaptive_params
        LOG.info(f"[超跌反弹] {result['summary']}，耗时{result['scan_elapsed']}s")
        return result'''

if old in content:
    content = content.replace(old, new)
    print("✅ result添加市场环境成功")
else:
    print("❌ 未找到result结尾")

# 3. 修改build_oversold_message
old = '''    now = now_bjt().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"🚀 超跌反弹策略 盘中实时 {now}",'''

new = '''    now = now_bjt().strftime("%Y-%m-%d %H:%M")
    regime_label = result.get("regime_label", "")
    param_name = ""
    if result.get("adaptive_params"):
        param_name = result["adaptive_params"].get("name", "")
    env_tag = f" | {regime_label}·{param_name}" if regime_label else ""
    lines = [
        f"🚀 超跌反弹策略 盘中实时 {now}{env_tag}",'''

if old in content:
    content = content.replace(old, new)
    print("✅ 消息显示市场环境成功")
else:
    print("❌ 未找到消息位置")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("✅ oversold_rebound.py 修改完成")
