# 基于千问的股票筛选系统

FastAPI 后端 + Vue 3 前端的 A 股选股系统，支持行情概览、条件筛选、自然语言选股、策略选股、自选股、预警通知、个股详情和数据健康检查。后端以本地行情/财务数据库为核心，AI 只负责理解意图和选择白名单工具，实际筛选与策略计算都由服务端确定性执行。

- API 细节与 curl 示例：[docs/API.md](docs/API.md)
- 内置策略说明：[docs/STRATEGIES.md](docs/STRATEGIES.md)
- 字段能力边界：[docs/FIELD_CAPABILITIES.md](docs/FIELD_CAPABILITIES.md)
- Railway 部署：[docs/RAILWAY_DEPLOYMENT.md](docs/RAILWAY_DEPLOYMENT.md)
- 学年设计文档：[docs/基于千问的股票筛选系统设计与实现.docx](docs/基于千问的股票筛选系统设计与实现.docx)
- 许可证：[MIT](LICENSE)

---

## 系统架构

```text
浏览器（Vue 3 SPA）
   │
   │ /api/*（开发环境 Vite 代理；生产环境 nginx 反代）
   ▼
FastAPI 后端
   ├── SQLite / MySQL：股票基础信息、行情、财务、分红、自选股、预警、对话历史
   ├── Redis：AI 解析、个股分析和部分行情聚合的可选缓存，连接失败时自动降级
   ├── Baostock：沪深日 K、周/月 K、分钟 K、财务、分红
   ├── AKShare / Sina：北交所和少量兜底数据
   ├── APScheduler：收盘后同步、周末回填、策略推送、SQLite 冷备份
   └── AI 后端：OpenAI 兼容接口（默认）或 DashScope
```

---

## 功能一览

| 模块 | 前端路径 | 说明 |
|---|---|---|
| 登录 / 注册 | `/login` | JWT 登录，注册和登录都带一次性图形验证码 |
| 行情概览 | `/dashboard` | 指数、行业、涨跌榜、成交额榜、换手率榜和数据新鲜度 |
| 自然语言选股 | `/chat` | SSE 流式对话，模型选择筛选、策略、解释、排序、分页或详情工具 |
| 条件选股 | `/results` | 多条件组合筛选、排序、分页、批量加入自选 |
| 策略选股 | `/strategy` | 自然语言策略入口、结构化条件筛选和 6 个内置日线策略 |
| 自选与预警 | `/portfolio` | 自选股跨设备同步，价格/涨跌幅预警和通知中心 |
| 个股详情 | `/detail/:code?` | 本地详情、实时行情兜底、日/周/月 K、分钟 K 和 AI 解读 |

---

## 技术栈

### 后端

- Python 3.10+
- FastAPI 0.115、Uvicorn、SQLAlchemy 2.0、Pydantic v2
- APScheduler 定时任务
- Baostock 优先数据源，AKShare/Sina 少量兜底
- OpenAI SDK + DashScope 双 AI 后端
- Redis 可选缓存
- pytest 回归测试

### 前端

- Vue 3.5、Vite 6、Vue Router 4、Pinia 2
- Naive UI、klinecharts、marked
- Axios 普通请求，fetch + ReadableStream 处理 SSE
- nginx 生产静态服务与 `/api/*` 反代

### 部署

- Docker Compose：`backend + redis + frontend`
- 前端 nginx 支持 SSE：`proxy_buffering off`，长超时
- Railway：前后端各一个服务，Redis 可选，SQLite 需挂载 Volume

---

## 快速开始

### Docker Compose

```bash
cp backend/.env.example backend/.env
# 编辑 backend/.env，至少配置一种 AI 后端：
# - AI_BACKEND=openai + OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL
# - 或 AI_BACKEND=dashscope + DASHSCOPE_API_KEY

docker compose up -d --build

# 首次初始化数据
docker compose exec -T backend python -m scripts.sync_data full

# 前端
open http://localhost:8080
```

后端容器默认只在 Docker 网络内暴露 `8000`。如果需要直接访问 Swagger，可在 `docker-compose.yml` 中打开 backend 的端口映射，再访问 `http://localhost:8001/docs`。

### 本地开发

```bash
# 后端
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m scripts.sync_data full
uvicorn app.main:app --reload --port 8000

# 前端，另开一个终端
cd frontend
npm install
npm run dev
```

开发环境的 Vite 已把 `/api` 代理到 `http://127.0.0.1:8000`，前端默认地址是 `http://localhost:5173`。

---

## 关键配置

配置文件在 `backend/.env`，示例见 [backend/.env.example](backend/.env.example)。

| 变量 | 说明 |
|---|---|
| `DATABASE_URL` | 默认 SQLite，可改 MySQL：`mysql+pymysql://user:pass@host:3306/db?charset=utf8mb4` |
| `REDIS_URL` | 可选；留空或连接失败时业务自动退回无缓存模式 |
| `DATA_PROVIDER` | 数据源后端，默认 `baostock`，`akshare` 为 legacy |
| `SECRET_KEY` | JWT 签名密钥，生产必须替换 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT 有效期 |
| `AI_BACKEND` | `openai` 或 `dashscope` |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` | OpenAI 兼容后端配置，可接 OpenAI、OpenCode Go 或自建网关 |
| `OPENAI_RESPONSES_ENABLED` | 兼容网关不支持 Responses API 时保持 `false` |
| `AGENT_PLAN_TIMEOUT_SECONDS` | 旧规划路径超时 |
| `AGENT_REACT_STEP_TIMEOUT_SECONDS` | bounded ReAct 单步模型超时 |
| `DASHSCOPE_API_KEY` / `QWEN_MODEL` | DashScope 后端配置 |
| `CORS_ORIGINS` | 允许的前端来源，逗号分隔 |
| `FEISHU_*` | 飞书 webhook 或企业应用配置；不填则不推送 |
| `BAOSTOCK_INTRADAY_TIMEOUT` | 分钟 K 拉取超时 |
| `BAOSTOCK_INTRADAY_BREAKER_SECONDS` | 分钟 K 失败后的短期熔断时间 |

不要提交真实 `.env`、数据库文件或任何 API Key。

---

## 数据同步

```bash
python -m scripts.sync_data <子命令> [参数]
```

| 子命令 | 内容 |
|---|---|
| `basic` | 拉取全 A 股基础信息 |
| `daily [days]` | 拉取全市场最近 N 天日 K，默认 5 天 |
| `kline [code] [days]` | 回填单只股票 K 线，默认 `600519.SH 120` |
| `financial [pool]` | 同步财务指标，`pool` 支持 `csi300`、`csi500`、`all` |
| `dividend [code]` | 同步现金分红并计算 TTM 股息率；不传 code 时全市场 |
| `full` | `basic + daily(10) + financial(all) + dividend(all)` |

`DATA_PROVIDER=akshare` 时仍保留 `basic-ak`、`daily-sina`、`daily-em`、`pool`、`industry`、`financial-ak` 等 legacy 命令。

---

## API 概览

所有业务接口默认前缀为 `/api/v1`。

| 路由 | 说明 |
|---|---|
| `/auth` | 验证码、注册、登录、当前用户 |
| `/stock` | 搜索、详情、实时行情兜底、K 线、分钟 K、自选股 CRUD |
| `/screener` | 结构化筛选、自然语言一次性筛选、自然语言 SSE 流式筛选 |
| `/qwen` | 个股 AI 解读，一次性和 SSE 两种返回 |
| `/strategy` | 策略模板、Agent 工具清单、内置策略执行、自然语言策略入口 |
| `/market` | Dashboard 聚合、指数、行业列表、板块、涨跌榜、ticker |
| `/chat` | 对话历史 CRUD 和上下文快照 |
| `/notifications` | 通知中心、已读、清空、飞书预警推送 |
| `/health` | AI 探活、数据健康、缓存状态、手动同步、备份、数据源状态 |

Swagger 文档在 `http://localhost:8000/docs`，Docker Compose 默认通过前端访问接口：`http://localhost:8080/api/v1/...`。

---

## 筛选字段

操作符：`gt`、`gte`、`lt`、`lte`、`eq`、`between`、`in`。

| 字段 | 含义 | 来源 |
|---|---|---|
| `pe` / `pb` | 市盈率 / 市净率 | `stock_daily` |
| `market_cap` | 总市值，单位亿 | `stock_daily` |
| `close` / `turnover` / `dividend_yield` | 收盘价 / 换手率 / 股息率 | `stock_daily` |
| `roe` | 净资产收益率 | `stock_financial` |
| `revenue_yoy` / `profit_yoy` | 营收同比 / 净利润同比 | `stock_financial` |
| `gross_margin` / `debt_ratio` | 毛利率 / 资产负债率 | `stock_financial` |
| `industry` / `market` | 行业 / 市场板块 | `stock_basic` |
| `risk_flag` | ST / 退市风险名称标记 | `stock_basic` |
| `ma5` / `ma20` | 5 日 / 20 日均线 | 本地日 K 计算 |
| `volume_ratio_20` | 当前成交量相对 20 日均量 | 本地日 K 计算 |
| `breakout_20` | 是否突破 20 日高点 | 本地日 K 计算 |
| `ma5_above_ma20` | 5 日均线是否高于 20 日均线 | 本地日 K 计算 |
| `pct_change_20` | 20 日涨跌幅 | 本地日 K 计算 |

排序字段还支持 `change_pct` 和 `score`。完整字段边界和不支持指标说明见 [docs/FIELD_CAPABILITIES.md](docs/FIELD_CAPABILITIES.md)。

---

## 定时任务

调度器随 FastAPI 启动，使用东八区时间。执行状态写入 `sync_meta`，前端数据面板和 `/health/data` 会读取这些状态。

| 时间 | 任务 | 内容 |
|---|---|---|
| 周一至周五 15:05 | `market_refresh` | 收盘后快刷日 K 与估值面 |
| 周一至周五 15:30 | `daily_market` | 全市场日 K 补偿 |
| 周一至周五 16:00 | `daily_value` | 估值与股息率补充 |
| 周一至周五 18:00 | `strategy_push` | 全策略扫描并推送飞书 |
| 周六 02:00 | `weekly_fundamentals` | 财务指标 |
| 周六 03:00 | `weekly_dividend` | 现金分红与 TTM 股息率 |
| 周日 02:00 | `weekly_basic` | 股票列表、新股、退市更新 |
| 周日 03:00 | `weekly_kline_backfill` | 全市场近期 K 线回填 |
| 每 6 小时 | `db_backup` | SQLite 冷备份 |

手动触发：

```bash
curl -X POST http://localhost:8080/api/v1/health/sync/daily_market
curl -X POST 'http://localhost:8080/api/v1/health/sync/db_backup?wait=true'
```

`/health/data` 的 `fresh=true` 只表示全市场日线覆盖到最近应有交易日；仍需同时查看 `coverage`、`sync_warnings`、`active_jobs` 和推荐修复任务。

---

## 项目结构

```text
qwen-stock-screener-naive/
├── docker-compose.yml
├── backend/
│   ├── Dockerfile
│   ├── railway.toml
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py              # FastAPI 入口、lifespan、router 注册
│   │   ├── config.py            # pydantic-settings 配置
│   │   ├── database.py          # SQLAlchemy engine/session
│   │   ├── api/                 # 9 个业务 router
│   │   ├── core/                # JWT、密码哈希、依赖
│   │   ├── models/              # user / stock / watchlist / chat / notification
│   │   ├── schemas/             # Pydantic 模型
│   │   ├── services/
│   │   │   ├── agent_react.py
│   │   │   ├── qwen_client/
│   │   │   ├── screener_engine.py
│   │   │   ├── strategy_selector.py
│   │   │   ├── strategies/
│   │   │   ├── data_sync.py
│   │   │   ├── scheduler.py
│   │   │   ├── feishu.py
│   │   │   ├── cache.py
│   │   │   ├── db_backup.py
│   │   │   └── migrations.py
│   │   └── prompts/
│   ├── scripts/
│   └── tests/
├── frontend/
│   ├── Dockerfile
│   ├── railway.toml
│   ├── nginx.conf.template
│   ├── package.json
│   └── src/
│       ├── router/
│       ├── api/
│       ├── stores/
│       ├── views/
│       ├── components/
│       ├── composables/
│       ├── services/
│       ├── shared/
│       └── assets/
└── docs/
```

---

## 后端模块

| 模块 | 关键文件 | 说明 |
|---|---|---|
| 认证 | [backend/app/api/auth.py](backend/app/api/auth.py) | 图形验证码、注册、登录、`me` |
| 股票数据 | [backend/app/api/stock.py](backend/app/api/stock.py) | 搜索、详情、quote、K 线、分钟 K、自选股 |
| 筛选引擎 | [backend/app/services/screener_engine.py](backend/app/services/screener_engine.py) | 字段校验、SQL 查询、技术指标、排序分页 |
| 自然语言选股 | [backend/app/api/screener.py](backend/app/api/screener.py) | 一次性和 SSE 流式入口 |
| Agent 执行 | [backend/app/services/agent_react.py](backend/app/services/agent_react.py) | bounded ReAct、工具白名单、schema 校验、安全停止 |
| 策略选股 | [backend/app/services/strategy_selector.py](backend/app/services/strategy_selector.py) | 6 个内置日线策略、缓存、singleflight、飞书推送 |
| AI 客户端 | [backend/app/services/qwen_client/](backend/app/services/qwen_client/) | OpenAI 兼容和 DashScope 传输层 |
| 行情聚合 | [backend/app/api/market.py](backend/app/api/market.py) | Dashboard 首屏 overview、指数、行业、板块、榜单、ticker 和缓存预热 |
| 对话历史 | [backend/app/api/chat.py](backend/app/api/chat.py) | 会话快照 CRUD、上下文恢复 |
| 通知中心 | [backend/app/api/notification.py](backend/app/api/notification.py) | 通知 CRUD、已读、飞书预警入口 |
| 数据同步 | [backend/app/services/data_sync.py](backend/app/services/data_sync.py) | 基础信息、日 K、财务、分红、北交所兜底 |
| 定时调度 | [backend/app/services/scheduler.py](backend/app/services/scheduler.py) | 自动同步、任务状态、手动触发、卡住任务修复 |
| 健康检查 | [backend/app/api/health.py](backend/app/api/health.py) | AI、数据、缓存、备份、provider 状态 |

---

## 前端模块

| 模块 | 关键文件 | 说明 |
|---|---|---|
| 应用壳 | [frontend/src/components/Shell.vue](frontend/src/components/Shell.vue) | 导航、顶部栏、全局状态入口 |
| 行情概览 | [frontend/src/views/Dashboard.vue](frontend/src/views/Dashboard.vue) | 大盘、板块、榜单、数据状态；首屏优先请求 `/market/overview` |
| 对话选股 | [frontend/src/views/Chat.vue](frontend/src/views/Chat.vue) | SSE 状态机、工具轨迹、结果预览 |
| 条件选股 | [frontend/src/views/Results.vue](frontend/src/views/Results.vue) | 因子筛选、排序、分页、自选操作 |
| 策略工作台 | [frontend/src/views/Strategy.vue](frontend/src/views/Strategy.vue) | Agent 输入、条件筛选、内置策略 |
| 自选监控 | [frontend/src/views/Portfolio.vue](frontend/src/views/Portfolio.vue) | 自选股、预警规则、通知同步 |
| 个股详情 | [frontend/src/views/Detail.vue](frontend/src/views/Detail.vue) | K 线图、分钟线、AI 解读 |
| 数据新鲜度 | [frontend/src/components/DataFreshness.vue](frontend/src/components/DataFreshness.vue) | `/health/data` 展示和修复入口 |
| 自选浮窗 | [frontend/src/components/WatchlistDock.vue](frontend/src/components/WatchlistDock.vue) | 全局快速查看自选 |
| 预警引擎 | [frontend/src/services/alertEngine.js](frontend/src/services/alertEngine.js) | 前端轮询触发预警并写通知 |
| SSE 客户端 | [frontend/src/api/sse.js](frontend/src/api/sse.js) | ReadableStream 流式解析和 JWT 注入 |

---

## 测试与验收

后端测试：

```bash
docker compose exec -T backend pytest
docker compose exec -T backend pytest tests/test_agent_query_regression.py
```

当前容器环境执行 `pytest --collect-only -q` 可收集到 324 个 pytest 用例。覆盖范围包括认证、筛选、Agent 规划、SSE、策略、数据同步保护、健康检查、缓存、实时行情兜底、自选和通知。

前端 smoke：

```bash
cd frontend
npm run smoke:auth
npm run smoke:dashboard
npm run smoke:strategy
npm run smoke:chat
npm run smoke:detail
```

发布前 smoke：

```bash
python3 backend/scripts/release_smoke.py
docker compose exec -T backend python scripts/release_smoke.py
```

真实 AI 不参与普通 pytest。需要验证线上模型时，先看 `/health/ai`，再运行 `agent_smoke.py`、`agent_reliability_smoke.py` 或 `release_smoke.py`。

---

## 健壮性设计

| 场景 | 处理 |
|---|---|
| AI 未配置、超时或不可达 | 普通回复或安全停止，不把本地兜底伪装成模型筛选 |
| 模型返回非法工具或参数 | 后端 schema 校验失败即停止，不执行未知工具 |
| 用户请求不支持指标 | 本地前置拦截并说明原因，不返回部分满足结果 |
| 免费数据源抖动 | 同步任务限时、保留已提交批次，异常写入 `sync_meta` |
| 全市场快照异常少 | 基础列表同步有防误删保护 |
| 详情页 K 线不足 | 先返回已有数据，后台回填，不长时间阻塞页面 |
| 实时行情慢或失败 | 短预算等待、失败缓存、熔断，本地日线兜底 |
| Redis 不可用 | 静默退回无缓存模式 |
| Vue 组件异常 | ErrorBoundary 和全局 errorHandler 防白屏 |
| 用户未登录 | 私有功能跳登录；部分前端状态用 localStorage 兜底 |

---

## 已知限制

- 财务指标是最新一期快照，适合当前选股，不适合严肃历史回测。
- 内置策略表示当前条件命中，不是收益回测，也不构成投资评级。
- `score` 只用于当前列表或策略内部排序，不能跨策略比较。
- 分钟 K 依赖 Baostock 实时查询，失败时返回 503，不用日线伪装分钟线。
- 北交所 `.BJ` 数据有兜底路径，但分红和部分历史数据覆盖率仍可能低于沪深市场。
- 流通市值字段当前没有单独数据源，页面使用总市值口径。
- 预警引擎是前端轮询，不是 WebSocket 推送。

---

## 文档导览

| 文档 | 用途 |
|---|---|
| [docs/API.md](docs/API.md) | 端点、请求响应和 curl 示例 |
| [docs/FIELD_CAPABILITIES.md](docs/FIELD_CAPABILITIES.md) | 筛选字段、缺失行为和不支持指标 |
| [docs/STRATEGIES.md](docs/STRATEGIES.md) | 内置策略、信号、限制和新增策略方式 |
| [docs/RAILWAY_DEPLOYMENT.md](docs/RAILWAY_DEPLOYMENT.md) | Railway 部署步骤 |
| [docs/基于千问的股票筛选系统设计与实现.docx](docs/基于千问的股票筛选系统设计与实现.docx) | 学年设计文档 |

---

## 致谢

- [Baostock](https://baostock.com/)：A 股数据主链路
- [AKShare](https://github.com/akfamily/akshare)：补充数据和兜底
- [FastAPI](https://github.com/fastapi/fastapi) / [Vue 3](https://github.com/vuejs/core)
- OpenAI 兼容生态 / 阿里云百炼 DashScope

---

**免责声明**：本项目仅用于课程学习和技术研究，不构成任何投资建议。
