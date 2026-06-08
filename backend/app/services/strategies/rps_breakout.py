from __future__ import annotations

import pandas as pd

from app.schemas.strategy import StrategyPickItem
from app.services.strategies.base import BaseStrategy, _item


class RpsBreakoutStrategy(BaseStrategy):
    id = "rps_breakout"
    name = "RPS 强势突破"
    tag = "强势"
    description = "相对强度策略：120 日涨幅横向排名靠前，且价格接近阶段高点。"
    rules = ["120 日涨幅排名进入前 10%", "收盘价接近 120 日最高价", "优先选择相对强度更高的股票"]
    history_days = 130

    def run(self, df: pd.DataFrame) -> list[StrategyPickItem]:
        df = df.sort_values(["symbol", "date"]).copy()
        g = df.groupby("symbol", sort=False)

        df["close_120"] = g["close"].shift(120).values
        df["high_120"] = g["high"].rolling(120, min_periods=60).max().values
        df["prev_close"] = g["close"].shift(1).values

        last = df.groupby("symbol", sort=False).tail(1).dropna(subset=["close_120", "high_120"])
        if last.empty:
            return []

        last = last.copy()
        last["pct120"] = (last["close"] / last["close_120"] - 1) * 100
        last["rps"] = last["pct120"].rank(pct=True) * 100

        hits = last[(last["rps"] >= 90) & (last["close"] >= last["high_120"] * 0.9)]

        items: list[StrategyPickItem] = []
        for _, row in hits.iterrows():
            score = row["rps"] * 0.8 + min(100, max(0, row["pct120"])) * 0.2
            items.append(_item(row, score, ["120日相对强度前10%", "接近阶段高点"], {
                "RPS": round(row["rps"], 2),
                "120日涨幅%": round(row["pct120"], 2),
                "120日高点": round(row["high_120"], 2),
            }, prev_close=row["prev_close"]))
        return items
