from __future__ import annotations

import pandas as pd

from app.schemas.strategy import StrategyPickItem
from app.services.strategies.base import BaseStrategy, _item


class TurtleBreakoutStrategy(BaseStrategy):
    id = "turtle_breakout"
    name = "海龟突破"
    tag = "突破"
    description = "经典突破策略：突破 20 日高点，成交额过亿，且当日阳线真涨。"
    rules = ["收盘价突破前 20 日最高价", "成交额大于 1 亿元", "收盘价高于开盘价和昨日收盘价"]
    history_days = 35

    def run(self, df: pd.DataFrame) -> list[StrategyPickItem]:
        df = df.sort_values(["symbol", "date"]).copy()
        g = df.groupby("symbol", sort=False)

        df["high_20"] = g["high"].shift(1).rolling(20, min_periods=20).max().values
        df["prev_close"] = g["close"].shift(1).values
        df["amount_yi"] = df["amount"] / 1e8

        last = df.groupby("symbol", sort=False).tail(1)
        mask = (
            last["high_20"].notna()
            & (last["close"] > last["high_20"])
            & (last["amount_yi"] > 1)
            & (last["close"] > last["open"])
            & (last["close"] > last["prev_close"])
        )
        hits = last[mask]

        items: list[StrategyPickItem] = []
        for _, row in hits.iterrows():
            breakout_pct = (row["close"] / row["high_20"] - 1) * 100
            score = 20 + min(50, breakout_pct * 10) + min(30, row["amount_yi"] / 3)
            items.append(_item(row, score, ["20日新高突破", "成交额过亿", "阳线真涨"], {
                "20日高点": round(row["high_20"], 2),
                "突破幅度%": round(breakout_pct, 2),
                "成交额(亿)": round(row["amount_yi"], 2),
            }, prev_close=row["prev_close"]))
        return items
