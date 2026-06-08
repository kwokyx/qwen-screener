from __future__ import annotations

from app.schemas.strategy import StrategyPickItem
from app.services.strategies.base import (
    LONG_STRATEGY_CANDIDATE_LIMIT,
    BaseStrategy,
    DailyPoint,
    base_item,
    pct_rank,
)


class RpsBreakoutStrategy(BaseStrategy):
    id = "rps_breakout"
    name = "RPS 强势突破"
    tag = "强势"
    description = "相对强度策略：120 日涨幅横向排名靠前，且价格接近阶段高点。"
    rules = ["120 日涨幅排名进入前 10%", "收盘价接近 120 日最高价", "优先选择相对强度更高的股票"]
    history_days = 130
    max_codes = LONG_STRATEGY_CANDIDATE_LIMIT

    def run(self, histories: dict[str, list[DailyPoint]]) -> list[StrategyPickItem]:
        candidates = []
        for code, points in histories.items():
            if len(points) < 121:
                continue
            first = points[-121]
            last = points[-1]
            if not first.close or not last.close:
                continue
            pct120 = (last.close / first.close - 1) * 100
            high120 = max(p.high for p in points[-120:] if p.high is not None)
            near_high = last.close >= high120 * 0.9
            candidates.append((code, points, pct120, high120, near_high))

        if not candidates:
            return []

        pct_values = [v[2] for v in candidates]
        items: list[StrategyPickItem] = []
        for _code, points, pct120, high120, near_high in candidates:
            rank = pct_rank(pct_values, pct120)
            if rank >= 90 and near_high:
                score = rank * 0.8 + min(100, max(0, pct120)) * 0.2
                items.append(base_item(points, score, ["120日相对强度前10%", "接近阶段高点"], {
                    "RPS": rank,
                    "120日涨幅%": pct120,
                    "120日高点": high120,
                }))
        return items
