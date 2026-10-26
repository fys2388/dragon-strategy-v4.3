# -*- coding: utf-8 -*-
"""为突破策略增加基本面硬过滤。"""

with open('strategies/macd_resonance/breakout.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = """        # 6. 综合打分排序（融合熊猫有财技术面 + 黄阳基本面）
        for s in breakout_list:
            tech_score = self._calc_composite_score(s)
            # 技术面60% + 黄阳基本面40%
            s["composite_score"] = round(tech_score * 0.6 + s.get("huangyang_score", 50) * 0.4, 1)
        breakout_list.sort(key=lambda x: x.get("composite_score", 0), reverse=True)
        top = breakout_list[:5]"""

new = """        # 6. 基本面硬过滤（黄阳价值投资核心理念：好生意+好公司+好价格）
        # 第一档：过滤掉偏弱(<50分)和差，只保留一般及以上
        fundamental_filtered = [s for s in breakout_list if s.get("huangyang_score", 50) >= 50]
        if not fundamental_filtered:
            # 降级：只过滤差(<40分)，保留偏弱
            fundamental_filtered = [s for s in breakout_list if s.get("huangyang_score", 50) >= 40]
            LOG.info("[趋势突破] 基本面硬过滤降级：一般及以上无标的，放宽到偏弱及以上")
        if not fundamental_filtered:
            # 再降级：不过滤，但全部标记基本面风险
            fundamental_filtered = breakout_list
            LOG.info("[趋势突破] 基本面硬过滤再次降级：无标的满足基本面要求，全部保留但标记风险")
        filtered_count = len(breakout_list) - len(fundamental_filtered)
        if filtered_count > 0:
            LOG.info(f"[趋势突破] 基本面硬过滤：{filtered_count}只基本面不达标被过滤")

        # 7. 综合打分排序（融合熊猫有财技术面 + 黄阳基本面）
        for s in fundamental_filtered:
            tech_score = self._calc_composite_score(s)
            # 技术面60% + 黄阳基本面40%
            s["composite_score"] = round(tech_score * 0.6 + s.get("huangyang_score", 50) * 0.4, 1)
        fundamental_filtered.sort(key=lambda x: x.get("composite_score", 0), reverse=True)
        top = fundamental_filtered[:5]"""

if old in content:
    content = content.replace(old, new, 1)
    print('修改成功')
else:
    print('未找到匹配字符串')
    # 打印附近内容
    idx = content.find('综合打分排序')
    if idx >= 0:
        print(repr(content[idx-50:idx+300]))

with open('strategies/macd_resonance/breakout.py', 'w', encoding='utf-8') as f:
    f.write(content)
