from __future__ import annotations

import pandas as pd

from app.schemas.strategy import StrategyPickItem
from app.services.strategies.base import BaseStrategy, _item


class UptrendLimitDownStrategy(BaseStrategy):
    id = "uptrend_limit_down"
    name = "趋势急跌修复"
    tag = "反转"
    description = "趋势回撤策略：上升趋势中出现放量急跌，用于观察错杀修复机会。"
    rules = ["昨日 20 日均线高于 60 日均线", "今日收盘价较昨日下跌至少 9.5%", "今日成交量大于 20 日均量 2 倍"]
    history_days = 65

    def run(self, df: pd.DataFrame) -> list[StrategyPickItem]:
        df = df.sort_values(["symbol", "date"]).copy()
        g = df.groupby("symbol", sort=False)

        df["ma20"] = g["close"].rolling(20, min_periods=20).mean().values
        df["ma60"] = g["close"].rolling(60, min_periods=60).mean().values
        df["vol20"] = g["volume"].rolling(20, min_periods=20).mean().values
        df["prev_close"] = g["close"].shift(1).values
        df["prev_ma20"] = g["ma20"].shift(1).values
        df["prev_ma60"] = g["ma60"].shift(1).values
        df["prev_vol20"] = g["vol20"].shift(1).values

        last = df.groupby("symbol", sort=False).tail(1).dropna(
            subset=["prev_ma20", "prev_ma60", "prev_vol20", "prev_close", "close", "volume"]
        )
        if last.empty:
            return []

        mask = (
            (last["prev_ma20"] > last["prev_ma60"])
            & (last["close"] <= last["prev_close"] * 0.905)
            & (last["volume"] > last["prev_vol20"] * 2.0)
        )
        hits = last[mask]

        items: list[StrategyPickItem] = []
        for _, row in hits.iterrows():
            trend_gap = (row["prev_ma20"] / row["prev_ma60"] - 1) * 100
            drop_pct = (row["close"] / row["prev_close"] - 1) * 100
            volume_ratio = row["volume"] / row["prev_vol20"]
            score = 30 + min(30, max(0, trend_gap) * 8) + min(30, abs(drop_pct) * 2) + min(10, volume_ratio)
            items.append(_item(row, score, ["上升趋势", "放量急跌", "修复观察"], {
                "MA20": round(row["prev_ma20"], 2),
                "MA60": round(row["prev_ma60"], 2),
                "今日跌幅%": round(drop_pct, 2),
                "量比20日": round(volume_ratio, 2),
            }, prev_close=row["prev_close"]))
        return items
