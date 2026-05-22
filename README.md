# 基于千问的股票筛选系统

学年设计项目。FastAPI 后端 + Vue 3 前端，集成大模型实现「自然语言筛选 + 基本面投资分析」，支持沪深 300/500 行情、财务、行业数据的离线同步与定时刷新。

```
浏览器 (Vue 3 SPA)
   │ /api/* via nginx 反代
   ▼
FastAPI 后端  ──┬──  SQLite / MySQL（行情 / 财务 / 用户 / 自选 / 对话历史）
                ├──  Redis 缓存（千问解析结果、个股分析）
                ├──  AKShare（沪深300/500 + 雪球 + 新浪 + 东方财富）
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
| 策略回测 | `/strategy` | 给定筛选条件 → 月度调仓 → 净值曲线 + 关键指标 |

> 完整 API 接口文档见 [`docs/API.md`](docs/API.md)，含所有端点的 curl 示例与响应样本。

---

## 技术栈

### 后端（Python 3.10+）
- **FastAPI 0.115** + Uvicorn + SQLAlchemy 2.0 + Pydantic v2
- **APScheduler** 定时任务（每日收盘后行情、周末财务回填、6h 一次 SQLite 冷备份）
- **AKShare** 数据源（沪深300 成分股 + 雪球 / 新浪 / 东方财富多通路）
- **OpenAI SDK + dashscope** 双 AI 后端，可一键切换
- **Redis**（可选）缓存千问解析结果

### 前端（Node 20+）
- **Vue 3.5** + Vite + Vue Router 4 + Pinia 2
- 自定义主题（A2 调色板 + IBM Plex 字体）+ 自渲染 SVG 图表（Sparkline / FullCandle / Donut）
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
#   - OPENAI_API_KEY + OPENAI_BASE_URL  （走 OpenAI 兼容网关）
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
| `SECRET_KEY` | dev-secret | JWT 签名密钥，生产必须改 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 1440 | JWT 有效期 |
| **`AI_BACKEND`** | `openai` | `openai` 或 `dashscope` |
| `OPENAI_API_KEY` | — | OpenAI 或兼容网关的 Key |
| `OPENAI_BASE_URL` | `https://api2.up.railway.app` | 中转网关地址；填 `https://api.openai.com` 走官方 |
| `OPENAI_MODEL` | `gpt-5.4` | 模型名；走官方时建议改 `gpt-4o-mini` 等 |
| `OPENAI_REASONING` | `high` | Responses API reasoning effort（不支持则自动忽略） |
| `DASHSCOPE_API_KEY` | — | 阿里云百炼 Key（[控制台](https://bailian.console.aliyun.com)） |
| `QWEN_MODEL` | `qwen-plus` | dashscope 模型 |
| `CORS_ORIGINS` | `http://localhost:5173` | 多个用逗号分隔 |

> **AI 后端两种配法选其一即可**。`OPENAI_BASE_URL` 默认指向一个中转网关，仅作示例——生产/正式使用请改成 `https://api.openai.com` 或自建网关，并相应调整 `OPENAI_MODEL`。

---

## 数据同步命令

```bash
python -m scripts.sync_data <子命令> [pool]
```

| 子命令 | 数据源 | 内容 | 耗时 |
|---|---|---|---|
| `basic` | 新浪 | 全 A 股 5500+ 代码 + 名称 | 几秒 |
| `daily-em` | 东方财富 | 全市场实时行情（PE/PB/市值）—— **网络受限时易超时** | < 30s |
| `daily-sina` | 新浪 | 全市场 5500 只 OHLC + 成交量（无 PE/市值） | ~40s |
| `pool` | 沪深300 + 雪球 | 池内 PE/PB/股息率/流通值 | ~1 分钟 |
| `industry` | 雪球 | 行业 + 上市时间 + 总股本 | ~1 分钟 |
| `financial` | 东方财富 | ROE / 营收同比 / 净利同比 / 毛利率 / 负债率 | ~3 分钟 |
| `full` | 全部 | 上面四步连跑（默认 csi300 池） | ~5 分钟 |

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
strategy/           策略回测（输入条件 + 时间窗 → 净值曲线 + 指标）
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

---

## 定时任务（APScheduler，东八区）

| Cron | 任务 | 内容 |
|---|---|---|
| 周一-周五 15:30 | `sync_daily_sina` | 全市场 5800 只 OHLC + 成交量 |
| 周一-周五 16:00 | `sync_pool_xq` | csi300 + csi500 共 800 只价值面 |
| 周六 02:00 | `weekly_fundamentals` | 行业 + 财务摘要 |
| 周日 02:00 | `sync_basic` | 全 A 股代码列表（新股 / 退市） |
| 周日 03:00 | `weekly_kline_backfill` | 全市场 60d K 线回填 |
| 每 6h | `db_backup` | SQLite 冷备份 → `/app/data/backups/` |

任务执行结果落 `sync_meta` 表，前端 `/health/data` 可查「最后更新于…」。

手动触发：
```bash
# 异步（守护线程，立即返回）
curl -X POST http://localhost:8000/api/v1/health/sync/daily_market

# 同步（短任务用）
curl -X POST 'http://localhost:8000/api/v1/health/sync/db_backup?wait=true'
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
│   │   │   ├── data_sync.py    # AKShare 多通路同步
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
| **千问 AI 客户端** [`services/qwen_client/`](backend/app/services/qwen_client/) | 三层降级（Function Calling → JSON 模式 → 容错 regex 抠 JSON）；OpenAI / DashScope 双后端切换；SSE 流式；指数退避重试；Redis 缓存 | — |
| **NL 筛选** [`api/screener.py`](backend/app/api/screener.py) | 三个端点：结构化 / NL 一次性 / NL SSE 流式（thinking → parsed → result 三阶段） | ✅ `test_screener.py` |
| **基本面分析** [`api/qwen.py`](backend/app/api/qwen.py) | 个股投资分析：一次性 + SSE 流式两个端点；1h Redis 缓存 | — |
| **行情聚合** [`api/market.py`](backend/app/api/market.py) | 4 大指数（实时点位 + 30 日 sparkline）；板块涨跌；涨/跌/成交额/换手率四榜；全市场 Ticker | — |
| **对话历史** [`api/chat.py`](backend/app/api/chat.py) | 历史快照 CRUD；每用户上限 50 条，超出自动删最旧 | ✅ `test_chat_sessions.py` |
| **通知中心** [`api/notification.py`](backend/app/api/notification.py) | 预警通知持久化、已读 / 全部已读 / 删除 | ✅ `test_notifications.py` |
| **策略回测** [`services/backtest_engine.py`](backend/app/services/backtest_engine.py) | 等权调仓 / 净值曲线 / 关键指标（夏普 / 回撤 / 胜率 / 盈亏比）/ 月度收益 / 交易日志 | — |
| **数据同步** [`services/data_sync.py`](backend/app/services/data_sync.py) | 多通路（雪球 + 新浪 + 东方财富）；7 个 sync 子命令；< 80% 防误删保护；K 线自动回填 | ✅ `test_data_sync_guard.py` |
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
| **个股详情** [`Detail.vue`](frontend/src/views/Detail.vue) | `/stock/{code}` + `/qwen/analysis/{code}/stream` | K 线 6 个周期切换；16 个关键指标头部；千问流式分析（含 Markdown 渲染）；自动同行业对比 |
| **自选监控** [`Portfolio.vue`](frontend/src/views/Portfolio.vue) | `/stock/me/watchlist` + alertEngine 轮询 | 5 种预警类型（涨跌 % / 价格突破 / 当日 %）；跨设备同步 |
| **策略回测** [`Strategy.vue`](frontend/src/views/Strategy.vue) | `/strategy/backtest` | 4 个预设策略 + 自定义参数 + 月度收益热力图 |

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
| pytest 38 个用例全通过 | ✅ | [`backend/tests/`](backend/tests/) |
| 接口文档 | ✅ | [`docs/API.md`](docs/API.md) |
| 学年设计 docx | ✅ | [`docs/`](docs/) |

---

## 测试

```bash
cd backend
source .venv/bin/activate
pytest tests/ -v
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
| 东方财富批量接口受限 | 回退「沪深300 + 雪球逐只」稳定通路 |
| 千问输出不是合法 JSON | 三层降级：FC → JSON 模式 → 容错 regex 抠 JSON |
| 上游 AI 瞬时网络错误 | 指数退避重试 3 次；流式中途断开不重试（避免重复 token） |
| 全市场同步上游返回异常少 | `< DB 80%` 直接跳过该次任务（防止部分快照 wipe） |
| Redis 不可达 | 静默回退到无缓存模式，业务不中断 |
| 千问 Key 未配置 | 千问相关功能给出明确错误，其他功能正常 |
| 用户未登录 | 自选股 / 对话历史走 localStorage 离线兜底 |
| 任意 Vue 组件抛错 | 全局 ErrorBoundary + Vue errorHandler 兜底，不白屏 |

---

## 已知限制

- 财务字段是「最新一期」快照，非「当时」——回测的基本面回看是近似
- 沪深 300 是默认池；其他股票（如北交所）调用 `pool csi500` / `sse50` 切换
- K 线为日级粒度（无分时）；UI 上的「5 日 / 30 日 / 一年」对应 `?days=` 参数
- 流通市值字段当前用总市值代替（雪球未直接提供）

---

## 致谢

- [AKShare](https://github.com/akfamily/akshare) — A 股数据
- [FastAPI](https://github.com/tiangolo/fastapi) / [Vue 3](https://github.com/vuejs/core)
- [阿里云百炼](https://bailian.console.aliyun.com) / OpenAI 兼容生态

---

**Disclaimer**：本项目仅用于学习与研究，不构成任何投资建议。
