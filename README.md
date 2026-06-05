# 基于千问的股票筛选系统

- 哪些功能做完了、哪些没做：[docs/STATUS.md](docs/STATUS.md)
- 接口怎么调：[docs/API.md](docs/API.md)
- 许可证：[MIT](LICENSE)

---

FastAPI 后端 + Vue 3 前端，集成大模型实现「自然语言筛选 + 基本面投资分析」，支持沪深 300/500 行情、财务、行业数据的离线同步与定时刷新。

```
浏览器 (Vue 3 SPA)
   │ /api/* via nginx 反代
   ▼
FastAPI 后端  ──┬──  SQLite / MySQL（行情 / 财务 / 用户 / 自选 / 对话历史）
                ├──  Redis 缓存（千问解析结果、个股分析）
                ├──  Baostock（全 A 基础信息、K 线、财务、分红）+ AKShare 少量兜底
                └──  AI 后端：OpenAI 兼容（默认） / 阿里云百炼千问（备用）
```

---

## 功能一览

| 模块 | 路径 | 说明 |
|---|---|---|
| 行情 Dashboard | `/dashboard` | 大盘指数、行业涨跌、Top 涨/跌幅 |
| 千问对话筛选 | `/chat` | 自然语言输入 → 千问解析为结构化条件 → SSE 流式返回 |
| 因子筛选器 | `/results` | 13 字段 × 7 操作符的可组合筛选 |
| 个股详情 | `/detail/:code` | K 线 + 关键指标 + 千问基本面分析（流式） |
| 自选监控 | `/portfolio` | 自选股 + 价格预警，登录后跨设备同步 |
| 智能选股工作台 | `/strategy` | 自然语言 Agent → 本地筛选工具；支持结构化条件与内置策略 |

> 完整 API 接口文档见 [`docs/API.md`](docs/API.md)，含所有端点的 curl 示例与响应样本。

---

## 技术栈

### 后端（Python 3.10+）
- **FastAPI 0.115** + Uvicorn + SQLAlchemy 2.0 + Pydantic v2
- **APScheduler** 定时任务（每日收盘后行情、周末财务回填、6h 一次 SQLite 冷备份）
- **Baostock 优先** 数据源（全 A 基础信息、日 K、周/月 K、分钟 K、财务与分红；AKShare 仅保留少量兜底）
- **OpenAI SDK + dashscope** 双 AI 后端，可一键切换
- **Redis**（可选）缓存千问解析结果

### 前端（Node 20+）
- **Vue 3.5** + Vite + Vue Router 4 + Pinia 2
- Naive UI 浅色金融终端主题 + IBM Plex 字体 + klinecharts K 线图（Sparkline 保留用于小趋势图）
- Axios（普通请求） + fetch + ReadableStream（SSE 流式）
- `marked` 渲染千问输出的 Markdown

### 部署
- Docker Compose（backend + redis + frontend nginx）
- Nginx SSE 反代（`proxy_buffering off` + 30 分钟超时）

---

## 快速开始

### 方式 A：Docker Compose 一键起（推荐）

```bash
# 1. 配置环境变量
cp backend/.env.example backend/.env
# 编辑 backend/.env，至少填一项 AI 后端：
#   - OPENAI_API_KEY  （默认走 OpenCode Go/Qwen OpenAI 兼容网关）
#   - 或 AI_BACKEND=dashscope + DASHSCOPE_API_KEY  （阿里云百炼）

# 2. 启动全栈
docker compose up -d --build

# 3. 首次拉数据（容器内执行）
docker exec qwen-backend python -m scripts.sync_data full

# 4. 浏览器打开
#    前端：http://localhost:8080
#    后端 API 文档（直连调试）：先在 docker-compose.yml 解开 ports 8001 → 8000
```

### 方式 B：本地开发模式

需要本机有 Python 3.10、Node 20、MySQL 或保留 SQLite 默认。

```bash
# === 后端 ===
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                            # 填入 AI Key
python -m scripts.sync_data full                # 首次拉数据（~5 分钟）
uvicorn app.main:app --reload --port 8000

# === 前端（新开一个 terminal）===
cd frontend
npm install                                     # 或 pnpm install
npm run dev                                     # → http://localhost:5173
```

`vite.config.js` 已配置 `/api` 代理到 `http://127.0.0.1:8000`，开发模式直接同源调用。

---

## 配置项（`backend/.env`）

| 变量 | 默认 | 说明 |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./stock.db` | 改 MySQL：`mysql+pymysql://user:pass@host:3306/db?charset=utf8mb4` |
| `REDIS_URL` | `redis://localhost:6379/0` | 留空则禁用缓存（业务不中断） |
| `BAOSTOCK_INTRADAY_TIMEOUT` | `6` | 分钟 K 首次拉取的最长等待秒数 |
| `BAOSTOCK_INTRADAY_BREAKER_SECONDS` | `300` | 分钟 K 拉取失败后的短路秒数，避免页面反复阻塞 |
| `BAOSTOCK_SYNC_WORKERS` | `4` | 全市场日线回填并发数；过高会增加免费数据源抖动 |
| `BAOSTOCK_BATCH_TIMEOUT` | `90` | 单批日线回填最长等待秒数，超时后保留已提交批次 |
| `QUOTE_TIMEOUT` | `0.8` | 详情页实时行情 provider 单次 HTTP 超时 |
| `QUOTE_REQUEST_BUDGET` | `0.35` | 详情页等待实时行情的页面请求预算；超时后立即使用本地日线回退 |
| `QUOTE_FAILURE_TTL` | `30` | 实时行情失败缓存秒数，避免重复打慢上游 |
| `QUOTE_CIRCUIT_FAILURES` / `QUOTE_CIRCUIT_SECONDS` | `3` / `60` | 实时行情连续失败后的短期熔断 |
| `SECRET_KEY` | dev-secret | JWT 签名密钥，生产必须改 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 1440 | JWT 有效期 |
| **`AI_BACKEND`** | `openai` | `openai` 或 `dashscope` |
| `OPENAI_API_KEY` | — | OpenAI 或兼容网关的 Key |
| `OPENAI_BASE_URL` | `https://opencode.ai/zen/go/v1` | OpenCode Go 的 OpenAI 兼容接口；也可换成官方或自建兼容网关 |
| `OPENAI_MODEL` | `qwen3.6-plus` | OpenCode Go 当前示例模型 |
| `OPENAI_REASONING` | `high` | Responses API reasoning effort（Chat Completions 兼容模式不会使用） |
| `OPENAI_RESPONSES_ENABLED` | `false` | OpenCode Go/Qwen 走 Chat Completions 时保持关闭，避免先探测不支持的 Responses API |
| `DASHSCOPE_API_KEY` | — | 阿里云百炼 Key（[控制台](https://bailian.console.aliyun.com)） |
| `QWEN_MODEL` | `qwen-plus` | dashscope 模型 |
| `CORS_ORIGINS` | `http://localhost:5173` | 多个用逗号分隔 |

> **AI 后端两种配法选其一即可**。OpenCode Go 属于 OpenAI-compatible Chat Completions 网关，因此 `AI_BACKEND=openai`、`OPENAI_RESPONSES_ENABLED=false`。不要把真实 Key 提交进仓库。

---

## 数据同步命令

```bash
python -m scripts.sync_data <子命令> [参数]
```

| 子命令 | 数据源 | 内容 | 耗时 |
|---|---|---|---|
| `basic` | Baostock | 全 A 股 5500+ 代码 + 名称 | 几秒 |
| `daily [days]` | Baostock | 全市场日 K（OHLCV + PE/PB + 换手率） | 视回填天数而定 |
| `kline [code] [days]` | Baostock | 单只股票日 K 回填 | 几秒 |
| `financial [pool]` | Baostock | ROE / 营收同比 / 净利同比 / 毛利率 / 负债率 | 视股票池而定 |
| `dividend [code]` | Baostock | 已实施现金分红 + 本地计算近 12 个月股息率 | 视股票池而定 |
| `full` | Baostock | 基本信息 + 日 K + 全市场财务 + 全市场分红 | 较长任务 |

支持的股票池：`csi300`（沪深300）、`csi500`（中证500）、`sse50`（上证50）。

启动后会**自动定时刷新**，无需手动重跑（见下方「定时任务」）。

---

## API 概览（前缀 `/api/v1`）

完整 Swagger 文档在 `http://localhost:8000/docs`。

```
auth/               注册 / 登录 / me
stock/              搜索 / 详情 / K线 / 自选股 CRUD
screener/           POST  /screener        多条件筛选
                    POST  /screener/nl     自然语言（一次返回）
                    POST  /screener/nl/stream  自然语言（SSE 流式）
qwen/               GET   /qwen/analysis/{code}            一次返回
                    GET   /qwen/analysis/{code}/stream     SSE 流式
market/             指数 / 板块 / 涨跌幅榜 / Ticker
chat/               对话历史 CRUD（登录后跨设备同步）
notifications/      预警通知中心
strategy/           Agent 智能选股 / 条件筛选 / 内置策略选股
health/             AI 探活 / 数据健康度 / 缓存命中率 / 手动触发同步
```

支持的筛选字段：
| 字段 | 含义 | 表 |
|---|---|---|
| `pe` / `pb` | 市盈率 / 市净率 | `stock_daily` |
| `market_cap` | 总市值（亿） | `stock_daily` |
| `close` / `turnover` / `dividend_yield` | 价格 / 换手率 / 股息率 % | `stock_daily` |
| `roe` | 净资产收益率 % | `stock_financial` |
| `revenue_yoy` / `profit_yoy` | 营收 / 净利同比 % | `stock_financial` |
| `gross_margin` / `debt_ratio` | 毛利率 / 资产负债率 % | `stock_financial` |
| `industry` / `market` | 行业 / 板块 | `stock_basic` |

操作符：`gt / gte / lt / lte / eq / between / in`

完整字段能力、缺失行为和不支持指标原因见 [`docs/FIELD_CAPABILITIES.md`](docs/FIELD_CAPABILITIES.md)。

---

## 定时任务（APScheduler，东八区）

| Cron | 任务 | 内容 |
|---|---|---|
| 周一-周五 15:30 | `daily_market` | 全市场日 K（OHLCV + PE/PB + 换手率） |
| 周一-周五 16:00 | `daily_value` | 全市场价值面补充 |
| 周六 02:00 | `weekly_fundamentals` | 行业 + 财务摘要 |
| 周六 03:00 | `weekly_dividend` | 已实施现金分红 + 本地计算近 12 个月股息率 |
| 周日 02:00 | `sync_basic` | 全 A 股代码列表（新股 / 退市） |
| 周日 03:00 | `weekly_kline_backfill` | 全市场 60d K 线回填 |
| 每 6h | `db_backup` | SQLite 冷备份 → `/app/data/backups/` |

任务执行结果落 `sync_meta` 表，前端 `/health/data` 可查「最后更新于…」。接口会同时返回 `freshness` 诊断对象，区分全市场行情落后、详情页稀疏新数据和后台同步中。

`fresh=true` 只表示全市场日线已覆盖到 `expected_trade_date`，不代表所有后台任务都成功。若同时存在 `sync_warnings`，前端会继续展示异常任务；财务、分红、K 线回填等异常可能影响 ROE、同比、股息率或历史 K 线相关功能，但不会伪造成数据新鲜。

手动触发：
```bash
# 异步（守护线程，立即返回）
curl -X POST http://localhost:8000/api/v1/health/sync/daily_market

# 同步（短任务用）
curl -X POST 'http://localhost:8000/api/v1/health/sync/db_backup?wait=true'
```

健康检查和 Agent smoke：

```bash
curl -s http://127.0.0.1:8080/api/v1/health/ai
curl -s http://127.0.0.1:8080/api/v1/health/data
python3 backend/scripts/agent_smoke.py
docker compose exec -T backend python scripts/agent_reliability_smoke.py
```

普通自动化测试不依赖真实 AI；后端用 fake model / 本地规则锁定路由语义，前端 smoke 用浏览器内 mock SSE 覆盖真实 UI 流程。需要验证真实 Qwen/OpenCode Go 时，先看 `/health/ai`，再手动运行 `agent_smoke.py` 或容器内的 `agent_reliability_smoke.py`；若模型规划超过短超时，系统会保留安全本地兜底和 `fallback_reason`，不把部分满足条件的结果伪装成完整命中。完整本地浏览器 smoke：

```bash
cd frontend
npm run smoke:auth
npm run smoke:dashboard
npm run smoke:strategy
npm run smoke:chat
npm run smoke:detail
```

交付前 release smoke：

```bash
python3 backend/scripts/release_smoke.py
docker compose exec -T backend python scripts/release_smoke.py
```

`release_smoke.py` 会检查 Docker 服务、AI/数据健康、SSE fast-path、`stock_detail` 不筛选、真实筛选返回结果，以及定向密钥扫描，并在末尾输出 `pass/warn/fail` 汇总。在 backend 容器内运行时没有 docker/rg CLI，会把 `docker compose ps` 降级为 WARN；外层 `docker compose ps` 是单独验证项，容器内脚本继续使用 HTTP 检查和 Python 密钥扫描。AI 已配置但上游暂不可达时会输出 `WARN health/ai`，筛选链路继续走本地兜底并显示 `fallback_reason`；存在 `sync_warnings` 或重同步任务正在运行时也会输出 WARN 和下一步建议，不会伪装成模型或同步任务完全正常。`agent_reliability_smoke.py` 会额外覆盖复杂筛选、解释、排序、分页、详情和 unsupported metric 边界，逐轮输出 `tool`、`conditions`、`screened/result`、`model_ms`、`tool_ms`、`fallback_reason` 和总耗时；如果 `/health/ai` 未配置或不健康，它只输出 WARN 并跳过真实 Qwen 回归。

Chat Agent 采用 bounded ReAct：模型每步只能选择一个白名单工具或给出最终回答；后端执行工具后把 observation 摘要回传给下一步。SSE 会继续保留旧的 `planning/parsed/screening/result/agent/done` 事件，并额外输出 `react_step/tool_start/tool_observation/tool_done/final`，用于区分模型决策、工具执行和最终回答；这些 ReAct step 事件带有 `timing_phase`，可区分 `model_action`、`model_final`、`model_*_fallback` 和 `tool_execution`。前端只展示公开步骤摘要，不展示模型私有思考链。

Unsupported metric 是进入模型前的本地快速路径。命中三年 CAGR/复合增速、扣非净利润、经营现金流、EPS/每股收益、PS/市销率、机构/基金/北向资金持仓、研报评级、目标价等字段时，后端直接返回不支持说明，不调用 Qwen，不调用筛选引擎，SSE 不会出现 `screening/result`，`model_ms=0` 且 `fallback_reason=local_fast_path`。

`/health/ai` 在运行时不会为首次上游探测阻塞页面：缓存未命中时先返回 `pending=true`，后台短超时刷新真实状态；已有过期状态时返回 `stale=true` 并继续刷新。AI 上游不可达属于预期降级路径，UI 会提示本地规则兜底，不应解读为本地筛选不可用。

个股详情的实时行情只在短预算内等待外部 provider。超时、DNS 失败或熔断时，`/stock/{code}/quote` 会使用本地最新日线返回 `source=local`；页面仍应展示详情、K 线和本地指标，并明确不是实时行情。
`npm run smoke:detail` 会打开 `/detail/600036.SH`，检查本地详情、K 线 canvas / 容器、阻塞性加载错误和移动端横向溢出。

登录和注册都要求一次性图形验证码。验证码由后端生成 SVG data URL，错误或过期会返回明确提示；前端失败后会刷新验证码。浏览器回归用 `npm run smoke:auth` 覆盖验证码加载、刷新、空值/错误提示、注册后切回登录、登录、退出和重登。

Dashboard 市场概览使用本地 EOD 聚合缓存。后端启动后会在后台预热 `indices/sectors/movers/ticker`，数据同步成功后会清理并重新预热缓存；冷启动首个请求可能仍比热缓存慢，但不应长期阻塞页面。需要复测时，重启 backend/frontend 后连续请求 `/api/v1/market/indices`、`/api/v1/market/sectors?limit=20`、`/api/v1/market/movers?limit=10`、`/api/v1/market/ticker`、`/api/v1/health/data`，对比 cold/warm 耗时。

提交前可做一次定向密钥扫描：

```bash
rg -n "OPENAI_API_KEY=.*[A-Za-z0-9]{20}|DASHSCOPE_API_KEY=.*[A-Za-z0-9]{20}|sk-[A-Za-z0-9]{20,}" backend/app backend/tests frontend/src docker-compose.yml README.md docs backend/.env.example || true
```

---

## 项目结构

```
qwen-stock-screener/
├── docker-compose.yml          # 三服务编排（backend + redis + frontend）
├── backend/
│   ├── Dockerfile              # 多阶段构建（slim runtime + healthcheck）
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py             # FastAPI 入口 + lifespan + 9 个 router
│   │   ├── config.py           # pydantic-settings
│   │   ├── database.py         # SQLAlchemy 引擎
│   │   ├── models/             # ORM（user / stock / watchlist / chat / notification）
│   │   ├── schemas/            # Pydantic 模型
│   │   ├── api/                # 9 个 router
│   │   ├── core/               # JWT + 密码哈希 + deps
│   │   ├── services/
│   │   │   ├── qwen_client/    # AI 调用层（FC + JSON 模式兜底 + 重试 + 流式）
│   │   │   │   ├── __init__.py
│   │   │   │   └── transport.py
│   │   │   ├── screener_engine.py
│   │   │   ├── data_sync.py    # Baostock-first 同步 + AKShare 少量兜底
│   │   │   ├── scheduler.py    # APScheduler 任务
│   │   │   ├── backtest_engine.py
│   │   │   ├── cache.py        # Redis（静默回退）
│   │   │   ├── db_backup.py
│   │   │   └── migrations.py
│   │   └── prompts/            # 千问 prompt 模板
│   ├── scripts/sync_data.py    # CLI 同步入口
│   └── tests/                  # 9 个 pytest 文件
│
├── frontend/
│   ├── Dockerfile              # builder(node) + runtime(nginx)
│   ├── nginx.conf              # SSE 反代（proxy_buffering off）
│   ├── package.json
│   └── src/
│       ├── main.js + App.vue + router/
│       ├── api/                # 10 个端点封装 + SSE 通用客户端
│       ├── stores/             # Pinia（auth / chatHistory / watchlist / notifications / toast / aiStatus）
│       ├── composables/        # useNlStream / useKlineCache
│       ├── services/           # 前端预警引擎
│       ├── views/              # 6 个页面 + Login
│       ├── components/         # Shell / TopBar / Toaster / Skeleton / charts/
│       ├── shared/             # theme.js（A2 调色板）+ errors.js
│       └── assets/global.css
│
└── docs/
    ├── build_design_doc.py     # python-docx 论文生成器
    └── 基于千问的股票筛选系统设计与实现.docx
```

---

## 系统模块清单

系统按「后端服务 + 前端视图 + 工程基础设施」三层组织，下表为每个模块的实现状态。

### 后端模块（[backend/app/](backend/app/)）

| 模块 | 关键能力 | 测试覆盖 |
|---|---|---|
| **认证** [`api/auth.py`](backend/app/api/auth.py) | JWT 注册 / 登录 / `me`；bcrypt 密码哈希；OAuth2 form 登录 | ✅ `test_auth_e2e.py` |
| **股票数据** [`api/stock.py`](backend/app/api/stock.py) | 模糊搜索、个股详情（基本面 + 最新行情 + 财务）、K 线（任意 N 日，自动回填）、自选 CRUD | ✅ `test_stock_api.py` |
| **筛选引擎** [`services/screener_engine.py`](backend/app/services/screener_engine.py) | 13 字段 × 7 操作符 × AND/OR 组合 + 排序 + 分页 | ✅ `test_screener.py` |
| **千问 AI 客户端** [`services/qwen_client/`](backend/app/services/qwen_client/) | Function Calling + bounded ReAct step；OpenAI / DashScope 双后端切换；SSE 流式；指数退避重试；Redis 缓存 | ✅ `test_agent_planner.py` |
| **NL 筛选** [`api/screener.py`](backend/app/api/screener.py) | 三个端点：结构化 / NL 一次性 / NL SSE 流式（thinking → parsed → result 三阶段） | ✅ `test_screener.py` |
| **基本面分析** [`api/qwen.py`](backend/app/api/qwen.py) | 个股投资分析：一次性 + SSE 流式两个端点；1h Redis 缓存 | — |
| **行情聚合** [`api/market.py`](backend/app/api/market.py) | 4 大指数（实时点位 + 30 日 sparkline）；板块涨跌；涨/跌/成交额/换手率四榜；全市场 Ticker | — |
| **对话历史** [`api/chat.py`](backend/app/api/chat.py) | 历史快照 CRUD；每用户上限 50 条，超出自动删最旧 | ✅ `test_chat_sessions.py` |
| **通知中心** [`api/notification.py`](backend/app/api/notification.py) | 预警通知持久化、已读 / 全部已读 / 删除 | ✅ `test_notifications.py` |
| **智能选股 Agent** [`services/agent_react.py`](backend/app/services/agent_react.py) + [`services/strategy_selector.py`](backend/app/services/strategy_selector.py) | bounded ReAct：模型选工具 → 后端执行 → observation → 最终回答；AI 不可用时高置信度本地降级 | ✅ `test_strategy_agent.py` + `test_screener_stream.py` |
| **数据同步** [`services/data_sync.py`](backend/app/services/data_sync.py) | Baostock-first；7 个 sync 子命令；< 80% 防误删保护；K 线自动回填 | ✅ `test_data_sync_guard.py` |
| **定时调度** [`services/scheduler.py`](backend/app/services/scheduler.py) | APScheduler 6 任务（行情 / 财务 / 基本信息 / K 线回填 / 备份） + `sync_meta` 元数据落库 | — |
| **缓存层** [`services/cache.py`](backend/app/services/cache.py) | Redis 千问解析结果 / 个股分析缓存；不可达时静默回退 | ✅ `test_cache.py` |
| **冷备份** [`services/db_backup.py`](backend/app/services/db_backup.py) | SQLite 每 6h 物理备份；启动时立即一份；备份列表查询 | — |
| **健康检查** [`api/health.py`](backend/app/api/health.py) | AI 探活、数据新鲜度、缓存命中率、手动触发同步、备份列表 | — |

### 前端视图（[frontend/src/views/](frontend/src/views/)）

| 视图 | 接的后端 | 关键能力 |
|---|---|---|
| **Login** [`Login.vue`](frontend/src/views/Login.vue) | `/auth/*` | 登录 / 注册一体页，A2 主题 |
| **行情 Dashboard** [`Dashboard.vue`](frontend/src/views/Dashboard.vue) | `/market/*` | 4 指数 + 30 日 sparkline + 板块涨跌 + 涨跌榜（4 个 tab） |
| **千问对话筛选** [`Chat.vue`](frontend/src/views/Chat.vue) | `/screener/nl/stream` | SSE 流式三阶段；历史持久化 + 跨设备同步；0 命中智能建议；预设提示 |
| **因子筛选器** [`Results.vue`](frontend/src/views/Results.vue) | `/screener` | 默认条件可视化 + 实时 sparkline + 价值分排序 |
| **个股详情** [`Detail.vue`](frontend/src/views/Detail.vue) | `/stock/{code}` + `/stock/{code}/kline` + `/stock/{code}/intraday` | klinecharts K 线；5/15/30/60 分钟 K + 日/周/月 K；MA/BOLL/MACD/KDJ/RSI 切换；分钟线失败时明确提示，不用日线伪装 |
| **自选监控** [`Portfolio.vue`](frontend/src/views/Portfolio.vue) | `/stock/me/watchlist` + alertEngine 轮询 | 5 种预警类型（涨跌 % / 价格突破 / 当日 %）；跨设备同步 |
| **智能选股工作台** [`Strategy.vue`](frontend/src/views/Strategy.vue) | `/strategy/agent` + `/strategy/select` + `/screener` | 自然语言 Agent 选股 + 结构化条件筛选 + 内置策略选股；结果可跳转详情页 |

### 前端基础设施

| 组件 / 模块 | 路径 | 用途 |
|---|---|---|
| **全局错误边界** | [`components/ErrorBoundary.vue`](frontend/src/components/ErrorBoundary.vue) | Vue `errorHandler` 兜底，组件抛错不白屏 |
| **命令面板** | [`components/CommandPalette.vue`](frontend/src/components/CommandPalette.vue) | ⌘K 全局搜索股票 / 跳转视图 |
| **自选浮窗** | [`components/WatchlistDock.vue`](frontend/src/components/WatchlistDock.vue) | 全局浮动自选股快捷面板 |
| **预警引擎** | [`services/alertEngine.js`](frontend/src/services/alertEngine.js) | 30s 轮询每只自选股最新价，触发预警 → 写通知中心 |
| **数据新鲜度** | [`components/DataFreshness.vue`](frontend/src/components/DataFreshness.vue) | 顶部条显示「最后更新于…」+ 一键刷新 |
| **状态管理** | [`stores/`](frontend/src/stores/) | 6 个 Pinia store：auth / chatHistory / watchlist / notifications / toast / aiStatus，全部带 localStorage 离线兜底 |
| **Composables** | [`composables/`](frontend/src/composables/) | `useNlStream`（SSE 状态机） + `useKlineCache`（按 code 缓存 sparkline） |
| **SSE 客户端** | [`api/sse.js`](frontend/src/api/sse.js) | 通用 fetch + ReadableStream 流式解析，自动注入 JWT |
| **错误翻译** | [`shared/errors.js`](frontend/src/shared/errors.js) | errno / 401 / 503 / network → 中文产品文案 |
| **UI 基元** | Skeleton / EmptyState / Toaster / StarButton / AlertRuleEditor | 骨架屏 / 空态 / Toast / 一键加自选 / 预警规则编辑器 |

### 工程基础设施

| 设施 | 状态 | 文件 |
|---|---|---|
| Docker Compose 三服务编排 | ✅ | [`docker-compose.yml`](docker-compose.yml) |
| 后端 Dockerfile 多阶段 + healthcheck | ✅ | [`backend/Dockerfile`](backend/Dockerfile) |
| 前端 Dockerfile (node builder + nginx runtime) | ✅ | [`frontend/Dockerfile`](frontend/Dockerfile) |
| nginx SSE 反代（buffering off + 30 分钟超时） | ✅ | [`frontend/nginx.conf`](frontend/nginx.conf) |
| pytest 166 个用例全通过 | ✅ | [`backend/tests/`](backend/tests/) |
| 接口文档 | ✅ | [`docs/API.md`](docs/API.md) |
| 学年设计 docx | ✅ | [`docs/`](docs/) |

---

## 测试

```bash
cd backend
source .venv/bin/activate
pytest tests/ -v
```

Docker 环境可直接运行：

```bash
docker compose exec -T backend pytest
```

涵盖：
- `test_smoke.py` — 启动 + 基本路由
- `test_auth_e2e.py` — 注册 / 登录端到端
- `test_screener.py` — 筛选引擎单元
- `test_stock_api.py` — 个股 / 搜索 / K 线
- `test_watchlist_sync.py` / `test_chat_sessions.py` / `test_notifications.py` — 跨设备同步
- `test_data_sync_guard.py` — 防误删（上游 < DB 80% 跳过）
- `test_cache.py` — Redis 缓存回退

测试用独立 SQLite 文件（`/tmp/pytest_qwen.db`），跟生产 `stock.db` 物理隔离。

---

## 健壮性设计要点

| 场景 | 处理 |
|---|---|
| 免费数据源偶发网络抖动 | Baostock-first；同步批次限时并保留已提交数据；分钟 K 失败后短期熔断 |
| 详情页首次历史 K 线不足 | 先返回已有日线，后台补充历史；前端自动刷新图表，不阻塞详情页 |
| 详情页实时行情上游慢或不可达 | 短预算等待 + 失败缓存 + 熔断；超时后返回本地日线 `source=local` |
| OpenAI 兼容网关不支持 Responses API | 自动回退 Chat Completions，并在短期熔断窗口内跳过不兼容接口 |
| 千问输出不是合法 JSON / 工具参数非法 | 后端 schema 强校验；ReAct step 最多修复一次，失败后只走高置信度本地兜底或澄清 |
| 上游 AI 瞬时网络错误 | `/health/ai` pending/stale 快速返回 + 后台短超时刷新；前端降级后自动复测；业务调用指数退避重试 3 次 |
| 全市场同步上游返回异常少 | `< DB 80%` 直接跳过该次任务（防止部分快照 wipe） |
| Redis 不可达 | 静默回退到无缓存模式，业务不中断 |
| 千问 Key 未配置 | 千问相关功能给出明确错误，其他功能正常 |
| 登录 / 注册验证码错误或过期 | 本次请求失败并刷新验证码；验证码一次性使用，不降低后端校验 |
| 用户未登录 | 自选股 / 对话历史走 localStorage 离线兜底 |
| 任意 Vue 组件抛错 | 全局 ErrorBoundary + Vue errorHandler 兜底，不白屏 |

---

## 已知限制

- 财务字段是「最新一期」快照，适合当前选股，不适合严肃历史回测
- Agent 只能筛选本地白名单字段：PE、PB、ROE、市值、股息率、营收同比、净利润同比、毛利率、负债率、行业、市场、收盘价、换手率；三年 CAGR/复合增速、扣非净利润、经营现金流、EPS/每股收益、PS/市销率、机构持仓、基金持仓、北向资金、研报评级、目标价等会明确说明不支持，不返回部分满足结果
- Baostock 分红接口不支持北交所 `.BJ`，这类股票股息率会明确显示缺失，不用假数据补 0
- 分钟 K 依赖 Baostock 实时查询，失败时返回 503；前端明确提示，不会静默切到日线
- 日 K 接口按旧到新返回；周 K/月 K 直接请求 Baostock 对应周期，不由前端临时聚合
- 流通市值字段当前用总市值代替

> 完整清单见 [`docs/STATUS.md`](docs/STATUS.md)，含「未完成 / 后续工作」的优先级分级。

---

## 文档导览

| 文档 | 用途 |
|---|---|
| [README.md](README.md)（本文件） | 项目总览、快速开始、系统模块 |
| [docs/STATUS.md](docs/STATUS.md) | **交接清单**：已完成 / 半实现 / UI 占位 / 已知陷阱 / 后续工作 |
| [docs/API.md](docs/API.md) | 接口文档：33+ 端点的请求 / 响应 / curl 示例 |
| [docs/基于千问的股票筛选系统设计与实现.docx](docs/) | 学年设计论文成稿 |
| [docs/build_design_doc.py](docs/build_design_doc.py) | 论文生成脚本 |
| [LICENSE](LICENSE) | MIT 许可证 |

---

## 致谢

- [Baostock](https://baostock.com/) — A 股数据主链路
- [AKShare](https://github.com/akfamily/akshare) — 少量实时行情与兼容兜底
- [FastAPI](https://github.com/tiangolo/fastapi) / [Vue 3](https://github.com/vuejs/core)
- [阿里云百炼](https://bailian.console.aliyun.com) / OpenAI 兼容生态

---

**Disclaimer**：本项目仅用于学习与研究，不构成任何投资建议。
