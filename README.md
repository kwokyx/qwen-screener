# 变更说明：相对 kwokyx/qwen-screener 旧版基线

> 对比基准：`qwen-screener-main-old`（与 [kwokyx/qwen-screener](https://github.com/kwokyx/qwen-screener) 同源）  
> 当前分支：`feature/algorithm-scoring-scheme-b`  
> 日期：2026-05-26

---

## 摘要

本分支在旧版基础上完成 **方案 B（算法评分 + 千问解读）**、**深度分析与评分结论统一**、**因子筛选可配置**、**数据同步修复** 及 **DashScope 健康检查** 等改动。远程 `main` 未修改，请通过 Pull Request 由上级审核合并。

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

- `backend/app/prompts/stock_analysis.md`：评级词表由「推荐/强烈推荐」改为与算法一致的 **强烈关注 / 可关注 / 中性 / 谨慎**
- `qwen_client`：分析前注入 `score_total`、`score_verdict` 及四维子分，禁止模型推翻系统结论

---

## 3. 因子筛选页可配置

- `backend/app/schemas/screener.py`：`pool`、`list_years_min`
- `backend/app/services/screener_engine.py`：股票池与上市年限过滤
- `frontend/src/views/Results.vue`：左侧可编辑筛选（替代静态展示 + 硬编码条件）
- `frontend/src/api/screener.js`：传递 `pool`、`listYearsMin`

---

## 4. 数据同步与运维

- `backend/scripts/sync_data.py`：`daily-em` → `sync_full_valuation_em`，失败时提示备用 `pool` 命令
- `backend/app/services/data_sync.py`：行业东财兜底、东财接口重试

---

## 5. AI 配置与健康检查

- `backend/app/services/qwen_client/transport.py`：`AI_BACKEND=dashscope` 时检查 `DASHSCOPE_API_KEY`
- `backend/.env.example`：DashScope 优先说明、`QWEN_SCORE_CACHE_TTL`

---

## 6. 文档与 README

- `README.md`：英文标题与 maintainer 信息
- 新增 `docs/课题要求对照.md`、`docs/设计提交文档模板.md`
- 更新 `docs/API.md` 评分接口说明

---

## 7. Git 标签（本地）

| 标签 | 说明 |
|------|------|
| `archive/pre-algorithm-scoring` | 千问 JSON 全量打分中间态（`a6cc164`），可 `git checkout` 回退对比 |

---

## 部署提醒（不进 Git）

- 配置写在 `backend/.env`（非 `.env.example`）
- `AI_BACKEND=dashscope` 且填写 `DASHSCOPE_API_KEY`
- 修改 `.env` 后需：`docker compose up -d --force-recreate backend`

---

## 相关文档

- [股票评分实现方案.md](./股票评分实现方案.md) — 方案 B 规则与 API 说明
