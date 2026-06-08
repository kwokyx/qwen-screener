from __future__ import annotations

from app.schemas.strategy import StrategyPickItem
from app.services.strategies.base import (
    STRATEGY_CANDIDATE_LIMIT,
    BaseStrategy,
    DailyPoint,
    avg,
    base_item,
)


class HighTightFlagStrategy(BaseStrategy):
    id = "high_tight_flag"
    name = "高位窄幅整理"
    tag = "形态"
    description = "强势整理策略：先强势上涨，再高位缩量窄幅整理。"
    rules = ["40 日内最高/最低涨幅大于 60%", "近 10 日振幅小于 15%", "近 10 日仍处于 40 日高点附近", "当日成交量缩至 20 日均量 60% 以下"]
    history_days = 55
    max_codes = STRATEGY_CANDIDATE_LIMIT

    def run(self, histories: dict[str, list[DailyPoint]]) -> list[StrategyPickItem]:
        items: list[StrategyPickItem] = []
        for points in histories.values():
            if len(points) < 40:
                continue
            tail40 = points[-40:]
            tail10 = points[-10:]
            high40 = max(p.high for p in tail40 if p.high is not None)
            low40 = min(p.low for p in tail40 if p.low is not None)
            high10 = max(p.high for p in tail10 if p.high is not None)
            low10 = min(p.low for p in tail10 if p.low is not None)
            vol20 = avg([p.volume for p in points[-21:-1]])
            last_vol = points[-1].volume
            if not low40 or not low10 or not vol20 or last_vol is None:
                continue
            momentum = high40 / low40
            consolidation = high10 / low10
            high_level = low10 >= high40 * 0.8
            shrink = last_vol < vol20 * 0.6
            if momentum > 1.6 and consolidation < 1.15 and high_level and shrink:
                score = momentum * 30 + (1.15 - consolidation) * 100 + (1 - last_vol / vol20) * 20
                items.append(base_item(points, score, ["强动量", "高位窄幅整理", "缩量"], {
                    "40日高低比": momentum,
                    "10日振幅比": consolidation,
                    "缩量比例": last_vol / vol20,
                }))
        return items
