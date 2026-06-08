from __future__ import annotations

import pandas as pd

from app.schemas.strategy import StrategyPickItem
from app.services.strategies.base import BaseStrategy, _item


class LimitUpShakeoutStrategy(BaseStrategy):
    id = "limit_up_shakeout"
    name = "涨停后承接"
    tag = "短线"
    description = "涨停次日承接策略：昨日接近涨停，今日放量收阴但低点不破昨日收盘。"
    rules = ["昨日收盘价较前日上涨至少 9.5%", "今日收阴线", "今日成交量大于昨日 2 倍", "今日最低价不低于昨日收盘价"]
    history_days = 3

    def run(self, df: pd.DataFrame) -> list[StrategyPickItem]:
        df = df.sort_values(["symbol", "date"]).copy()
        g = df.groupby("symbol", sort=False)

        df["prev_close"] = g["close"].shift(1)
        df["prev2_close"] = g["close"].shift(2)
        df["prev_volume"] = g["volume"].shift(1)

        last = df.groupby("symbol", sort=False).tail(1).dropna(
            subset=["prev_close", "prev2_close", "prev_volume", "open", "low", "close", "volume"]
        )
        if last.empty:
            return []

        mask = (
            (last["prev_close"] >= last["prev2_close"] * 1.095)
            & (last["close"] < last["open"])
            & (last["volume"] > last["prev_volume"] * 2.0)
            & (last["low"] >= last["prev_close"])
        )
        hits = last[mask]

        items: list[StrategyPickItem] = []
        for _, row in hits.iterrows():
            limit_up_pct = (row["prev_close"] / row["prev2_close"] - 1) * 100
            volume_ratio = row["volume"] / row["prev_volume"]
            support_gap = (row["low"] / row["prev_close"] - 1) * 100
            score = (
                35
                + min(25, max(0, limit_up_pct - 9.5) * 20)
                + min(30, volume_ratio * 8)
                + min(10, max(0, support_gap) * 10)
            )
            items.append(_item(row, score, ["昨日强势涨停", "今日放量收阴", "支撑不破"], {
                "昨日涨幅%": round(limit_up_pct, 2),
                "今日量比昨日": round(volume_ratio, 2),
                "支撑距离%": round(support_gap, 2),
            }, prev_close=row["prev_close"]))
        return items
