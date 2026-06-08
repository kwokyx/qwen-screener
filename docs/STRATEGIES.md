# 内置策略引擎

策略后端是本地规则引擎，不是 AI 算分系统。AI 只负责把明确的自然语言策略意图路由到 `strategy_select`，真正执行由 `backend/app/services/strategies/` 下的策略类完成。

## 代码结构

| 文件 | 职责 |
|---|---|
| `backend/app/services/strategies/base.py` | `BaseStrategy`、`DailyPoint`、通用均值 / 排位 / 命中项构造 helper |
| `backend/app/services/strategies/__init__.py` | 显式注册 `STRATEGIES` 与 `STRATEGY_REGISTRY` |
| `backend/app/services/strategies/*.py` | 每个内置策略一个类，声明 `id/name/tag/description/rules/history_days/max_codes` 并实现 `run(histories)` |
| `backend/app/services/strategy_selector.py` | API 门面、工具元数据、缓存、singleflight、日线数据加载和执行分发 |

新增策略时应新增一个策略类，并在 `strategies/__init__.py` 的显式列表中注册；不要做动态 import。

## 当前策略

| 策略 | 数据来源 | 窗口 | 候选池 | 缺失行为 |
|---|---|---:|---|---|
| 海龟突破 `turtle_breakout` | `stock_daily` OHLCV / amount + `stock_basic` 名称行业 | 35 日 | 最新成交额前 500 只 | 最近窗口 K 线不完整或关键字段缺失则跳过 |
| 均线放量 `ma_volume` | `stock_daily` close / volume + `stock_basic` | 35 日 | 最新成交额前 500 只 | 均线或成交量窗口不完整则跳过 |
| RPS 强势突破 `rps_breakout` | `stock_daily` close / high + `stock_basic` | 130 日 | 最新成交额前 300 只 | 120 日涨幅或高点窗口不足则跳过 |
| 高位窄幅整理 `high_tight_flag` | `stock_daily` high / low / volume + `stock_basic` | 55 日 | 最新成交额前 500 只 | 40 日 / 10 日 / 20 日窗口不足则跳过 |
| 涨停后承接 `limit_up_shakeout` | `stock_daily` OHLCV + `stock_basic` | 3 日 | 全市场最近日线 | 最近 3 根 K 线不完整则跳过 |
| 趋势急跌修复 `uptrend_limit_down` | `stock_daily` close / volume + `stock_basic` | 65 日 | 最新成交额前 300 只 | 20 / 60 日均线或成交量窗口不足则跳过 |

候选池限制是性能边界，不代表全市场回测。接口返回的 `notes` 会说明当前策略是否限制在流动性股票池内。

## 命中强度

后端响应中的 `score` 字段保留用于 API 兼容，但产品语义是“命中强度”或“策略排序值”：

- 只用于当前策略内部排序。
- 不代表投资评级。
- 不用于不同策略之间横向比较。
- 不能被展示成统一股票价值分。

若后续要恢复统一评分，需要新增独立、可解释的数据来源和测试，不应复用策略内部排序值。
