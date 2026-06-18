# 基于千问的股票筛选系统

一个面向 A 股的智能选股系统，提供行情概览、条件选股、AI 自然语言选股、策略选股、自选股、预警通知、个股详情和数据健康检查。后端以本地行情和财务数据库为核心，AI 只负责理解用户意图和选择白名单工具，实际筛选、排序、策略计算和数据校验都由服务端确定性执行。

- 在线访问：<https://qwenstock.up.railway.app/>
- API 文档：[docs/API.md](docs/API.md)
- 策略说明：[docs/STRATEGIES.md](docs/STRATEGIES.md)
- 字段能力：[docs/FIELD_CAPABILITIES.md](docs/FIELD_CAPABILITIES.md)
- Railway 部署：[docs/RAILWAY_DEPLOYMENT.md](docs/RAILWAY_DEPLOYMENT.md)

---

## 功能概览

| 模块 | 路径 | 说明 |
|---|---|---|
| 登录注册 | `/login` | JWT 登录，注册和登录带图形验证码 |
| 市场概览 | `/dashboard` | 指数、板块、涨跌榜、成交额榜、数据新鲜度 |
| AI 选股 | `/chat` | 自然语言对话，支持筛选、解释、排序、分页、详情和策略工具 |
| 条件选股 | `/results` | 按估值、财务、行业、技术指标等字段组合筛选 |
| 策略选股 | `/strategy` | 运行 6 个内置日线策略，支持批量加入自选 |
| 自选与预警 | `/portfolio` | 自选股管理、价格/涨跌幅预警、通知中心和飞书推送 |
| 股票详情 | `/detail/:code?` | 基础信息、行情、K 线、分钟线和 AI 解读 |

---

## 系统架构

```text
Vue 3 SPA
  │
  │ REST API / SSE
  ▼
FastAPI 后端
  ├── SQLAlchemy：股票、行情、财务、自选、通知、对话等数据模型
  ├── 筛选引擎：字段校验、SQL 查询、排序分页、技术指标计算
  ├── bounded ReAct Agent：模型决策 + 后端白名单工具执行
  ├── 策略引擎：6 个内置日线策略
  ├── APScheduler：收盘后同步、周末回填、策略推送、冷备份
  ├── Redis：可选缓存，失败时自动降级
  └── Baostock / AKShare / Sina：行情、财务和补充数据
```

### 技术栈

| 层级 | 技术 |
|---|---|
| 后端 | Python、FastAPI、SQLAlchemy、Pydantic、APScheduler、pytest |
| 前端 | Vue 3、Vite、Vue Router、Pinia、Naive UI、klinecharts |
| 数据 | SQLite / MySQL、Redis、Baostock、AKShare、Sina |
| AI | OpenAI 兼容接口或 DashScope |
| 部署 | Docker Compose、nginx、Railway |

---

## 快速开始

### Docker Compose

```bash
cp backend/.env.example backend/.env
# 编辑 backend/.env，配置数据库、JWT 密钥和 AI 后端；不要提交真实 .env

docker compose up -d --build

# 首次初始化数据
docker compose exec -T backend python -m scripts.sync_data full

open http://localhost:8080
```

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

# 前端，另开终端
cd frontend
npm install
npm run dev
```

开发环境前端地址为 `http://localhost:5173`，Vite 会把 `/api` 代理到 `http://127.0.0.1:8000`。

---

## 关键配置

配置文件在 `backend/.env`，示例见 [backend/.env.example](backend/.env.example)。

| 变量 | 说明 |
|---|---|
| `DATABASE_URL` | 默认 SQLite，也可配置 MySQL |
| `REDIS_URL` | 可选缓存；不可用时自动退回无缓存模式 |
| `SECRET_KEY` | JWT 签名密钥，生产环境必须替换 |
| `AI_BACKEND` | `openai` 或 `dashscope` |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` | OpenAI 兼容接口配置 |
| `DASHSCOPE_API_KEY` / `QWEN_MODEL` | DashScope 配置 |
| `CORS_ORIGINS` | 允许访问后端的前端来源 |
| `FEISHU_*` | 飞书 webhook 或企业应用配置；不填则不推送 |

不要提交真实 API Key、`.env`、本地数据库或备份文件。

---

## 数据同步

数据主链路使用 Baostock，AKShare 和 Sina 用于补充或兜底。系统使用日 K、基础信息、估值、财务指标、现金分红和部分实时行情数据。

```bash
python -m scripts.sync_data <子命令>
```

| 子命令 | 说明 |
|---|---|
| `basic` | 同步股票基础信息 |
| `daily [days]` | 同步最近 N 天日 K，默认 5 天 |
| `kline [code] [days]` | 回填单只股票 K 线 |
| `financial [pool]` | 同步财务指标，支持 `csi300`、`csi500`、`all` |
| `dividend [code]` | 同步现金分红并计算 TTM 股息率 |
| `full` | 执行基础信息、日 K、财务和分红的完整同步 |

调度器随后端启动，默认按东八区运行：

| 时间 | 任务 |
|---|---|
| 交易日 15:05 | 收盘后行情快刷 |
| 交易日 15:30 | 全市场日 K 补偿 |
| 交易日 16:00 | 估值与股息率补充 |
| 交易日 18:00 | 策略扫描与飞书推送 |
| 周六 02:00 / 03:00 | 财务指标、现金分红 |
| 周日 02:00 / 03:00 | 股票列表、近期 K 线回填 |
| 每 6 小时 | SQLite 冷备份 |

`/api/v1/health/data` 会返回最新交易日、应到交易日、覆盖率、同步异常和卡住任务，不会把未达标数据伪装成新鲜数据。

---

## AI Agent 与策略

AI 选股采用 bounded ReAct：模型只输出动作，后端只执行白名单工具，并对参数做 schema 校验。模型超时、不可达、返回非法工具或请求不支持字段时，系统会普通回复或安全停止，不会把宽泛兜底结果伪装成 AI 筛选结果。

Agent 当前可使用的核心工具包括：

- `stock_screen`：结构化条件筛选
- `explain_result`：解释当前结果
- `sort/page`：排序与分页
- `stock_detail`：股票详情
- `strategy_select`：内置策略选股
- `ask_clarification`：条件不足或字段不支持时追问

策略模块保留 6 个日线策略：海龟突破、RPS 突破、均线放量、高紧旗形、涨停洗盘、上升趋势跌停。策略结果表示当前信号命中，不等于收益回测或投资评级。

---

## API 与测试

所有业务接口默认前缀为 `/api/v1`。本地 Swagger 地址为 `http://localhost:8000/docs`，线上后端 Swagger 由部署服务单独提供。

主要接口组：

- `/auth`：验证码、注册、登录、当前用户
- `/stock`：搜索、详情、行情、K 线、自选股
- `/screener`：条件选股和自然语言选股
- `/qwen`：个股 AI 解读
- `/strategy`：策略模板和策略执行
- `/market`：市场概览、指数、板块、榜单
- `/chat`：对话历史
- `/notifications`：通知和预警
- `/health`：AI、数据、缓存、同步和备份状态

常用验证命令：

```bash
docker compose exec -T backend pytest
docker compose exec -T backend python scripts/release_smoke.py

cd frontend
npm run build
npm run smoke:auth
npm run smoke:dashboard
npm run smoke:strategy
npm run smoke:chat
```

普通 pytest 不依赖真实 AI。需要验证真实模型时，先检查 `/api/v1/health/ai`，再运行 `scripts/agent_reliability_smoke.py`。

---

## 项目结构

```text
qwen-stock-screener-naive/
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI router
│   │   ├── models/       # SQLAlchemy 数据模型
│   │   ├── schemas/      # Pydantic 请求/响应模型
│   │   ├── services/     # Agent、筛选、策略、同步、缓存、通知
│   │   └── prompts/      # AI 提示词
│   ├── scripts/          # 数据同步和 smoke 脚本
│   └── tests/            # 后端测试
├── frontend/
│   ├── src/
│   │   ├── views/        # 页面
│   │   ├── components/   # 组件
│   │   ├── api/          # 接口封装
│   │   ├── stores/       # Pinia 状态
│   │   └── services/     # SSE、预警等前端服务
│   └── nginx.conf.template
├── docs/
├── docker-compose.yml
└── README.md
```

---

## 已知边界

- 财务指标是最新一期快照，适合当前选股，不适合严肃历史回测。
- 内置策略是规则信号扫描，不是收益回测。
- 免费数据源存在延迟和覆盖差异，系统会在健康检查中暴露同步异常。
- 分钟 K 依赖数据源实时查询，失败时返回错误，不用日线伪装分钟线。
- 流通市值字段当前没有单独数据源，页面使用总市值口径。
- 预警通知由前端轮询和后端通知接口配合完成，不是 WebSocket 实时推送。

---

## 致谢

- [Baostock](https://baostock.com/)：A 股数据主链路
- [AKShare](https://github.com/akfamily/akshare)：补充数据
- [FastAPI](https://github.com/fastapi/fastapi) / [Vue 3](https://github.com/vuejs/core)

**免责声明**：本项目仅用于课程学习和技术研究，不构成任何投资建议。
