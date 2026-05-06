# 基于千问的股票筛选系统

学年设计项目。后端 FastAPI + 前端 Vue 3，集成阿里千问大模型实现自然语言股票筛选与基本面分析。

## 项目结构

```
qwen-stock-screener/
├── backend/        # FastAPI 后端
├── frontend/       # Vue 3 前端（待创建）
└── docs/           # 论文素材：架构图、ER 图等
```

## 数据流

```
AKShare ─┬─ 全 A 股代码名（stock_info_a_code_name）─→ stock_basic
         ├─ 沪深300 成分股（index_stock_cons_csindex）─→ pool list
         ├─ 雪球个股快照（stock_individual_spot_xq）  ─→ stock_daily（PE/PB/股息率/市值）
         ├─ 雪球个股基本（stock_individual_basic_info_xq）─→ stock_basic（行业/上市时间）
         └─ 财务摘要（stock_financial_abstract）       ─→ stock_financial（ROE/营收/同比/毛利率/负债率）
```

> 东方财富批量接口（`stock_zh_a_spot_em`、`stock_individual_info_em`）在部分网络下会 RemoteDisconnected，
> 故采用「沪深300 + 雪球逐只」的稳定通路，300 只 ≈ 1 分钟，对学年设计 demo 足够。

## 后端快速开始

```bash
cd backend

# 1. 创建虚拟环境
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. 配置环境变量（已建好 MySQL）
cp .env.example .env
# 编辑 .env：
#   DATABASE_URL=mysql+pymysql://qwen:Qwen_Dev_Pwd_2026%21@127.0.0.1:3306/qwen_stock?charset=utf8mb4
#   DASHSCOPE_API_KEY=sk-xxx                      # 千问 API（自然语言筛选 + 个股分析需要）

# 3. 拉数据（首次约 5 分钟）
python -m scripts.sync_data full

# 4. 启动开发服务器
uvicorn app.main:app --reload --port 8000

# 浏览器：http://localhost:8000/docs   交互式 API 文档
```

## 同步数据子命令

```bash
python -m scripts.sync_data basic                # 全 A 股代码名（5500+ 只，几秒）
python -m scripts.sync_data pool [csi300]        # 雪球行情 + 估值（300 只，~1 分钟）
python -m scripts.sync_data industry [csi300]    # 行业 + 上市时间（~1 分钟）
python -m scripts.sync_data financial [csi300]   # ROE / 营收 / 同比 / 毛利率（~3 分钟）
python -m scripts.sync_data full                 # 上面四步全跑
```

支持的股票池：`csi300`（沪深300）、`csi500`（中证500）、`sse50`（上证50）。

## 主要 API（前缀 `/api/v1`）

| Method | Path | 说明 |
|---|---|---|
| POST | `/auth/register` | 注册 |
| POST | `/auth/login` | 登录获取 JWT |
| GET  | `/stock/search?q=平安` | 搜索股票 |
| GET  | `/stock/{code}` | 个股详情（行情 + 财务汇总） |
| GET  | `/stock/{code}/kline?days=120` | K 线数据 |
| POST | `/screener` | 多条件筛选（结构化 JSON） |
| POST | `/screener/nl` | **自然语言筛选**（核心创新点） |
| GET  | `/qwen/analysis/{code}` | 千问生成投资分析 |

## 筛选示例

### 1. 银行行业 + 高股息

```bash
curl -X POST http://localhost:8000/api/v1/screener \
  -H "Content-Type: application/json" \
  -d '{
    "conditions": [
      {"field":"industry","op":"eq","value":"银行"},
      {"field":"dividend_yield","op":"gt","value":4}
    ],
    "sort_by":"dividend_yield","limit":5
  }'
```

返回（沪深300 内）：兴业银行 / 招商银行 / 光大银行 / 华夏银行 / 上海银行

### 2. 自然语言筛选（千问）

```bash
curl -X POST http://localhost:8000/api/v1/screener/nl \
  -H "Content-Type: application/json" \
  -d '{"query": "ROE 大于 15 且最新季度净利润同比正增长的成长股"}'
```

返回会带 `parsed_conditions` 字段，回显千问解析出的结构化条件，论文截图利器。

## 支持的筛选字段

| 字段 | 含义 | 表 |
|---|---|---|
| pe / pb | 市盈率/市净率 | stock_daily |
| market_cap | 总市值（亿） | stock_daily |
| close / turnover | 收盘价/换手率 | stock_daily |
| dividend_yield | 股息率 % | stock_daily |
| roe | 净资产收益率 % | stock_financial |
| revenue_yoy / profit_yoy | 营收/净利同比 % | stock_financial |
| gross_margin / debt_ratio | 毛利率/资产负债率 % | stock_financial |
| industry / market | 行业/板块 | stock_basic |

操作符：`gt / gte / lt / lte / eq / between / in`

## 测试

```bash
pytest tests/ -v
```

## 定时任务

`app/services/scheduler.py` 用 APScheduler 注册了两个任务：

- 每个交易日 16:00 拉沪深300 行情快照
- 每周一 17:00 拉行业 + 财务摘要

uvicorn 启动后自动接管，关闭时优雅停止。

## 后续 Roadmap

- [x] W1 后端骨架、JWT、Swagger
- [x] W2 数据同步管道（行情 / 行业 / 财务）+ 定时任务
- [x] W3 筛选引擎（12 字段 × 7 操作符）
- [ ] W4 千问 prompt 调优、缓存、Function Calling 切换
- [ ] W5–W6 Vue 3 前端
- [ ] W7 测试 + Bug 修复
- [ ] W8 论文 + 答辩 PPT
