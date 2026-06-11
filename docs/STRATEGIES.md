# 内置策略引擎

策略后端是本地规则引擎，不是 AI 算分系统。AI 只负责把明确的自然语言策略意图路由到 `strategy_select`，真正执行由 `backend/app/services/strategies/` 下的策略类完成。

## 代码结构

| 文件 | 职责 |
|---|---|
| `backend/app/services/strategies/base.py` | `BaseStrategy` 与命中项构造 helper |
| `backend/app/services/strategies/__init__.py` | 显式注册 `STRATEGIES` 与 `STRATEGY_REGISTRY` |
| `backend/app/services/strategies/*.py` | 每个内置策略一个类，声明 `id/name/tag/description/rules/history_days` 并实现 `run(df)` |
| `backend/app/services/strategy_selector.py` | API 门面、工具元数据、缓存、singleflight、日线数据加载和执行分发 |

新增策略时应新增一个策略类，并在 `strategies/__init__.py` 的显式列表中注册；不要做动态 import。

## 执行范围

当前策略不是“先取成交额前 300 / 500 只再计算”。真实执行流程是：

```text
/strategy/select
  -> run_strategy_selection
  -> 根据策略 history_days 读取最近 N 个交易日
  -> 从 stock_daily + stock_basic 加载全市场日线 DataFrame
  -> 过滤 K 线窗口不完整、close/high/low 缺失、volume <= 0 的股票
  -> 调用具体策略类 run(df)
  -> 按策略内部 score 排序
  -> 根据接口 limit 截断返回
```

也就是说，`limit` 只控制返回条数，不控制参与计算的股票池。海龟突破里的“成交额大于 1 亿元”是策略条件本身，不是候选池裁剪。

## 当前策略

| 策略 | 数据来源 | 窗口 | 扫描范围 | 缺失行为 |
|---|---|---:|---|---|
| 海龟突破 `turtle_breakout` | `stock_daily` OHLCV / amount + `stock_basic` 名称行业 | 35 日 | 全市场最近 35 个交易日完整 K 线 | 最近窗口 K 线不完整或关键字段缺失则跳过 |
| 均线放量 `ma_volume` | `stock_daily` close / volume + `stock_basic` | 35 日 | 全市场最近 35 个交易日完整 K 线 | 均线或成交量窗口不完整则跳过 |
| RPS 强势突破 `rps_breakout` | `stock_daily` close / high + `stock_basic` | 130 日 | 全市场最近 130 个交易日完整 K 线 | 120 日涨幅或高点窗口不足则跳过 |
| 高位窄幅整理 `high_tight_flag` | `stock_daily` high / low / volume + `stock_basic` | 55 日 | 全市场最近 55 个交易日完整 K 线 | 40 日 / 10 日 / 20 日窗口不足则跳过 |
| 涨停后承接 `limit_up_shakeout` | `stock_daily` OHLCV + `stock_basic` | 3 日 | 全市场最近 3 个交易日完整 K 线 | 最近 3 根 K 线不完整则跳过 |
| 趋势急跌修复 `uptrend_limit_down` | `stock_daily` close / volume + `stock_basic` | 65 日 | 全市场最近 65 个交易日完整 K 线 | 20 / 60 日均线或成交量窗口不足则跳过 |

策略选择是“当前条件命中扫描”，不是收益回测。接口返回的 `notes` 会说明策略基于本地日线数据实时计算，不代表买卖建议。

## 和逐只扫描实现的关系

本项目的策略条件参考了常见的全市场日线扫描思路，但实现方式是批量化的：

| 实现方式 | 说明 |
|---|---|
| 逐只扫描 | 对每只股票分别读取 K 线，再执行策略判断 |
| 本项目批量扫描 | 一次 SQL 读出最近 N 日全市场数据，组成 DataFrame 后按 `symbol` 分组计算 |

两种方式的策略含义接近，区别在工程实现。本项目这样做是为了减少数据库往返次数，并方便 RPS 这类需要横向排名的策略。

如果后续遇到性能瓶颈，可以新增显式的流动性预筛选，例如“最新成交额前 N 只”，但需要在代码、接口 notes 和文档中同时说明，不能只在文档里写。

## 命中强度

后端响应中的 `score` 字段保留用于 API 兼容，但产品语义是“命中强度”或“策略排序值”：

- 只用于当前策略内部排序。
- 不代表投资评级。
- 不用于不同策略之间横向比较。
- 不能被展示成统一股票价值分。

若后续要恢复统一评分，需要新增独立、可解释的数据来源和测试，不应复用策略内部排序值。
