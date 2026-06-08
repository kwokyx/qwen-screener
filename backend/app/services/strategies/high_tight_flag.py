from __future__ import annotations

import pandas as pd

from app.schemas.strategy import StrategyPickItem
from app.services.strategies.base import BaseStrategy, _item


class HighTightFlagStrategy(BaseStrategy):
    id = "high_tight_flag"
    name = "高位窄幅整理"
    tag = "形态"
    description = "强势整理策略：先强势上涨，再高位缩量窄幅整理。"
    rules = ["40 日内最高/最低涨幅大于 60%", "近 10 日振幅小于 15%", "近 10 日仍处于 40 日高点附近", "当日成交量缩至 20 日均量 60% 以下"]
    history_days = 55

    def run(self, df: pd.DataFrame) -> list[StrategyPickItem]:
        df = df.sort_values(["symbol", "date"]).copy()
        g = df.groupby("symbol", sort=False)

        df["high_40"] = g["high"].rolling(40, min_periods=40).max().values
        df["low_40"] = g["low"].rolling(40, min_periods=40).min().values
        df["high_10"] = g["high"].rolling(10, min_periods=10).max().values
        df["low_10"] = g["low"].rolling(10, min_periods=10).min().values
        df["vol20"] = g["volume"].rolling(20, min_periods=20).mean().values
        df["prev_close"] = g["close"].shift(1).values

        last = df.groupby("symbol", sort=False).tail(1).dropna(
            subset=["high_40", "low_40", "high_10", "low_10", "vol20"]
        )
        if last.empty:
            return []

        last = last.copy()
        last["momentum"] = last["high_40"] / last["low_40"]
        last["consolidation"] = last["high_10"] / last["low_10"]

        mask = (
            (last["momentum"] > 1.6)
            & (last["consolidation"] < 1.15)
            & (last["low_10"] >= last["high_40"] * 0.8)
            & (last["volume"] < last["vol20"] * 0.6)
        )
        hits = last[mask]

        items: list[StrategyPickItem] = []
        for _, row in hits.iterrows():
            score = row["momentum"] * 30 + (1.15 - row["consolidation"]) * 100 + (1 - row["volume"] / row["vol20"]) * 20
            items.append(_item(row, score, ["强动量", "高位窄幅整理", "缩量"], {
                "40日高低比": round(row["momentum"], 2),
                "10日振幅比": round(row["consolidation"], 2),
                "缩量比例": round(row["volume"] / row["vol20"], 2),
            }, prev_close=row["prev_close"]))
        return items
