# 变更说明：相对 kwokyx/qwen-screener 旧版基线

> 对比基准：`qwen-screener-main-old`（与 [kwokyx/qwen-screener](https://github.com/kwokyx/qwen-screener) 同源）  
> 当前分支：`feature/algorithm-scoring-scheme-b`  
> 维护者：[@inggg19](https://github.com/inggg19)  
> 最近更新：2026-05-26

**基于千问的股票筛选系统** — FastAPI + Vue 3 + AKShare。仅供学习研究，不构成投资建议。

| | |
|---|---|
| 仓库 | [github.com/kwokyx/qwen-screener](https://github.com/kwokyx/qwen-screener/tree/feature/algorithm-scoring-scheme-b) |
| 状态 | [docs/STATUS.md](docs/STATUS.md) |
| API | [docs/API.md](docs/API.md) |
| 综合分对齐 | [docs/修改说明.md](docs/修改说明.md) |
| License | [MIT](LICENSE) |

---

## 摘要

本分支在旧版基础上完成 **方案 B（算法评分 + 千问解读）**、**列表与详情综合分统一**、**条件选股页可配置与用户友好命名**、**数据新鲜度展示**、**策略回测（演示级）**、**数据同步修复** 及 **DashScope 健康检查** 等改动。远程 `main` 未修改，请通过 Pull Request 审核合并。

---

## 1. 方案 B：算法评分 + 千问解读

| 项目 | 旧版 | 本分支 |
|------|------|--------|
| 评分数字 | 详情页前端 `bullScore` 本地公式 | 后端 `score_engine.py` 公开分档表 + 加权 |
| API | 无 | `GET /api/v1/qwen/score/{code}` |
| 千问职责 | — | 仅生成 ≤40 字 `reason`（`stock_score_reason.md`） |
| 响应字段 | — | `source=algorithm`、`reason_source`、`breakdown` |

**新增文件**

- `backend/app/services/score_engine.py`
- `backend/app/prompts/stock_score_reason.md`
- `backend/app/schemas/qwen_score.py`（扩展）
- `backend/tests/test_score_engine.py`
- `docs/股票评分实现方案.md`

**修改文件**

- `backend/app/services/qwen_client/__init__.py` — `score_stock()` 先算法后千问 reason
- `backend/app/api/qwen.py`
- `frontend/src/views/Detail.vue` — 调用 `/qwen/score`，展示「算法评分 · 千问解读」
- `frontend/src/api/qwen.js`

---

## 2. 深度分析与评分结论一致

- `backend/app/prompts/stock_analysis.md`：评级词表改为与算法一致的 **强烈关注 / 可关注 / 中性 / 谨慎**
- `qwen_client`：分析前注入 `score_total`、`score_verdict` 及四维子分，禁止模型推翻系统结论

---

## 3. 综合分统一（列表 / 对话 / 详情）

- 条件选股页、千问筛选结果表、详情页 **同一时刻 `score_total` 一致**
- 列表删除前端 `bullScore()`，改由 `screener_engine` 写入 `score_total`
- 表格列名：**综合评分**（与详情对齐）

详见 [docs/修改说明.md](docs/修改说明.md)

---

## 4. 条件选股页（原「因子」页）

| 改动 | 说明 |
|------|------|
| 导航文案 | 顶栏「因子」→ **条件选股** |
| 左侧表单 | 可编辑股票池、市盈率/市值/ROE/成长等；**添加条件** |
| 后端 | `pool`、`list_years_min` 传入 `screener_engine` |
| 共用元数据 | `frontend/src/shared/screenerMeta.js` 统一字段中文名 |

**涉及文件**

- `backend/app/schemas/screener.py`、`backend/app/services/screener_engine.py`
- `frontend/src/views/Results.vue`、`frontend/src/api/screener.js`
- `frontend/src/components/TopBar.vue`、`frontend/src/router/index.js`

---

## 5. 策略回测（演示级，可选模块）

- 前端 `POST /api/v1/strategy/backtest` 调用后端 `backtest_engine`
- 给定筛选条件 + 时间窗 → 净值曲线、夏普、回撤、交易日志
- **限制**：K 线不足时用合成价格；基本面为当前快照，非历史 point-in-time（页内有警示）

---

## 6. 数据同步与运维

- `backend/scripts/sync_data.py`：`daily-em` 失败时提示备用 `pool` 命令
- `backend/app/services/data_sync.py`：行业东财兜底、东财接口重试
- `frontend/src/components/DataFreshness.vue`：展示各数据源最后同步时间
- `d9c2a3d`：`score_engine.snapshot_from_row` 与筛选侧字段对齐

---

## 7. AI 配置与健康检查

- `backend/app/services/qwen_client/transport.py`：`AI_BACKEND=dashscope` 时检查 `DASHSCOPE_API_KEY`
- `backend/.env.example`：DashScope 优先说明、`QWEN_SCORE_CACHE_TTL`

---

## 8. 文档

- 新增 `docs/修改说明.md`、`docs/股票评分实现方案.md`
- 更新 `docs/API.md` 评分与筛选接口说明

---

## 9. Git 标签（本地，可选回退）

| 标签 | 说明 |
|------|------|
| `archive/pre-algorithm-scoring` | 千问 JSON 全量打分中间态（`a6cc164`） |

---

## 部署提醒（不进 Git）

```bash
cp backend/.env.example backend/.env
# 填写 DASHSCOPE_API_KEY 或 OPENAI_API_KEY
docker compose up -d --build
# 修改 .env 后：
docker compose up -d --force-recreate backend
```

---

## 功能一览（本分支）

| 模块 | 路径 | 说明 |
|---|---|---|
| 行情 Dashboard | `/dashboard` | 大盘指数、行业涨跌 |
| 千问对话筛选 | `/chat` | 自然语言 → 结构化条件 → SSE 流式 |
| 条件选股 | `/results` | 表单配置 + 13 字段筛选 |
| 个股详情 | `/detail/:code` | K 线 + 算法综合分 + 千问解读 |
| 自选监控 | `/portfolio` | 自选股 + 价格预警 |
| 策略回测 | `/strategy` | 条件 + 时间窗 → 净值与指标（演示） |

---

## 相关文档

- [股票评分实现方案.md](docs/股票评分实现方案.md) — 方案 B 规则与 API
- [修改说明.md](docs/修改说明.md) — 综合分统一说明
- [STATUS.md](docs/STATUS.md) — 完成度与已知限制

---

**Disclaimer**：本项目仅用于学习与研究，不构成任何投资建议。
