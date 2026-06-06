# API 文档

后端 Base URL：`http://localhost:8000/api/v1`
（容器内：`http://backend:8000/api/v1`；通过 nginx 反代后浏览器请求路径仍是 `/api/v1/...`）

交互式 Swagger：`http://localhost:8000/docs`
ReDoc：`http://localhost:8000/redoc`

---

## 目录

1. [认证 `/auth`](#1-认证-auth)
2. [股票数据 `/stock`](#2-股票数据-stock)
3. [筛选器 `/screener`](#3-筛选器-screener)
4. [千问 AI `/qwen`](#4-千问-ai-qwen)
5. [行情聚合 `/market`](#5-行情聚合-market)
6. [对话历史 `/chat`](#6-对话历史-chat)
7. [通知中心 `/notifications`](#7-通知中心-notifications)
8. [策略回测 `/strategy`](#8-策略回测-strategy)
9. [健康检查 `/health`](#9-健康检查-health)

---

## 鉴权约定

- **公开接口**（无需登录）：`auth/*`、`stock/*`（除 `me/watchlist`）、`screener/*`、`qwen/*`、`market/*`、`strategy/*`、`health/*`
- **登录态接口**（需要 `Authorization: Bearer <token>`）：`auth/me`、`stock/me/watchlist*`、`chat/*`、`notifications/*`

获取 token：见 [`POST /auth/login`](#post-authlogin)。
401 时前端自动跳 `/login` 并清掉本地 token。

---

## 1. 认证 `/auth`

### POST `/auth/register`
注册新用户。

**请求体**（JSON）
```json
{ "username": "alice", "password": "abc12345", "email": "alice@example.com" }
```
- `username`: 3-64 字符，唯一
- `password`: 6-64 字符
- `email`: 可选

**响应** `201`
```json
{
  "id": 3, "username": "alice", "email": "alice@example.com",
  "is_active": true, "created_at": "2026-04-30T20:17:42"
}
```
**错误** `400` 用户名已被占用。

**示例**
```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"abc12345"}'
```

---

### POST `/auth/login`
登录获取 JWT。**注意请求体是 form-encoded**（OAuth2 标准）。

**请求体**（`application/x-www-form-urlencoded`）
- `username=alice&password=abc12345`

**响应** `200`
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "user": { "id": 3, "username": "alice", "email": null, "is_active": true, "created_at": "..." }
}
```
**错误** `401` 用户名或密码错误。

**示例**
```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d 'username=alice&password=abc12345'
```

---

### GET `/auth/me` 🔒
获取当前登录用户信息。

**响应** `200` 同 `UserOut`。
**错误** `401` token 无效或过期。

---

## 2. 股票数据 `/stock`

### GET `/stock/search?q={kw}&limit=20`
按代码或名称模糊搜索。

**Query**
- `q`: 关键词（必填，1+ 字符）
- `limit`: 默认 20，1-100

**响应** `200`
```json
[
  { "code": "600000.SH", "name": "浦发银行", "industry": "银行", "market": "主板" },
  { "code": "600036.SH", "name": "招商银行", "industry": "银行", "market": "主板" }
]
```

**示例**
```bash
curl 'http://localhost:8000/api/v1/stock/search?q=招商'
```

---

### GET `/stock/{code}`
个股详情：基本信息 + 最新行情 + 最新财务摘要 + 涨跌幅（vs 上一交易日收盘）。

`code` 格式：`600519.SH` / `000651.SZ` / `920175.BJ`

**响应** `200`
```json
{
  "code": "600519.SH",
  "name": "贵州茅台",
  "industry": "白酒",
  "latest": {
    "code": "600519.SH", "trade_date": "2026-05-01",
    "open": 1400.0, "high": 1401.17, "low": 1380.0, "close": 1384.79,
    "volume": 5275270.0, "pe": 20.965, "pb": 6.402,
    "market_cap": 17341.3, "dividend_yield": 3.729, "turnover": 0.42
  },
  "prev_close": 1389.5,
  "change_pct": -0.34,
  "roe": 10.57,
  "revenue_yoy": 6.336,
  "profit_yoy": 1.471,
  "gross_margin": 89.76,
  "debt_ratio": 12.12
}
```
**错误** `404` 股票不存在。

---

### GET `/stock/{code}/kline?days=120`
最近 N 个交易日 OHLCV。本地数据不足时会**自动从 AKShare 回填**一次。

**Query**
- `days`: 默认 120，建议 5 / 30 / 80 / 120 / 240 / 480

**响应** `200`（时间倒序）
```json
[
  { "code": "600519.SH", "trade_date": "2026-05-01", "open": 1400.0, "high": 1401.17, "low": 1380.0, "close": 1384.79, "volume": 5275270.0, "pe": 20.96, "pb": 6.40, "market_cap": 17341.3 },
  { "code": "600519.SH", "trade_date": "2026-04-30", "open": 1395.0, ... }
]
```

---

### GET `/stock/me/watchlist` 🔒
列出当前用户的自选股 + 预警规则。

**响应** `200`
```json
[
  {
    "id": 12, "code": "600519.SH", "note": "长期跟踪",
    "ref_price": 1389.50,
    "alerts": [
      { "id": "a1b2", "type": "pct_down", "threshold": 5, "enabled": true, "lastTriggered": null }
    ]
  }
]
```

---

### POST `/stock/me/watchlist` 🔒
加自选 / upsert（同 code 已存在则更新 note + alerts）。

**请求体**
```json
{
  "code": "600519.SH",
  "note": "长期跟踪",
  "ref_price": 1389.50,
  "alerts": [{ "id": "a1b2", "type": "pct_down", "threshold": 5, "enabled": true }]
}
```

**预警类型**
- `pct_up` / `pct_down`：相比 `ref_price` 累计涨/跌 ≥ threshold%
- `price_gt` / `price_lt`：现价突破 threshold（绝对价）
- `day_pct`：当日相对今开 ±threshold%

**响应** `201` 返回创建/更新后的对象。

---

### DELETE `/stock/me/watchlist/{code}` 🔒
删除自选股。**响应** `204` 无 body。

---

## 3. 筛选器 `/screener`

### POST `/screener`
多条件筛选，立即返回。

**请求体**
```json
{
  "conditions": [
    { "field": "industry", "op": "eq", "value": "银行" },
    { "field": "dividend_yield", "op": "gt", "value": 4 }
  ],
  "logic": "AND",
  "sort_by": "dividend_yield",
  "sort_desc": true,
  "limit": 10
}
```

**支持字段**：`pe / pb / roe / market_cap / dividend_yield / revenue_yoy / profit_yoy / gross_margin / debt_ratio / industry / market / close / turnover`

**操作符**：`gt | gte | lt | lte | eq | between | in`
- `between` → value 传 `[低, 高]`
- `in` → value 传字符串数组（仅 `industry / market`）

**响应** `200`
```json
{
  "total": 24,
  "items": [
    { "code": "601166.SH", "name": "兴业银行", "industry": "银行", "market": "主板",
      "pe": 4.896, "pb": 0.456, "roe": null, "market_cap": 3794.5,
      "dividend_yield": 9.063, "close": 17.93 }
  ],
  "parsed_conditions": null,
  "explanation": null
}
```
**错误** `400` 不支持的字段或操作符。

---

### POST `/screener/nl`
自然语言筛选（千问解析 → 引擎执行），**一次性返回**。

**请求体**
```json
{ "query": "低估值高分红的银行股，按股息率排序" }
```

**响应** `200`：同 `POST /screener`，**但 `parsed_conditions` 字段会回显** 千问解析出的结构化条件。

**错误** `503` AI 服务不可达；`400` 千问解析的条件无效。

---

### POST `/screener/nl/stream` ⚡
自然语言筛选 **SSE 流式版本**。Chat Agent 是 bounded ReAct：普通支持字段筛选会先让模型选择一个白名单工具；只有模型返回通过 schema 校验的工具 action，后端才执行本地工具并生成 observation。纯问候/缺少条件的澄清请求、明确“先别执行”的策略设计请求，以及 unsupported metric 会在模型前本地处理；模型慢、超时、上游不可达或没有给出合法 action 时，后端返回普通回复，不自动筛选，并保留计时和原因。

**协议**：每帧 `data: {json}\n\n`，`payload.type` ∈
| type | 含义 | 字段 |
|---|---|---|
| `thinking` | 前端可展示的公开进度文本 | `text` |
| `planning` | Agent 计划元数据 | `plan, conditions, tool_calls, react_steps, timings` |
| `react_step` | 模型选择下一步 | `step_index, tool, model_ms, public_summary` |
| `tool_start` | 后端开始执行本地工具 | `step_index, tool, public_summary` |
| `tool_observation` | 工具 observation 摘要 | `step_index, tool, tool_ms, observation` |
| `tool_done` | 工具执行完成 | `step_index, tool, tool_ms` |
| `final` | ReAct 本轮最终回答步骤 | `step_index, public_summary, fallback_reason` |
| `parsed` | 股票筛选参数已校验 | `conditions, logic, sort_by, sort_desc, limit` |
| `planned` | 策略选股参数已校验 | `plan` |
| `screening` | 本地筛选或策略工具开始执行 | `tool, tool_call` |
| `result` | 命中股票 | `total, items, parsed_conditions` |
| `agent` | 文本型 Agent 结果或策略结果包装 | `plan, answer, tool_calls, result?` |
| `design` | 策略设计结果，不执行筛选 | `plan, answer, conditions` |
| `error` | 出错 | `message` |
| `done` | 流结束 | — |

`model_ms` 表示模型步骤耗时，`tool_ms` 表示本地工具耗时，`fallback_reason` 会说明模型超时、上游不可达、本地快速路径或安全拦截原因；当没有合法工具 action 时，SSE 不会出现 `screening/result`。前端不应展示模型私有思考链，只展示 `public_summary` / `thinking`。

**示例**
```bash
curl -N -X POST http://localhost:8000/api/v1/screener/nl/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "ROE 大于 15 的成长股"}'
```

---

## 4. 千问 AI `/qwen`

### GET `/qwen/analysis/{code}`
让千问基于个股最新基本面生成投资分析（**一次性返回**，结果会 Redis 缓存 1 小时）。

**响应** `200`
```json
{
  "code": "600519.SH",
  "analysis": "投资亮点：贵州茅台凭借在白酒行业的龙头地位...\n\n主要风险：...\n\n综合评级：推荐",
  "snapshot": {
    "code": "600519.SH", "name": "贵州茅台", "industry": "白酒",
    "pe": 20.96, "pb": 6.40, "market_cap": 17341.3,
    "roe": 10.57, "revenue_yoy": 6.34, "profit_yoy": 1.47,
    "gross_margin": 89.76, "debt_ratio": 12.12, "dividend_yield": 3.73
  }
}
```
**错误** `404` 股票不存在；`503` AI 服务不可达。

---

### GET `/qwen/analysis/{code}/stream` ⚡
SSE 流式版本，逐 token 推送。

**协议**：
| type | 字段 |
|---|---|
| `meta` | `code, snapshot`（首帧即发，UI 可立即渲染上下文） |
| `chunk` | `text`（token 增量） |
| `done` | — |
| `error` | `message` |

**示例**
```bash
curl -N http://localhost:8000/api/v1/qwen/analysis/600519.SH/stream
```

---

## 5. 行情聚合 `/market`

### GET `/market/indices`
4 大指数（上证、深证、创业板、科创50）的实时点位 + 30 日 sparkline。

**响应** `200`
```json
[
  {
    "name": "上证指数", "code": "SH000001",
    "value": 3186.42, "change": 18.32, "change_pct": 0.58,
    "constituents": 1602,
    "spark": [3142.5, 3155.8, 3160.2, ...]
  }
]
```
数据源：AKShare `stock_zh_index_daily`，Redis 缓存 1 小时。

---

### GET `/market/sectors?limit=8`
板块涨跌榜（按行业聚合 DB 内股票的涨跌幅）。

**响应** `200`
```json
[
  { "name": "半导体", "change_pct": 3.42, "count": 18, "leader_name": "中芯国际", "leader_pct": 5.55 },
  { "name": "银行", "change_pct": -0.31, "count": 24, "leader_name": "招商银行", "leader_pct": 0.42 }
]
```

---

### GET `/market/movers?limit=8`
涨跌榜 / 成交额 / 换手率四个 tab，**一次性返回** 前端切换零延迟。

**响应** `200`
```json
{
  "gainers":     [{ "code": "300750.SZ", "name": "宁德时代", "industry": "电池", "close": 245.30, "change_pct": 4.32, "change": 10.15, "amount": 8.2, "turnover": 1.42, "pe": 28.4, "market_cap": 10380 }],
  "losers":      [...],
  "by_amount":   [...],
  "by_turnover": [...]
}
```

---

### GET `/market/ticker`
Dashboard 顶部 Ticker 条用的聚合数据。

**响应** `200`
```json
{
  "indices": [...],                  // 同 /market/indices
  "total_amount_yi": 8421,           // 全市场总成交额（亿元）
  "advancers": 3215,                 // 上涨家数
  "decliners": 2287,                 // 下跌家数
  "trade_date": "2026-05-01"
}
```

---

## 6. 对话历史 `/chat` 🔒

### GET `/chat/sessions?limit=50`
按时间倒序返回当前用户最近 N 条 NL 筛选历史。

**响应** `200`
```json
[
  {
    "id": 18,
    "query": "低估值高分红的银行股",
    "parsed_conditions": [
      { "field": "industry", "op": "eq", "value": "银行" },
      { "field": "dividend_yield", "op": "gt", "value": 3 }
    ],
    "items": [{ "code": "601166.SH", "name": "兴业银行", "pe": 4.9, "dividend_yield": 9.06, ... }],
    "total": 24,
    "screen_meta": { "logic": "AND", "sort_by": "dividend_yield", "sort_desc": true, "limit": 50 },
    "created_at": "2026-05-01T03:42:11"
  }
]
```

---

### POST `/chat/sessions`
保存一条历史（用户成功跑完一次 NL 筛选时由前端自动调）。**超过 50 条时自动删最旧**。

**请求体**（同 `ChatSessionOut`，但不含 `id / created_at`）
```json
{
  "query": "低估值高分红的银行股",
  "parsed_conditions": [...],
  "items": [...],
  "total": 24,
  "screen_meta": {...}
}
```

**响应** `201` 返回创建后的对象。

---

### DELETE `/chat/sessions/{id}`
删除单条历史。`204` 无 body。**错误** `404`。

### DELETE `/chat/sessions`
清空当前用户所有历史。`204` 无 body。

---

## 7. 通知中心 `/notifications` 🔒

### GET `/notifications?limit=100`
按 `fired_at` 倒序返回通知。

**响应** `200`
```json
[
  {
    "id": 8, "kind": "alert", "tone": "up",
    "stock_code": "600519.SH",
    "title": "贵州茅台 已上涨 5.2%",
    "desc": "自加入自选时 1320 → 现价 1389，触发 pct_up=5",
    "fired_at": "2026-05-01T14:32:00",
    "dismissed_at": null
  }
]
```

---

### POST `/notifications`
创建一条通知（前端 alertEngine 触发时调）。**超过 100 条自动删最旧**。

**请求体**
```json
{
  "kind": "alert",
  "tone": "up",
  "stock_code": "600519.SH",
  "title": "贵州茅台 已上涨 5.2%",
  "desc": "..."
}
```
- `kind`: `alert | info | warn`
- `tone`: `up | down | qwen | amber`（影响 UI 颜色）

**响应** `201`。

---

### POST `/notifications/{id}/read`
标记已读（设置 `dismissed_at`）。**响应** `200` 返回更新后的对象。

### POST `/notifications/read-all`
全部标记已读。**响应** `204`。

### DELETE `/notifications/{id}`
删除单条。**响应** `204`。

---

## 8. 策略回测 `/strategy`

### POST `/strategy/backtest`
运行策略回测：给定筛选条件 + 时间窗，模拟「按月调仓、等权持有 top N」。

**请求体**
```json
{
  "name": "低估值蓝筹",
  "conditions": [
    { "field": "pe", "op": "lt", "value": 12 },
    { "field": "pb", "op": "lt", "value": 1.5 },
    { "field": "roe", "op": "gt", "value": 10 }
  ],
  "sort_by": "roe",
  "sort_desc": true,
  "holdings_count": 10,
  "weighting": "equal",
  "start_date": "2024-05-01",
  "end_date": "2026-05-01",
  "initial_capital": 1000000,
  "rebalance": "monthly",
  "transaction_cost": 0.003,
  "stop_loss": -0.15
}
```

**响应** `200`
```json
{
  "name": "低估值蓝筹",
  "universe": ["600519.SH", "000858.SZ", ...],
  "universe_names": ["贵州茅台", "五粮液", ...],
  "equity": [
    { "date": "2024-05-01", "value": 1000000, "pct": 0 },
    { "date": "2024-05-02", "value": 1003200, "pct": 0.32 }
  ],
  "benchmark": [...],
  "trades": [
    { "date": "2024-05-01", "side": "BUY", "code": "600519.SH", "name": "贵州茅台", "price": 1320.5, "qty": 75, "pnl": null, "trigger": "init" },
    { "date": "2024-06-01", "side": "SELL", "code": "600519.SH", "name": "贵州茅台", "price": 1389.0, "qty": 75, "pnl": 5137.5, "holding_days": 31, "trigger": "rebalance" }
  ],
  "metrics": {
    "total_return": 0.184,        // 18.4%
    "annual_return": 0.092,
    "max_drawdown": -0.082,
    "sharpe": 1.23,
    "volatility": 0.165,
    "win_rate": 0.68,
    "profit_loss_ratio": 1.85,
    "total_trades": 47,
    "benchmark_return": 0.124
  },
  "monthly_returns": [
    { "year": 2024, "month": 5, "pct": 0.018 },
    { "year": 2024, "month": 6, "pct": -0.012 }
  ],
  "data_source": "mixed",
  "notes": ["3 只标的历史 < 30 天，已用确定性合成数据填充"]
}
```

**`data_source` 取值**
- `real`：所有标的历史 K 线齐全
- `synthesized`：全部标的都缺数据，用确定性高斯游走合成
- `mixed`：部分真实 + 部分合成（绝大多数情况）

**错误** `400` 参数无效（如 `start_date >= end_date`）。

---

## 9. 健康检查 `/health`

### GET `/health/ai`
探测上游 AI 是否可用（前端启动时调一次）。

**响应** `200`
```json
{
  "ok": true,
  "latency_ms": 8349,
  "reason": null,
  "backend": "openai",
  "model": "qwen3.6-plus",
  "configured": true,
  "fallback": false,
  "mode": "ai_agent"
}
```
或
```json
{
  "ok": false,
  "latency_ms": null,
  "reason": "上游网络不可达",
  "configured": true,
  "fallback": true,
  "mode": "local_fallback"
}
```

缓存未命中且正在后台探测时会快速返回，不阻塞页面：
```json
{
  "ok": true,
  "latency_ms": null,
  "reason": "AI 健康检测中，暂不阻塞页面",
  "backend": "openai",
  "model": "qwen3.6-plus",
  "configured": true,
  "fallback": false,
  "mode": "ai_agent",
  "pending": true
}
```

若已有过期探测结果，接口会带 `stale=true` 返回旧状态，同时后台刷新真实结果。AI 上游不可达时，Chat Agent 不会自动执行筛选工具；UI 应展示 `reason`，不要把失败隐藏成模型可用。

---

### GET `/health/data`
数据健康度：表内行数、全市场行情覆盖、最近一次同步状态和新鲜度诊断。

**响应** `200`
```json
{
  "fresh": true,
  "expected_trade_date": "2026-06-03",
  "latest_trade_date": "2026-06-03",
  "newest_trade_date": "2026-06-03",
  "counts": {
    "basic": 5512,
    "daily": 460945,
    "financial": 5510,
    "with_industry": 5357,
    "latest_daily": 5512,
    "market_coverage_threshold": 2756
  },
  "coverage": {
    "latest_daily": 1.0,
    "latest_valuation": 1.0,
    "financial": 0.9973
  },
  "freshness": {
    "reason_code": "fresh",
    "label": "已最新",
    "severity": "fresh",
    "message": "全市场日线已覆盖到最近应有交易日。",
    "lag_days": 0,
    "expected_basis": "weekday_close_after_16_no_holidays",
    "coverage_threshold": 2756,
    "latest_coverage_rows": 5512,
    "has_sparse_newer_data": false,
    "active_jobs": [],
    "recommended_jobs": []
  },
  "sync_meta": {
    "daily_market": { "last_run_at": "2026-06-03 16:10:08", "status": "success", "duration_ms": 38420, "detail": "" },
    "weekly_kline_backfill": { ... }
  },
  "sync_warnings": [],
  "sync_has_issue": false
}
```

`freshness.reason_code` 常见值：
- `fresh`：全市场覆盖已达到最近应有交易日
- `sync_running`：行情落后但同步任务正在后台执行
- `partial_newer_data`：存在更晚的少量个股数据，但全市场快照仍未覆盖
- `stale`：行情落后，建议运行日线/估值同步

`sync_warnings` 与 `freshness.reason_code` 是两层信息：`fresh=true` 表示全市场日线已覆盖到 `expected_trade_date`，但仍可能存在财务、分红或历史 K 线回填等后台任务异常。交付检查应同时查看 `fresh`、`freshness.message`、`sync_has_issue` 和 `sync_warnings`，不要把同步异常隐藏为“已完全正常”。

---

### GET `/health/cache`
Redis 缓存命中率。

**响应** `200`
```json
{ "enabled": true, "keys": 124, "hits": 3217, "misses": 1085 }
```
未配置 Redis 时：`{ "enabled": false }`

---

### POST `/health/sync/{job_name}?wait=false`
手动触发一个 sync 任务（前端「立即更新」按钮用）。

**Path**：`job_name` ∈ `daily_market | daily_value | weekly_fundamentals | weekly_basic | weekly_kline_backfill | db_backup`

**Query**：
- `wait=false`（默认）：后台守护线程跑，立即返回
- `wait=true`：同步等结果（短任务用，如 `db_backup`）

**响应** `200`
```json
{ "job": "daily_value", "queued": true, "meta": { ... } }
```

---

### GET `/health/backups`
列出 `/app/data/backups/` 下的 SQLite 冷备份文件（时间倒序）。

**响应** `200`
```json
{
  "items": [
    { "name": "stock-20260501-070000.db", "size_mb": 38.4, "mtime": "2026-05-01T07:00:00" }
  ]
}
```

---

## 通用错误格式

FastAPI 标准 `HTTPException` 输出：

```json
{ "detail": "用户名已被占用" }
```

校验错误（pydantic v2）：

```json
{
  "detail": [
    { "type": "value_error", "loc": ["body", "password"],
      "msg": "String should have at least 6 characters", "input": "abc" }
  ]
}
```

**前端 [`shared/errors.js`](../frontend/src/shared/errors.js)** 已经把常见错误码（401 / 429 / 503 / errno 5x）翻译为中文产品文案。

---

## SSE 客户端示例

详见 [`frontend/src/api/sse.js`](../frontend/src/api/sse.js)，核心思路：

```js
const resp = await fetch(url, { headers: { Accept: 'text/event-stream', Authorization: `Bearer ${token}` }})
const reader = resp.body.getReader()
const decoder = new TextDecoder('utf-8')
let buffer = ''
while (true) {
  const { value, done } = await reader.read()
  if (done) break
  buffer += decoder.decode(value, { stream: true })
  // 按 \n\n 切帧，每帧 data: <json>
  ...
}
```

nginx 端必须关掉缓冲（已在 [`frontend/nginx.conf`](../frontend/nginx.conf) 配好）：

```nginx
proxy_buffering    off;
proxy_cache        off;
proxy_read_timeout 1800s;
```
