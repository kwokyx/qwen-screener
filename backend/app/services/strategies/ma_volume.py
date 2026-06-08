from __future__ import annotations

from app.schemas.strategy import StrategyPickItem
from app.services.strategies.base import (
    STRATEGY_CANDIDATE_LIMIT,
    BaseStrategy,
    DailyPoint,
    avg,
    base_item,
)


class MaVolumeStrategy(BaseStrategy):
    id = "ma_volume"
    name = "均线放量"
    tag = "趋势"
    description = "趋势确认策略：5 日均线上穿 20 日均线，并有成交量放大确认。"
    rules = ["5 日均线上穿 20 日均线", "成交量大于 20 日均量 1.5 倍", "按放量强度和涨幅排序"]
    history_days = 35
    max_codes = STRATEGY_CANDIDATE_LIMIT

    def run(self, histories: dict[str, list[DailyPoint]]) -> list[StrategyPickItem]:
        items: list[StrategyPickItem] = []
        for points in histories.values():
            if len(points) < 21:
                continue
            closes = [p.close for p in points]
            volumes = [p.volume for p in points]
            ma5_prev = avg(closes[-6:-1])
            ma20_prev = avg(closes[-21:-1])
            ma5 = avg(closes[-5:])
            ma20 = avg(closes[-20:])
            vol20 = avg(volumes[-20:])
            last_vol = points[-1].volume
            if None in (ma5_prev, ma20_prev, ma5, ma20, vol20, last_vol):
                continue
            golden_cross = ma5_prev < ma20_prev and ma5 > ma20
            volume_ratio = last_vol / vol20 if vol20 else 0
            if golden_cross and volume_ratio > 1.5:
                score = (ma5 / ma20 - 1) * 100 + volume_ratio * 10
                items.append(base_item(points, score, ["5日均线上穿20日均线", "成交量放大"], {
                    "MA5": ma5,
                    "MA20": ma20,
                    "量比20日": volume_ratio,
                }))
        return items
