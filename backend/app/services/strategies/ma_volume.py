from __future__ import annotations

import pandas as pd

from app.schemas.strategy import StrategyPickItem
from app.services.strategies.base import BaseStrategy, _item


class MaVolumeStrategy(BaseStrategy):
    id = "ma_volume"
    name = "均线放量"
    tag = "趋势"
    description = "趋势确认策略：5 日均线上穿 20 日均线，并有成交量放大确认。"
    rules = ["5 日均线上穿 20 日均线", "成交量大于 20 日均量 1.5 倍", "按放量强度和涨幅排序"]
    history_days = 35

    def run(self, df: pd.DataFrame) -> list[StrategyPickItem]:
        df = df.sort_values(["symbol", "date"]).copy()
        g = df.groupby("symbol", sort=False)

        df["ma5"] = g["close"].rolling(5, min_periods=5).mean()
        df["ma20"] = g["close"].rolling(20, min_periods=20).mean()
        df["vol20"] = g["volume"].rolling(20, min_periods=20).mean()
        df["ma5_prev"] = g["ma5"].shift(1)
        df["ma20_prev"] = g["ma20"].shift(1)
        df["prev_close"] = g["close"].shift(1)

        last = df.groupby("symbol", sort=False).tail(1)
        mask = (
            last["ma5_prev"].notna()
            & last["ma20_prev"].notna()
            & last["ma5"].notna()
            & last["ma20"].notna()
            & last["vol20"].notna()
            & (last["ma5_prev"] < last["ma20_prev"])
            & (last["ma5"] > last["ma20"])
            & (last["volume"] > last["vol20"] * 1.5)
        )
        hits = last[mask]

        items: list[StrategyPickItem] = []
        for _, row in hits.iterrows():
            volume_ratio = row["volume"] / row["vol20"]
            score = (row["ma5"] / row["ma20"] - 1) * 100 + volume_ratio * 10
            items.append(_item(row, score, ["5日均线上穿20日均线", "成交量放大"], {
                "MA5": round(row["ma5"], 2),
                "MA20": round(row["ma20"], 2),
                "量比20日": round(volume_ratio, 2),
            }, prev_close=row["prev_close"]))
        return items
