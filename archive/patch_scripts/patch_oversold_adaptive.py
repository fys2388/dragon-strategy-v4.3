# -*- coding: utf-8 -*-
"""修改oversold_rebound.py，加入自适应动态参数支持。"""
file_path = r"E:\AI\策略\dragon-strategy-v4.3\strategies\macd_resonance\oversold_rebound.py"
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 添加导入
old_import = "from .config import OVERSOLD_REBOUND, HARD_FILTERS"
new_import = """from .config import OVERSOLD_REBOUND, HARD_FILTERS
from .adaptive_config import get_oversold_params, get_current_regime, REGIME_LABELS"""
if old_import in content:
    content = content.replace(old_import, new_import)
    print("✅ 导入添加成功")
else:
    print("❌ 未找到导入位置")
    idx = content.find("from .config import")
    print(repr(content[idx:idx+100]))

# 2. 在run方法开始处获取动态参数
old_run_start = """    def run(self, need_push: bool = True, max_stocks: int = 1200) -> dict:
        \"\"\"执行超跌反弹扫描。\"\"\"
        t0 = time.time()
        LOG.info("=" * 50)
        LOG.info("🚀 超跌反弹模式启动")"""

new_run_start = """    def run(self, need_push: bool = True, max_stocks: int = 1200) -> dict:
        \"\"\"执行超跌反弹扫描。\"\"\"
        t0 = time.time()
        LOG.info("=" * 50)
        LOG.info("🚀 超跌反弹模式启动")

        # 自适应：获取当前市场环境和动态参数
        market_data = None
        try:
            from .data_validator import get_data_with_fallback
            market_data, _ = get_data_with_fallback()
        except Exception:
            pass
        regime = get_current_regime(market_data)
        adaptive_params = get_oversold_params(regime)
        LOG.info(f"[自适应] 市场环境={regime}({REGIME_LABELS.get(regime, '未知')}) "
                 f"参数={adaptive_params['name']} "
                 f"超跌要求={adaptive_params.get('drop_20d_min', 25)}% "
                 f"启动涨幅={adaptive_params.get('today_gain_min', 4)}%")"""

if old_run_start in content:
    content = content.replace(old_run_start, new_run_start)
    print("✅ run方法添加动态参数成功")
else:
    print("❌ 未找到run方法开始位置")

# 3. 修改超跌条件，使用动态参数
old_oversold = """        # 3. 超跌条件过滤
        oversold_list = []
        for s in candidates:
            try:
                change_20d = float(s.get("change_20d_pct", 0) or 0)
                today_chg = float(s.get("change_pct", 0) or 0)
                # 20日跌幅≥25%
                if change_20d > -OVERSOLD_REBOUND["drop_20d_min"]:
                    continue
                # 当日涨幅≥4%（启动信号）
                if today_chg < OVERSOLD_REBOUND["today_gain_min"]:
                    continue
                # 近5日振幅≤12%（排除已经大幅波动的）
                amp_5d = float(s.get("amplitude_5d_pct", 99) or 99)
                if amp_5d > OVERSOLD_REBOUND["amplitude_5d_max"]:
                    continue
                oversold_list.append(s)
            except Exception:
                continue"""

new_oversold = """        # 3. 超跌条件过滤（使用动态参数）
        drop_min = adaptive_params.get("drop_20d_min", OVERSOLD_REBOUND["drop_20d_min"])
        gain_min = adaptive_params.get("today_gain_min", OVERSOLD_REBOUND["today_gain_min"])
        oversold_list = []
        for s in candidates:
            try:
                change_20d = float(s.get("change_20d_pct", 0) or 0)
                today_chg = float(s.get("change_pct", 0) or 0)
                # 20日跌幅≥动态阈值
                if change_20d > -drop_min:
                    continue
                # 当日涨幅≥动态阈值（启动信号）
                if today_chg < gain_min:
                    continue
                # 近5日振幅≤12%（排除已经大幅波动的）
                amp_5d = float(s.get("amplitude_5d_pct", 99) or 99)
                if amp_5d > OVERSOLD_REBOUND["amplitude_5d_max"]:
                    continue
                oversold_list.append(s)
            except Exception:
                continue"""

if old_oversold in content:
    content = content.replace(old_oversold, new_oversold)
    print("✅ 超跌条件使用动态参数成功")
else:
    print("❌ 未找到超跌条件位置")

# 4. 修改技术确认，使用动态量比和DIF下限
old_tech = """        # 4. 技术确认（量比+MACD）
        confirmed = []
        for s in oversold_list:
            try:
                # 量比≥1.8
                vol_ratio = float(s.get("volume_ratio", 0) or 0)
                if vol_ratio < OVERSOLD_REBOUND["volume_ratio_min"]:
                    continue
                # 日线DIF > -0.8（不能太深）
                daily_dif = float(s.get("daily_dif", -99) or -99)
                if daily_dif < OVERSOLD_REBOUND["daily_dif_floor"]:
                    continue
                # 60分钟MACD金叉
                tf60 = s.get("tf60", {})
                if not tf60 or not tf60.get("is_golden_cross"):
                    continue
                confirmed.append(s)
            except Exception:
                continue"""

new_tech = """        # 4. 技术确认（量比+MACD，使用动态参数）
        vol_min = adaptive_params.get("volume_ratio_min", OVERSOLD_REBOUND["volume_ratio_min"])
        dif_floor = adaptive_params.get("daily_dif_floor", OVERSOLD_REBOUND["daily_dif_floor"])
        confirmed = []
        for s in oversold_list:
            try:
                # 量比≥动态阈值
                vol_ratio = float(s.get("volume_ratio", 0) or 0)
                if vol_ratio < vol_min:
                    continue
                # 日线DIF > 动态下限（不能太深）
                daily_dif = float(s.get("daily_dif", -99) or -99)
                if daily_dif < dif_floor:
                    continue
                # 60分钟MACD金叉
                tf60 = s.get("tf60", {})
                if not tf60 or not tf60.get("is_golden_cross"):
                    continue
                confirmed.append(s)
            except Exception:
                continue"""

if old_tech in content:
    content = content.replace(old_tech, new_tech)
    print("✅ 技术确认使用动态参数成功")
else:
    print("❌ 未找到技术确认位置")

# 5. 修改推荐数量限制
old_limit = """        # 5. 按当日涨幅排序，取前5
        confirmed.sort(key=lambda x: float(x.get("change_pct", 0) or 0), reverse=True)
        top = confirmed[:5]"""

new_limit = """        # 5. 按当日涨幅排序，取前N（动态）
        max_recs = adaptive_params.get("max_recommendations", 5)
        confirmed.sort(key=lambda x: float(x.get("change_pct", 0) or 0), reverse=True)
        top = confirmed[:max_recs]"""

if old_limit in content:
    content = content.replace(old_limit, new_limit)
    print("✅ 推荐数量使用动态参数成功")
else:
    print("❌ 未找到推荐数量位置")

# 6. 在result中保存市场环境
old_result = """        result = {
            "scan_time": now_bjt().strftime("%Y-%m-%d %H:%M"),
            "total_scanned": len(candidates),
            "oversold_count": len(oversold_list),
            "confirmed_count": len(confirmed),
            "entries": top,
            "diagnosis": diagnosis,
            "scan_elapsed": round(time.time() - t0, 1),
        }"""

new_result = """        result = {
            "scan_time": now_bjt().strftime("%Y-%m-%d %H:%M"),
            "total_scanned": len(candidates),
            "oversold_count": len(oversold_list),
            "confirmed_count": len(confirmed),
            "entries": top,
            "diagnosis": diagnosis,
            "scan_elapsed": round(time.time() - t0, 1),
            "regime": regime,
            "regime_label": REGIME_LABELS.get(regime, "未知"),
            "adaptive_params": adaptive_params,
        }"""

if old_result in content:
    content = content.replace(old_result, new_result)
    print("✅ result保存市场环境成功")
else:
    print("❌ 未找到result位置")

# 7. 修改build_oversold_message，显示市场环境
old_msg = """    lines = [
        f"🚀 超跌反弹策略 盘中实时 {scan_time}",
        "━" * 35,
        "",
        "【超跌反弹推荐】",
    ]"""

new_msg = """    regime_label = result.get("regime_label", "")
    param_name = ""
    if result.get("adaptive_params"):
        param_name = result["adaptive_params"].get("name", "")
    lines = [
        f"🚀 超跌反弹策略 盘中实时 {scan_time} | {regime_label}·{param_name}",
        "━" * 35,
        "",
        "【超跌反弹推荐】",
    ]"""

if old_msg in content:
    content = content.replace(old_msg, new_msg)
    print("✅ 消息显示市场环境成功")
else:
    print("❌ 未找到消息位置")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("✅ oversold_rebound.py 修改完成")
