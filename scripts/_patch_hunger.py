# -*- coding: utf-8 -*-
"""在 breakout.py 中实现推荐饥饿度自适应机制。"""

filepath = r"E:\AI\策略\dragon-strategy-v4.3\strategies\macd_resonance\breakout.py"

with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

# 在 max_recommend 和 min_score_override 之后，加入饥饿度自适应
old = """        # 大盘3-4分（宽松档）：最多2只，最低得分提高到60
        max_recommend = 2 if score < 4.0 else 5
        min_score_override = 60 if score < 4.0 else 0

        # 1. 获取股票池"""

new = """        # 大盘3-4分（宽松档）：最多2只，最低得分提高到60
        max_recommend = 2 if score < 4.0 else 5
        min_score_override = 60 if score < 4.0 else 0

        # === 推荐饥饿度自适应：连续0推荐时自动放宽，让Agent有学习素材 ===
        hunger_days = self._calc_hunger_days()
        hunger_level = 0
        if hunger_days >= 7:
            # 连续7天0推荐：大幅放宽，只要技术面通过就推荐
            max_recommend = max(max_recommend, 8)
            min_score_override = 0  # 不设最低得分
            hunger_level = 3
            LOG.info(f"[饥饿度] 连续{hunger_days}天0推荐，Level3：大幅放宽")
        elif hunger_days >= 5:
            # 连续5天0推荐：中度放宽
            max_recommend = max(max_recommend + 2, 5)
            min_score_override = max(min_score_override - 10, 40)
            hunger_level = 2
            LOG.info(f"[饥饿度] 连续{hunger_days}天0推荐，Level2：中度放宽")
        elif hunger_days >= 3:
            # 连续3天0推荐：轻度放宽
            max_recommend = max(max_recommend + 1, 3)
            min_score_override = max(min_score_override - 5, 50)
            hunger_level = 1
            LOG.info(f"[饥饿度] 连续{hunger_days}天0推荐，Level1：轻度放宽")
        result["hunger_days"] = hunger_days
        result["hunger_level"] = hunger_level

        # 1. 获取股票池"""

if old in content:
    content = content.replace(old, new, 1)
    print("饥饿度自适应逻辑插入成功")
else:
    print("未找到插入点")
    exit(1)

# 在类中添加 _calc_hunger_days 方法
# 找到 _load_cooldown_codes 方法之后插入
old_method = """    def _load_cooldown_codes(self) -> set:"""

new_method = """    def _calc_hunger_days(self) -> int:
        \"\"\"计算连续0推荐的天数（饥饿度）。

        从 tracking.jsonl 中统计最近有记录的日期里，推荐数量为0的连续天数。
        \"\"\"
        import json as _json
        from datetime import datetime, timedelta
        tracking_file = ds.os.path.join(self.base_dir, 'data', 'tracking.jsonl')
        if not ds.os.path.exists(tracking_file):
            return 0

        # 按日期统计推荐数量
        daily_counts = {}
        try:
            with open(tracking_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = _json.loads(line)
                        scan_time = rec.get('scan_time', '')
                        if scan_time:
                            day = scan_time[:10]  # YYYY-MM-DD
                            strategy = rec.get('strategy', '')
                            if strategy == 'breakout':
                                daily_counts[day] = daily_counts.get(day, 0) + 1
                    except (_json.JSONDecodeError, KeyError):
                        continue
        except Exception:
            return 0

        # 从今天往前数，连续0推荐的天数
        hunger = 0
        today = now_bjt().date()
        for i in range(1, 15):  # 最多查15天
            day = (today - timedelta(days=i)).strftime('%Y-%m-%d')
            # 周末不算（周六周日不是交易日）
            weekday = (today - timedelta(days=i)).weekday()
            if weekday >= 5:  # 周六=5, 周日=6
                continue
            count = daily_counts.get(day, 0)
            if count == 0:
                hunger += 1
            else:
                break
        return hunger

    def _load_cooldown_codes(self) -> set:"""

if old_method in content:
    content = content.replace(old_method, new_method, 1)
    print("_calc_hunger_days 方法插入成功")
else:
    print("未找到 _load_cooldown_codes 方法位置")

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)
print("文件已保存")
