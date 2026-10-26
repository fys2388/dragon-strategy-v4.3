# -*- coding: utf-8 -*-
"""每周模型训练脚本。

每周日运行，训练：
1. LightGBM预测模型（用优质股票池20-30只股票的250天数据）
2. 市场状态聚类模型（用沪指250天数据）

训练完成后推送报告到飞书。
"""
from __future__ import annotations

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance.ai_predictor import init_ai_predictor
from strategies.macd_resonance.market_cluster import init_market_cluster
from strategies.macd_resonance import data_source as ds


def send_feishu(text: str):
    webhook = os.environ.get("FEISHU_WEBHOOK_URL", "")
    if not webhook:
        print("⚠️ 未配置 FEISHU_WEBHOOK_URL")
        return
    import requests
    try:
        resp = requests.post(webhook, json={"msg_type": "text", "content": {"text": text}}, timeout=8)
        print(f"✅ 飞书推送完成 HTTP {resp.status_code}")
    except Exception as e:
        print(f"❌ 飞书推送失败: {e}")


def main():
    print("=" * 50)
    print("🤖 每周模型训练")
    print("=" * 50)

    # 1. 加载优质股票池
    pool_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "quality_pool.json")
    try:
        with open(pool_file, "r", encoding="utf-8") as f:
            pool = json.load(f)
        train_codes = [item["code"] for item in pool[:25]]
        print(f"训练股票数：{len(train_codes)}只")
    except Exception as e:
        print(f"⚠️ 加载股票池失败: {e}，使用默认股票")
        train_codes = ["600519", "000858", "601318", "000333", "600036",
                       "002594", "601012", "002475", "600276", "601888",
                       "000651", "600887", "002304", "603288", "000568",
                       "600030", "601398", "600000", "000001", "600036"]

    # 2. 训练LightGBM预测模型
    print("\n" + "=" * 50)
    print("训练LightGBM预测模型...")
    predictor = init_ai_predictor()
    train_result = predictor.train(train_codes, days=250)

    # 3. 训练市场聚类模型
    print("\n" + "=" * 50)
    print("训练市场状态聚类模型...")
    try:
        cluster = init_market_cluster()
        # 获取沪指数据
        index_df = ds.get_kline_daily("000001", count=300)  # 沪指
        if not index_df.empty:
            cluster_result = cluster.train(index_df, n_clusters=6)
            cluster_status = "成功"
        else:
            cluster_result = {"message": "沪指数据获取失败"}
            cluster_status = "失败"
    except Exception as e:
        cluster_result = {"message": str(e)}
        cluster_status = "失败"

    # 4. 生成训练报告
    report_lines = [
        "🤖 每周模型训练报告",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "【LightGBM预测模型】",
    ]

    if train_result.get("status") == "ok":
        report_lines.extend([
            f"✅ 训练成功",
            f"训练时间：{train_result.get('trained_at')}",
            f"训练样本：{train_result.get('sample_count')}条",
            f"正样本：{train_result.get('positive_count')}条 | 负样本：{train_result.get('negative_count')}条",
            f"验证准确率：{train_result.get('accuracy')}%",
            f"AUC：{train_result.get('auc')}",
            "",
            "Top10重要特征：",
        ])
        for i, f in enumerate(train_result.get("top_features", [])[:10], 1):
            report_lines.append(f"  {i}. {f['feature']}（{f['importance']}）")
    else:
        report_lines.append(f"❌ 训练失败：{train_result.get('message', '未知错误')}")

    report_lines.extend([
        "",
        "【市场状态聚类模型】",
        f"状态：{cluster_status}",
    ])
    if cluster_result.get("status") == "ok" or cluster_result.get("cluster_stats"):
        report_lines.append(f"聚类数：{cluster_result.get('n_clusters', 6)}")
        report_lines.append(f"样本数：{cluster_result.get('sample_count', 0)}天")

    report_lines.extend([
        "",
        "📌 模型已保存，下周选股将使用新模型进行AI打分",
    ])

    report = "\n".join(report_lines)
    print("\n" + report)

    # 5. 推送飞书
    send_feishu(report)


if __name__ == "__main__":
    main()
