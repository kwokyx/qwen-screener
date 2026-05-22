# 实现状态与交接清单

最后更新：2026-05-22 · 测试套件：**38/38 通过** · 总代码量：约 7500 行

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
| 千问 AI 客户端（FC + JSON + regex 三层降级 + 双后端切换 + 缓存） | [`services/qwen_client/`](../backend/app/services/qwen_client/) | ⚠️ 无单测，已手动端到端验证 |
| 个股投资分析（一次 + SSE 流式） | [`api/qwen.py`](../backend/app/api/qwen.py) | ⚠️ 无单测，已手动验证 |
| 对话历史持久化（跨设备同步） | [`api/chat.py`](../backend/app/api/chat.py) | ✅ `test_chat_sessions.py` |
| 通知中心（CRUD + 已读 / 全部已读） | [`api/notification.py`](../backend/app/api/notification.py) | ✅ `test_notifications.py` |
| 数据同步（雪球 + 新浪 + 东财多通路） | [`services/data_sync.py`](../backend/app/services/data_sync.py) | ✅ `test_data_sync_guard.py`（含 < 80% 防误删测试） |
| APScheduler 6 个定时任务 | [`services/scheduler.py`](../backend/app/services/scheduler.py) | ⚠️ 无单测，已观察到 cron 触发 |
| Redis 缓存（千问解析 + 个股分析） | [`services/cache.py`](../backend/app/services/cache.py) | ✅ `test_cache.py`（含静默回退测试） |
| SQLite 冷备份（每 6h） | [`services/db_backup.py`](../backend/app/services/db_backup.py) | ⚠️ 无单测，文件已生成 |
| 健康检查（AI / 数据 / 缓存 / 手动同步） | [`api/health.py`](../backend/app/api/health.py) | ⚠️ 无单测 |

### 前端

| 视图 | 文件 | 状态 |
|---|---|---|
| 登录 / 注册 | [`views/Login.vue`](../frontend/src/views/Login.vue) | ✅ |
| 行情 Dashboard（4 指数 + 板块 + 涨跌榜） | [`views/Dashboard.vue`](../frontend/src/views/Dashboard.vue) | ✅ 全部真实数据 |
| Chat（NL 筛选 + SSE 三阶段流式 + 历史） | [`views/Chat.vue`](../frontend/src/views/Chat.vue) | ✅ |
| Results（因子筛选 + 价值分排序） | [`views/Results.vue`](../frontend/src/views/Results.vue) | ✅ |
| 个股详情（K 线 + 千问流式 + 同行业对比） | [`views/Detail.vue`](../frontend/src/views/Detail.vue) | ✅（有部分 UI 占位见 §3） |
| Portfolio（自选 + 5 种预警 + 跨设备同步） | [`views/Portfolio.vue`](../frontend/src/views/Portfolio.vue) | ✅ |

---

## 2. 半实现 / 有已知限制 ⚠️

### 2.1 策略回测（Strategy） — 学年设计可接受
**位置**：[`services/backtest_engine.py`](../backend/app/services/backtest_engine.py) + [`views/Strategy.vue`](../frontend/src/views/Strategy.vue)

**能跑通的部分** ✅：
- 月度调仓、等权持有 top N
- 净值曲线、夏普、最大回撤、胜率、盈亏比、月度收益
- 4 个预设策略（高股息防御 / 低估值蓝筹 / 高 ROE 成长 / 高毛利消费）

**已知限制**：
1. **基本面 look-ahead bias** — 用「当前」PE/ROE 跑历史，没做 point-in-time 处理。论文「未来工作」要写明。
2. **交易日历近似** — 用「跳过周末」近似真实交易日，没接 tushare 交易日历。
3. **数据不足时合成填充** — DB 内某只股票历史 K 线 < 30 天时，用确定性高斯游走合成。返回 `data_source: "synthesized" | "mixed" | "real"` 透明告知。
4. **基准用「全持仓 buy-and-hold」**，不是真正的沪深300 指数对比。
5. **未做单测**：`test_backtest.py` 缺失。

### 2.2 行情板块涨跌幅 — 算法近似
**位置**：[`api/market.py`](../backend/app/api/market.py) `get_sectors`

板块 `change_pct` 用「今开 → 当日 close」，**不是真正的「昨收 → 今收」**。
原因：DB 内 `stock_daily` 没存 `prev_close` 字段。

**影响**：开盘没大跳空时差异很小（< 0.5%），但跳空高/低开时会失真。

**修法**：DB 加 `prev_close` 列，同步时填上一交易日 close。约 20 行代码。

### 2.3 涨停 / 跌停字段缺失
**位置**：[`views/Dashboard.vue`](../frontend/src/views/Dashboard.vue) 市场概况

AKShare 没提供涨跌停限价数据，**该字段未展示**（代码里有注释）。如果有 tushare token 可以补。

### 2.4 流通市值字段
**位置**：[`views/Detail.vue`](../frontend/src/views/Detail.vue) 头部指标

雪球接口未直接提供「流通市值」，当前用「总市值」代替。论文要写明。

### 2.5 预警引擎：轮询非推送
**位置**：[`services/alertEngine.js`](../frontend/src/services/alertEngine.js)

每 30s 轮询每只自选股最新价（GET `/stock/{code}`），触发预警。
**没用 WebSocket**，对学年设计场景够用，但真实使用会有 30s 延迟和电量消耗。

### 2.6 财务数据「最新一期」快照
**位置**：[`models/stock.py`](../backend/app/models/stock.py) `StockFinancial`

只存最新一期季报，没做时序回看。Detail 页财务表「近 5 期」是 UI 设计中预留的，**当前只显示 1 期**。

---

## 3. UI 占位（看着像有，实际未实现）🟡

> ⚠️ 演示 / 答辩时注意避开这些按钮，或者灰显处理。

| 位置 | 占位元素 | 现状 |
|---|---|---|
| Detail 页 K 线 tab 旁 | `MA / BOLL / MACD / KDJ / RSI` 指标按钮 | 仅 UI 标签，实际只画收盘价折线 |
| Detail 页底部 tab | `资金流向 / 十大股东 / 盘口 / 筹码分布 / 公告 / 研报` | 6 个 tab 中**只有「同行业对比」是真的**，其余 5 个空白 |
| Results 页左侧 | 「添加因子」按钮 | 无 click handler，纯装饰 |
| Chat 页输入框旁 | 「深度研究 / 联网检索 / 回测模式」3 个 mode 标签 | 装饰性，未实际改变 prompt |

---

## 4. 已知陷阱 / 配置坑 🔧

### 🔧 4.1 默认 OpenAI 配置不能直接用
**文件**：[`backend/.env.example`](../backend/.env.example)

默认值如下，**接手后必须改其中一项**：
```env
OPENAI_BASE_URL=https://api2.up.railway.app   # 第三方中转网关，可能下线
OPENAI_MODEL=gpt-5.4                          # 中转网关自定义别名，不是真实模型名
```

**接手时三选一**：
- 改 `OPENAI_BASE_URL=https://api.openai.com` + 真实 OpenAI Key + `OPENAI_MODEL=gpt-4o-mini`
- 切到 dashscope：`AI_BACKEND=dashscope` + `DASHSCOPE_API_KEY=sk-xxx`
- 用自己的 OpenAI 兼容网关，相应填 URL + MODEL

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
- [ ] 默认 OpenAI 配置改成可用项（见 4.1）
- [ ] 「千问评分」UI 文案改成「价值分」或真接通千问评分（见 4.2）
- [ ] Detail 页 6 个空 tab 灰显或删除（见 §3）
- [ ] K 线 5 个技术指标按钮：要么真实现 MA（最简单），要么 UI 加「敬请期待」

### 优先级 P1（影响真实使用 / 数据准确性）
- [ ] 板块涨跌用 `prev_close` 而非 `今开`（见 2.2）
- [ ] 财务数据时序回看（多期对比）
- [ ] 回测 point-in-time 处理（消除 look-ahead bias）
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
| qwen client | ❌ | ❌ | 手动验证 |
| qwen analysis | ❌ | ❌ | 手动验证 |
| market | ❌ | ❌ | 手动验证 |
| chat | ✅ `test_chat_sessions.py` | — | — |
| notifications | ✅ `test_notifications.py` | — | — |
| strategy / backtest | ❌ | ❌ | 手动验证 |
| data_sync | ✅ `test_data_sync_guard.py` | — | — |
| scheduler | ❌ | ❌ | 观察 |
| cache | ✅ `test_cache.py` | — | — |
| db_backup | ❌ | ❌ | 文件已生成 |
| health | ❌ | ❌ | 手动验证 |
| watchlist | ✅ `test_watchlist_sync.py` | — | — |

**全部 38 个测试用例通过**（pytest 输出 `38 passed in 29.33s`）。

---

## 7. 接手快速上手清单

1. **跑测试** `cd backend && pytest tests/ -v` → 应见 38 passed
2. **改 `.env`**：见 4.1，至少能调通一种 AI 后端
3. **拉数据**：`python -m scripts.sync_data full` → 沪深300 + 财务约 5 分钟
4. **启动**：`uvicorn app.main:app --reload` + `cd frontend && npm run dev`
5. **打开** http://localhost:5173，注册账号，去 `/chat` 试一句「低估值高分红的银行股」
6. **看本文档** §3 「UI 占位」，演示时避开
7. **看本文档** §4 「已知陷阱」，避免重复踩坑
8. **想加新功能** → 从 §5「未完成」P0/P1/P2 优先级里挑

---

## 8. 与外部资源的对应关系

| 外部依赖 | 用途 | 文件 |
|---|---|---|
| AKShare | A 股数据（多通路） | [`services/data_sync.py`](../backend/app/services/data_sync.py) |
| OpenAI Python SDK | LLM 调用主路径 | [`services/qwen_client/transport.py`](../backend/app/services/qwen_client/transport.py) |
| dashscope | 阿里千问备用通路 | 同上 |
| FastAPI / SQLAlchemy / APScheduler | 后端框架 | 全局 |
| Vue 3 / Vite / Pinia / Vue Router | 前端框架 | 全局 |
| Element Plus | **未使用** —— 设计时考虑过，最终用自渲染 A2 主题 | — |
| marked | Markdown 渲染（千问输出） | [`views/Detail.vue`](../frontend/src/views/Detail.vue) |

---

## 9. 论文「已知限制」一节建议照抄

> 受时间与数据源限制，本系统存在以下已知限制，列为未来工作方向：
>
> （1）回测引擎采用当前期基本面数据回看历史，存在 look-ahead bias，未来工作将接入 tushare 等付费数据源实现 point-in-time 处理；
>
> （2）交易日历采用「跳过周末」的简化策略，未处理节假日；
>
> （3）财务数据当前仅展示最新一期季报，未实现时序对比；
>
> （4）预警引擎采用客户端轮询（30s 间隔），未实现 WebSocket 推送；
>
> （5）部分技术指标（MA / BOLL / MACD / KDJ / RSI）以 UI 标签形式预留，未实现实际计算；
>
> （6）涨停跌停价、资金流向、十大股东、机构调研等深度数据受免费数据源限制未纳入。

---

## 联系

项目维护者：[kwokyx](https://github.com/kwokyx) · 许可证：[MIT](../LICENSE)
