# 实现状态与交接清单

最后更新：2026-06-03 · 测试套件：**166/166 通过**

---

## 完成度图例

| 标记 | 含义 |
|---|---|
| ✅ | **已完成**，有测试或已端到端验证，可直接使用 |
| ⚠️ | **部分实现**，主路径可用但有已知限制（多数学年设计场景可接受） |
| 🟡 | **UI 占位**，前端有按钮 / tab 但后面没接通，演示时避开或加灰显 |
| ❌ | **未实现**，留给后续工作 |
| 🔧 | **已知陷阱**，配置或代码层面有坑，接手前务必读 |

---

## 1. 已完成模块（生产级可用）✅

### 后端

| 模块 | 文件 | 验证方式 |
|---|---|---|
| JWT 认证（注册 / 登录 / me） | [`api/auth.py`](../backend/app/api/auth.py) | ✅ `test_auth_e2e.py`（端到端） |
| 股票搜索 / 详情 / K 线 / 自选 CRUD | [`api/stock.py`](../backend/app/api/stock.py) | ✅ `test_stock_api.py` |
| 筛选引擎（13 字段 × 7 操作符 × AND/OR） | [`services/screener_engine.py`](../backend/app/services/screener_engine.py) | ✅ `test_screener.py` |
| NL 筛选（一次性 + SSE 流式三阶段） | [`api/screener.py`](../backend/app/api/screener.py) | ✅ `test_screener.py`（含端到端） |
| 千问 AI 客户端（FC + JSON + regex 三层降级 + 双后端切换 + 缓存） | [`services/qwen_client/`](../backend/app/services/qwen_client/) | ✅ `test_qwen_transport.py` + 手动端到端验证 |
| 个股投资分析（一次 + SSE 流式） | [`api/qwen.py`](../backend/app/api/qwen.py) | ⚠️ 无单测，已手动验证 |
| Agent 智能选股（结构化筛选工具 + 策略选股工具 + 本地降级规划） | [`services/strategy_selector.py`](../backend/app/services/strategy_selector.py) | ✅ `test_strategy_agent.py` + `test_strategy_scoring.py` |
| 对话历史持久化（跨设备同步） | [`api/chat.py`](../backend/app/api/chat.py) | ✅ `test_chat_sessions.py` |
| 通知中心（CRUD + 已读 / 全部已读） | [`api/notification.py`](../backend/app/api/notification.py) | ✅ `test_notifications.py` |
| 数据同步（Baostock 优先，AKShare 少量兜底） | [`services/data_sync.py`](../backend/app/services/data_sync.py) | ✅ `test_data_sync_guard.py` + `test_dividend_sync.py` |
| APScheduler 6 个定时任务 | [`services/scheduler.py`](../backend/app/services/scheduler.py) | ⚠️ 无单测，已观察到 cron 触发 |
| Redis 缓存（千问解析 + 个股分析） | [`services/cache.py`](../backend/app/services/cache.py) | ✅ `test_cache.py`（含静默回退测试） |
| SQLite 冷备份（每 6h） | [`services/db_backup.py`](../backend/app/services/db_backup.py) | ⚠️ 无单测，文件已生成 |
| 健康检查（AI / 数据 / 缓存 / 手动同步） | [`api/health.py`](../backend/app/api/health.py) | ✅ `test_health_api.py` |

### 前端

| 视图 | 文件 | 状态 |
|---|---|---|
| 登录 / 注册 | [`views/Login.vue`](../frontend/src/views/Login.vue) | ✅ |
| 行情 Dashboard（4 指数 + 板块 + 涨跌榜） | [`views/Dashboard.vue`](../frontend/src/views/Dashboard.vue) | ✅ 全部真实数据 |
| Chat（NL 筛选 + SSE 三阶段流式 + 历史） | [`views/Chat.vue`](../frontend/src/views/Chat.vue) | ✅ |
| Results（因子筛选 + 价值分排序） | [`views/Results.vue`](../frontend/src/views/Results.vue) | ✅ |
| 个股详情（K 线 + 千问流式 + 同行业对比） | [`views/Detail.vue`](../frontend/src/views/Detail.vue) | ✅（有部分 UI 占位见 §3） |
| Portfolio（自选 + 5 种预警 + 跨设备同步） | [`views/Portfolio.vue`](../frontend/src/views/Portfolio.vue) | ✅ |
| 智能选股工作台（自然语言 Agent + 条件筛选 + 策略选股） | [`views/Strategy.vue`](../frontend/src/views/Strategy.vue) | ✅ |

---

## 2. 半实现 / 有已知限制 ⚠️

### 2.1 策略选股（Strategy） — 主路径可用
**位置**：[`services/strategy_selector.py`](../backend/app/services/strategy_selector.py) + [`views/Strategy.vue`](../frontend/src/views/Strategy.vue)

**能跑通的部分** ✅：
- 自然语言 Agent 先规划工具，再调用真实本地数据筛选
- 结构化条件筛选：13 字段 × 7 操作符 × AND/OR
- 4 个参考 Sequoia-X 思路改写的策略：海龟突破、均线放量、RPS 强势突破、高位窄幅整理
- 数据不足的股票跳过或在结果表明确标记缺失字段，不合成行情

**已知限制**：
1. 策略使用本地最新日线实时计算，定位是「当前选股」，不是历史收益回测。
2. 免费数据源的财务字段是最新一期快照，适合条件筛选，不适合严肃历史回看。
3. 内置策略阈值仍需结合更多市场样本继续校准。

### 2.2 涨停 / 跌停字段缺失
**位置**：[`views/Dashboard.vue`](../frontend/src/views/Dashboard.vue) 市场概况

AKShare 没提供涨跌停限价数据，**该字段未展示**（代码里有注释）。如果有 tushare token 可以补。

### 2.3 流通市值字段
**位置**：[`views/Detail.vue`](../frontend/src/views/Detail.vue) 头部指标

当前未单独同步「流通市值」，详情页用「总市值」代替。论文要写明。

### 2.4 预警引擎：轮询非推送
**位置**：[`services/alertEngine.js`](../frontend/src/services/alertEngine.js)

每 30s 轮询每只自选股最新价（GET `/stock/{code}`），触发预警。
**没用 WebSocket**，对学年设计场景够用，但真实使用会有 30s 延迟和电量消耗。

### 2.5 财务数据「最新一期」快照
**位置**：[`models/stock.py`](../backend/app/models/stock.py) `StockFinancial`

只存最新一期季报，没做时序回看。Detail 页财务表「近 5 期」是 UI 设计中预留的，**当前只显示 1 期**。

---

## 3. UI 占位（看着像有，实际未实现）🟡

> ⚠️ 演示 / 答辩时注意避开这些按钮，或者灰显处理。

| 位置 | 占位元素 | 现状 |
|---|---|---|
| Detail 页底部 tab | `资金流向 / 十大股东 / 盘口 / 筹码分布 / 公告 / 研报` | 6 个 tab 中**只有「同行业对比」是真的**，其余 5 个空白 |
| Results 页左侧 | 「添加因子」按钮 | 无 click handler，纯装饰 |
| Chat 页输入框旁 | 旧版模式标签 | 装饰性，未实际改变 prompt；核心选股功能已迁移到 Strategy 工作台 |

---

## 4. 已知陷阱 / 配置坑 🔧

### 🔧 4.1 OpenAI 兼容网关需要匹配账号可用模型
**文件**：[`backend/.env.example`](../backend/.env.example)

当前示例默认走 OpenCode Go 的 OpenAI-compatible Chat Completions 接口：
```env
AI_BACKEND=openai
OPENAI_BASE_URL=https://opencode.ai/zen/go/v1
OPENAI_MODEL=qwen3.6-plus
OPENAI_RESPONSES_ENABLED=false
```

第三方网关或账号权限变化时，三选一：
- 继续使用 OpenCode Go：确认套餐包含当前 Qwen 模型，并保持 `OPENAI_RESPONSES_ENABLED=false`
- 改 `OPENAI_BASE_URL=https://api.openai.com/v1` + 真实 OpenAI Key + 账号可用模型
- 切到 dashscope：`AI_BACKEND=dashscope` + `DASHSCOPE_API_KEY=your-dashscope-key`
- 用自己的 OpenAI 兼容网关，相应填 URL + MODEL

验证：
```bash
curl -s http://127.0.0.1:8080/api/v1/health/ai
python3 backend/scripts/agent_smoke.py
python3 backend/scripts/release_smoke.py
```

`release_smoke.py` 是 P0 交付封版检查：确认 Docker 服务健康、AI/数据健康、SSE fast-path 不走模型、`stock_detail` 不筛选、真实筛选返回结果，并执行定向密钥扫描。若 `/health/ai` 返回 `ok=false`，脚本会以 `WARN` 明示上游不可达并继续验证本地兜底链路；若 `/health/data` 返回 `fresh=true` 但 `sync_warnings` 非空，应按异常任务处理补充数据问题，不要把它解读成所有同步任务都成功。

### 🔧 4.2 「价值分」不是 AI 评分
**文件**：[`views/Results.vue`](../frontend/src/views/Results.vue) / [`views/Chat.vue`](../frontend/src/views/Chat.vue)

UI 显示「千问评分 / 价值分 92」，**实际是固定加权公式**：
```js
60 + (25 - pe*0.5) + dividend_yield*2 + roe   // 各项 clamp 后求和
```

如果要换成真千问评分：在 backend 加一个 `/qwen/score/{code}` 端点，让千问基于 snapshot 给 0-100 分。

### 🔧 4.3 测试用文件 SQLite，不是 in-memory
**文件**：[`backend/tests/conftest.py`](../backend/tests/conftest.py)

历史教训：`sqlite:///:memory:` 是 **per-connection** 的，TestClient lifespan 和 db fixture 不是同一个连接，会看不到表。所以改用 `/tmp/pytest_qwen.db` 文件。

**改它要小心**：千万别改回 `:memory:`。

### 🔧 4.4 SQLite 路径在 docker 内 vs 本地不一样
**文件**：[`docker-compose.yml`](../docker-compose.yml)

docker 内强制覆盖为 `sqlite:////app/data/stock.db`（挂载卷），本地是 `./stock.db`（项目根）。
**两套环境的数据不通**。要迁移用 `docker cp qwen-backend:/app/data/stock.db .`

### 🔧 4.5 .env 包含真实密码，**绝对不要 commit**
`.gitignore` 已经拦了，但接手时小心别手动 force-add。

---

## 5. 未完成 / 后续工作 ❌

### 优先级 P0（影响 demo / 答辩）
- [ ] 「千问评分」UI 文案改成「价值分」或真接通千问评分（见 4.2）
- [ ] Detail 页 6 个空 tab 灰显或删除（见 §3）

### 优先级 P1（影响真实使用 / 数据准确性）
- [ ] 财务数据时序回看（多期对比）
- [ ] 接 tushare 交易日历

### 优先级 P2（工程化补强）
- [ ] 补单测：`test_market.py`, `test_backtest.py`, `test_qwen_stream.py`
- [ ] 千问 prompt 版本化（A/B 对比命中率）
- [ ] WebSocket 替代 alertEngine 轮询
- [ ] refresh token + 续期
- [ ] 错误监控：Sentry
- [ ] 性能监控：Prometheus + Grafana

### 优先级 P3（功能扩展）
- [ ] 多用户 / 用户管理后台
- [ ] 真实涨停跌停字段（需要 tushare）
- [ ] 资金流向 / 十大股东 / 公告 / 研报 数据接入
- [ ] 真实流通市值字段
- [ ] 因子筛选器 UI「添加因子」功能
- [ ] 移动端布局优化（当前只是不破版）

---

## 6. 测试覆盖矩阵

| 模块 | 单测 | 集成测 | 端到端 |
|---|---|---|---|
| auth | — | — | ✅ `test_auth_e2e.py` |
| stock | ✅ `test_stock_api.py` | — | — |
| screener engine | ✅ `test_screener.py` | ✅ | — |
| NL screener | — | ✅ `test_screener.py` | — |
| qwen client | ✅ `test_qwen_transport.py` | — | 手动验证 |
| qwen analysis | ❌ | ❌ | 手动验证 |
| market | ❌ | ❌ | 手动验证 |
| chat | ✅ `test_chat_sessions.py` | — | — |
| notifications | ✅ `test_notifications.py` | — | — |
| strategy selector / Agent | ✅ `test_strategy_scoring.py` | ✅ `test_strategy_agent.py` | 手动验证 |
| data_sync | ✅ `test_data_sync_guard.py` | — | — |
| scheduler | ❌ | ❌ | 观察 |
| cache | ✅ `test_cache.py` | — | — |
| db_backup | ❌ | ❌ | 文件已生成 |
| health | ✅ `test_health_api.py` | — | 手动验证 |
| watchlist | ✅ `test_watchlist_sync.py` | — | — |

**全部 166 个测试用例通过**（2026-06-03 Docker 环境执行 `docker compose exec -T backend pytest`）。

---

## 7. 接手快速上手清单

1. **跑测试** `docker compose exec -T backend pytest` → 应见 166 passed
2. **改 `.env`**：见 4.1，至少能调通一种 AI 后端
3. **拉数据**：`python -m scripts.sync_data full` → Baostock 全 A 基础信息、日线、财务与分红
4. **启动**：`uvicorn app.main:app --reload` + `cd frontend && npm run dev`
5. **打开** http://localhost:5173，注册账号，去 `/strategy` 试一句「低估值高分红的银行股」
6. **看本文档** §3 「UI 占位」，演示时避开
7. **看本文档** §4 「已知陷阱」，避免重复踩坑
8. **想加新功能** → 从 §5「未完成」P0/P1/P2 优先级里挑

---

## 8. 与外部资源的对应关系

| 外部依赖 | 用途 | 文件 |
|---|---|---|
| Baostock | A 股基础信息、日/周/月/分钟 K、财务与分红主链路 | [`services/data_sync.py`](../backend/app/services/data_sync.py) |
| AKShare | 少量实时行情与兼容兜底 | [`services/data_sync.py`](../backend/app/services/data_sync.py) |
| OpenAI Python SDK | LLM 调用主路径 | [`services/qwen_client/transport.py`](../backend/app/services/qwen_client/transport.py) |
| dashscope | 阿里千问备用通路 | 同上 |
| FastAPI / SQLAlchemy / APScheduler | 后端框架 | 全局 |
| Vue 3 / Vite / Pinia / Vue Router | 前端框架 | 全局 |
| Naive UI | 浅色专业金融终端组件库 | [`frontend/package.json`](../frontend/package.json) |
| klinecharts | 详情页 K 线、成交量副图和技术指标 | [`components/charts/KLineChart.vue`](../frontend/src/components/charts/KLineChart.vue) |
| marked | Markdown 渲染（千问输出） | [`views/Detail.vue`](../frontend/src/views/Detail.vue) |

---

## 9. 论文「已知限制」一节建议照抄

> 受时间与数据源限制，本系统存在以下已知限制，列为未来工作方向：
>
> （1）交易日历采用「跳过周末」的简化策略，未处理节假日；
>
> （2）财务数据当前仅展示最新一期季报，未实现时序对比；
>
> （3）预警引擎采用客户端轮询（30s 间隔），未实现 WebSocket 推送；
>
> （4）涨停跌停价、资金流向、十大股东、机构调研等深度数据受免费数据源限制未纳入。

---

## 联系

项目维护者：[kwokyx](https://github.com/kwokyx) · 许可证：[MIT](../LICENSE)
