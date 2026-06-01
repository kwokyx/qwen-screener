# Execution Summary: 智能筛选升级为模型 Function Calling Agent

**Branch**: `codex/naive-kline-refactor`
**Date**: 2026-06-02

## Files changed

| File | Change |
|---|---|
| `backend/app/services/qwen_client/agent_planner.py` | 新增 OpenAI-compatible 原生 Function Calling 适配层，暴露五个受约束工具并校验模型参数 |
| `backend/app/services/qwen_client/__init__.py` | 导出模型规划入口 |
| `backend/app/services/strategy_selector.py` | 接入模型优先、规则降级的 Agent 路由，保留多轮承接、本地工具执行与空条件防护 |
| `backend/app/services/screener_engine.py` | 在 SQL 构建前校验筛选参数和排序字段 |
| `backend/app/api/screener.py` | SSE 改为真实阶段事件：判断、选工具、校验、执行、返回 |
| `backend/app/schemas/screener.py` | 限制筛选分页范围 |
| `backend/app/schemas/strategy.py` | 限制 Agent 规划分页范围 |
| `frontend/src/composables/useNlStream.js` | 发送紧凑的多轮上下文和历史摘要 |
| `frontend/src/views/Chat.vue` | AI 不可用时允许本地规则降级发送，并隐藏执行面板中的技术参数 |
| `backend/tests/test_agent_planner.py` | 新增模型 FC 参数校验、未知工具、非法 JSON 和紧凑上下文测试 |
| `backend/tests/test_screener.py` | 新增 SQL 前置参数校验测试 |
| `backend/tests/test_strategy_agent.py` | 新增模型优先、多轮承接、空条件防护、设计和降级回归测试 |
| `backend/tests/test_screener_stream.py` | 新增 SSE 分阶段与 FC 回归测试 |

## Checklist

- [x] 暴露 `stock_screen`、`strategy_design`、`strategy_select`、`explain_result`、`ask_clarification`
- [x] 使用原生 `tools` / `tool_choice=auto`，协议封装在适配层
- [x] AI 可用时优先由模型结合上下文选择工具；失败后回退规则 Agent
- [x] 模型参数经过 Pydantic 校验，SQL 参数经过筛选引擎二次校验
- [x] 默认禁止空条件筛选；仅显式“全部股票”等请求允许全市场
- [x] 多轮上下文包含会话、上一轮工具、条件、结果摘要、前排股票、工具调用摘要和最近六轮摘要
- [x] SSE 展示真实阶段，不伪造模型输出过程
- [x] 前端不展示原始 JSON、`limit`、`offset`、`conditions=0` 或堆栈
- [x] AI 网关不可用时聊天页显示降级状态，但仍允许发送
- [x] 未修改数据库、行情同步、baostock 和 K 线逻辑

## Validation

```text
python3 -m compileall -q backend/app backend/tests
git diff --check
frontend: npm run build
docker compose -p qwen-stock-screener up -d --build backend frontend
docker exec qwen-backend sh -lc 'cd /app && python -m pytest -q'
```

Results:

- Backend: `127 passed`
- Focused Agent suite: `75 passed`
- Frontend production build: passed
- Docker: backend, frontend and redis healthy

Real SSE checks through `http://127.0.0.1:8080/api/v1/screener/nl/stream`:

| Case | Result |
|---|---|
| 低估值高分红的银行股 | `stock_screen`, 4 conditions, 35 stocks |
| 帮我设计一个稳健的选股策略，列出量化条件 | `strategy_design`, no screening |
| 可以，做吧（有上下文） | reused 2 conditions, 120 stocks |
| 可以，做吧（无上下文） | `ask_clarification`, no screening |
| 为什么第一只股票命中？ | `explain_result`, no rescreen |
| 按股息率从高到低排序 | reused conditions, dividend sort |
| 换一批 | reused conditions, offset advanced to 2 |
| 查看全部股票 | explicit empty-condition screen, 5525 stocks |

Browser checks:

- `/chat`: AI gateway HTTP 503 is shown as local-rule fallback; send button becomes enabled after input; no console errors
- `/results`: default route shows an empty state instead of the full market
- `/results?source=agent`: restores the saved Agent conditions and renders 18 results; no console errors

## Problems encountered

1. The configured upstream AI gateway currently returns HTTP 503. Production runtime therefore uses the verified local-rule fallback.
2. Claude Code attempted local dependency installation despite the plan. Codex stopped that path and ran tests in the Docker environment.
3. `pytest-asyncio` emits a deprecation warning because `asyncio_default_fixture_loop_scope` is not explicitly configured. It does not fail the suite.

## Remaining risk

- The model FC protocol is covered with fake OpenAI-compatible responses and the fallback path is verified end to end. A successful live model call still depends on the upstream gateway recovering from HTTP 503.
