from __future__ import annotations

from app.services.strategies.base import (
    LONG_STRATEGY_CANDIDATE_LIMIT,
    STRATEGY_CANDIDATE_LIMIT,
    BaseStrategy,
    DailyPoint,
)
from app.services.strategies.high_tight_flag import HighTightFlagStrategy
from app.services.strategies.limit_up_shakeout import LimitUpShakeoutStrategy
from app.services.strategies.ma_volume import MaVolumeStrategy
from app.services.strategies.rps_breakout import RpsBreakoutStrategy
from app.services.strategies.turtle_breakout import TurtleBreakoutStrategy
from app.services.strategies.uptrend_limit_down import UptrendLimitDownStrategy


STRATEGIES: list[BaseStrategy] = [
    TurtleBreakoutStrategy(),
    MaVolumeStrategy(),
    RpsBreakoutStrategy(),
    HighTightFlagStrategy(),
    LimitUpShakeoutStrategy(),
    UptrendLimitDownStrategy(),
]

STRATEGY_REGISTRY: dict[str, BaseStrategy] = {strategy.id: strategy for strategy in STRATEGIES}

__all__ = [
    "BaseStrategy",
    "DailyPoint",
    "HighTightFlagStrategy",
    "LimitUpShakeoutStrategy",
    "LONG_STRATEGY_CANDIDATE_LIMIT",
    "MaVolumeStrategy",
    "RpsBreakoutStrategy",
    "STRATEGIES",
    "STRATEGY_CANDIDATE_LIMIT",
    "STRATEGY_REGISTRY",
    "TurtleBreakoutStrategy",
    "UptrendLimitDownStrategy",
]
