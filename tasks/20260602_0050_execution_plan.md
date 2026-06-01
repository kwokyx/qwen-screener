# Goal

将智能筛选升级为真正的模型 Function Calling Agent：模型结合有限对话上下文自主选择工具并生成结构化参数，后端校验通过后才执行；AI 不可用、超时或输出非法时回退到现有本地规则 Agent。保留 SSE 分阶段体验，不重写无关功能。

# Current project context

- Worktree: `/Users/gyx/Documents/Playground/qwen-stock-screener-naive`
- Branch: `codex/naive-kline-refactor`
- Current AI package:
  - `backend/app/services/qwen_client/__init__.py`
  - `backend/app/services/qwen_client/transport.py`
- Existing `qwen_client.parse_nl_query()` already has a narrow OpenAI Function Calling path, but it forces the single `screen_stocks` tool. This is not the requested multi-tool Agent.
- Existing Chat Agent routing and fallback live in:
  - `backend/app/services/strategy_selector.py`
  - `backend/app/api/screener.py`
- Existing frontend SSE state and Chat inspector live in:
  - `frontend/src/composables/useNlStream.js`
  - `frontend/src/views/Chat.vue`
  - `frontend/src/api/screener.js`
- Existing schemas:
  - `backend/app/schemas/screener.py`
  - `backend/app/schemas/strategy.py`
- Existing safety behavior must remain:
  - vague confirmation without prior context asks for clarification
  - implicit empty conditions never execute full-market screening
  - explicit “全部股票 / 全市场 / 不加条件” may execute empty-condition screening
  - local rule Agent remains fallback
- Read `COMMIT_CONVENTION.md` before editing.
- Use CodeGraph first for symbol relationships when available.

# Allowed files or directories to modify

- `backend/app/services/qwen_client/`
- `backend/app/services/strategy_selector.py`
- `backend/app/api/screener.py`
- `backend/app/schemas/screener.py`
- `backend/app/schemas/strategy.py`
- `backend/tests/`
- `frontend/src/composables/useNlStream.js`
- `frontend/src/views/Chat.vue`
- `frontend/src/api/screener.js`
- `tasks/20260602_0050_execution_summary.md`

Modify fewer files if possible. Keep changes cohesive and minimal.

# Explicit forbidden actions

- Do not commit. Codex will review and commit.
- Do not reset, truncate, migrate, recreate, or clear the database.
- Do not alter baostock, akshare, data synchronization, K-line, Docker topology, or unrelated pages.
- Do not delete the existing local rule Agent.
- Do not hardcode fixed answers for the listed test phrases.
- Do not expose API keys, full prompts, raw model JSON, stack traces, `conditions=0`, raw `limit`, or raw `offset` in user-facing UI.
- Do not invent fake token streaming from the model. SSE should expose truthful stages.
- Do not revert edits made by others. You are not alone in this codebase.

# Architecture target

Implement a provider-facing adapter inside `backend/app/services/qwen_client/` for Chat Agent planning. The route must not know provider protocol details.

Expose these model-visible tools with constrained schemas:

1. `stock_screen`
   - structured conditions, logic, sort, pagination
2. `strategy_design`
   - design-only response with quantitative conditions; must not execute screening
3. `strategy_select`
   - existing strategy id and bounded limit
4. `explain_result`
   - explain prior result; must not re-screen
5. `ask_clarification`
   - request missing information; must not execute screening

The adapter should:

- compact recent conversation context before sending it to the model
- use native `tools` / `tool_choice="auto"` when the configured OpenAI-compatible provider supports it
- return a typed/validated planning result or a clean fallback signal
- keep protocol/provider details out of `backend/app/api/screener.py`
- log only safe summaries: chosen tool, model-vs-fallback source, validation outcome, execution outcome, concise failure reason

The backend must treat the model output as untrusted:

- validate tool name against an enum/allow-list
- validate all args using Pydantic or an equivalent explicit schema
- validate `FilterCondition.field`, operators, `sort_by`, `limit`, and `offset`
- reject implicit empty conditions unless the user explicitly requests the full market
- reject or downgrade unknown tools and illegal fields
- preserve local fallback routing when the model path is unavailable or invalid

Integrate the validated model plan into `strategy_selector.plan_chat_agent()`. Preserve local context-sensitive behavior as fallback. Avoid claiming a tool was selected before the model has actually selected it.

SSE stages should truthfully communicate:

- 正在判断需求
- 已选择工具
- 正在校验参数
- 正在执行筛选 / 生成策略 / 解释结果 / 请求补充信息
- 已生成结果

The frontend inspector must remain concise. Add only the minimum changes needed to display readable planning and validation steps.

# Step-by-step checklist

- [ ] Read current routing, schemas, transport, SSE route, Chat state machine, and existing tests.
- [ ] Add a model Function Calling planner adapter with five constrained tools and compact context.
- [ ] Add typed server-side validation for model-selected tool and args.
- [ ] Integrate model-first routing into `plan_chat_agent()` while preserving local fallback.
- [ ] Ensure `strategy_design`, `explain_result`, and `ask_clarification` never execute the screening engine.
- [ ] Ensure `stock_screen` executes only after validated non-empty conditions, except explicit full-market requests.
- [ ] Ensure `strategy_select` validates strategy id and bounded limit before execution.
- [ ] Replace misleading SSE preview text with truthful staged events.
- [ ] Keep frontend inspector readable and suppress raw internal params.
- [ ] Add backend tests for valid model tool choice, fallback, invalid args, unknown tool, empty conditions, explicit all-stock request, design-only flow, confirmation with and without context, explanation, sort adjustment, and pagination adjustment.
- [ ] Run focused pytest.
- [ ] Run frontend build if frontend changes.
- [ ] Write the execution summary file.

# Validation commands

Run at least:

```bash
cd /Users/gyx/Documents/Playground/qwen-stock-screener-naive
pytest backend/tests/test_strategy_agent.py backend/tests/test_screener_stream.py backend/tests/test_qwen_transport.py -q
```

If test collection requires backend cwd:

```bash
cd /Users/gyx/Documents/Playground/qwen-stock-screener-naive/backend
pytest tests/test_strategy_agent.py tests/test_screener_stream.py tests/test_qwen_transport.py -q
```

If frontend files changed:

```bash
cd /Users/gyx/Documents/Playground/qwen-stock-screener-naive/frontend
npm run build
```

Do not rebuild Docker in the delegated task unless needed to diagnose a test failure. Codex will do integration Docker and browser verification.

# Expected execution summary path

Write:

`tasks/20260602_0050_execution_summary.md`

The summary must include:

- files changed
- checklist completion status
- architecture and fallback notes
- commands run
- exact test/build results
- problems encountered
- items needing Codex review
