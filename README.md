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
