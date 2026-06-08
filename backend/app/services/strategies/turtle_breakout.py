from __future__ import annotations

from app.schemas.strategy import StrategyPickItem
from app.services.strategies.base import (
    STRATEGY_CANDIDATE_LIMIT,
    BaseStrategy,
    DailyPoint,
    amount_yi,
    base_item,
)


class TurtleBreakoutStrategy(BaseStrategy):
    id = "turtle_breakout"
    name = "海龟突破"
    tag = "突破"
    description = "经典突破策略：突破 20 日高点，成交额过亿，且当日阳线真涨。"
    rules = ["收盘价突破前 20 日最高价", "成交额大于 1 亿元", "收盘价高于开盘价和昨日收盘价"]
    history_days = 35
    max_codes = STRATEGY_CANDIDATE_LIMIT

    def run(self, histories: dict[str, list[DailyPoint]]) -> list[StrategyPickItem]:
        items: list[StrategyPickItem] = []
        for points in histories.values():
            if len(points) < 21:
                continue
            last, prev = points[-1], points[-2]
            if last.close is None or last.open is None or prev.close is None:
                continue
            high20 = max(p.high for p in points[-21:-1] if p.high is not None)
            turnover_yi = amount_yi(last) or 0
            if last.close > high20 and turnover_yi > 1 and last.close > last.open and last.close > prev.close:
                breakout_pct = (last.close / high20 - 1) * 100
                score = 20 + min(50, breakout_pct * 10) + min(30, turnover_yi / 3)
                items.append(base_item(points, score, ["20日新高突破", "成交额过亿", "阳线真涨"], {
                    "20日高点": high20,
                    "突破幅度%": breakout_pct,
                    "成交额(亿)": turnover_yi,
                }))
        return items
