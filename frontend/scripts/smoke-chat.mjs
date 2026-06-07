#!/usr/bin/env node
import { existsSync } from 'node:fs'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'

const BASE_URL = (process.env.SMOKE_BASE_URL || 'http://127.0.0.1:8080').replace(/\/$/, '')

function findChrome() {
  const candidates = [
    process.env.CHROME_PATH,
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium-browser',
    '/usr/bin/chromium',
  ].filter(Boolean)
  return candidates.find((item) => existsSync(item))
}

function fail(message, details) {
  const suffix = details ? `\n${JSON.stringify(details, null, 2)}` : ''
  throw new Error(`${message}${suffix}`)
}

async function fetchJson(url, options) {
  const response = await fetch(url, options)
  if (!response.ok) throw new Error(`HTTP ${response.status} for ${url}: ${await response.text()}`)
  return response.json()
}

async function createCaptchaPayload() {
  const body = await fetchJson(`${BASE_URL}/api/v1/auth/captcha`)
  const encoded = body.image.split(',')[1] || ''
  const svg = Buffer.from(encoded, 'base64').toString('utf8')
  const code = [...svg.matchAll(/<text[^>]*>([^<]+)<\/text>/g)].map((item) => item[1]).join('')
  if (!body.id || code.length < 4) fail('Failed to parse captcha for smoke login')
  return { captcha_id: body.id, captcha_code: code }
}

async function createSmokeLogin() {
  const username = process.env.SMOKE_USERNAME || `chat_smoke_${Date.now().toString(36)}`
  const password = process.env.SMOKE_PASSWORD || 'chat_smoke_123456'
  const registerResponse = await fetch(`${BASE_URL}/api/v1/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, ...(await createCaptchaPayload()) }),
  })
  if (!registerResponse.ok && registerResponse.status !== 400) {
    throw new Error(`HTTP ${registerResponse.status} for smoke user registration: ${await registerResponse.text()}`)
  }
  const form = new URLSearchParams({ username, password, ...(await createCaptchaPayload()) })
  return fetchJson(`${BASE_URL}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: form,
  })
}

class CdpClient {
  constructor(ws) {
    this.ws = ws
    this.nextId = 1
    this.pending = new Map()
    ws.onmessage = (event) => {
      const message = JSON.parse(event.data)
      if (!message.id || !this.pending.has(message.id)) return
      const { resolve, reject } = this.pending.get(message.id)
      this.pending.delete(message.id)
      if (message.error) reject(new Error(`${message.error.message}: ${message.error.data || ''}`))
      else resolve(message.result || {})
    }
    ws.onclose = () => {
      for (const { reject } of this.pending.values()) reject(new Error('Chrome DevTools socket closed'))
      this.pending.clear()
    }
  }

  send(method, params = {}) {
    const id = this.nextId
    this.nextId += 1
    this.ws.send(JSON.stringify({ id, method, params }))
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject })
    })
  }

  close() {
    this.ws.close()
  }
}

async function connectCdp(wsUrl) {
  if (typeof WebSocket !== 'function') fail('This smoke script requires Node.js with global WebSocket support.')
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl)
    ws.onopen = () => resolve(new CdpClient(ws))
    ws.onerror = () => reject(new Error(`Failed to connect to ${wsUrl}`))
  })
}

async function waitForChromePort(userDataDir, chrome, stderrLines, expectedPort, ignoreLauncherExit = false) {
  if (process.env.CHROME_DEBUG_PORT) return process.env.CHROME_DEBUG_PORT
  const portFile = join(userDataDir, 'DevToolsActivePort')
  const deadline = Date.now() + 30000
  while (Date.now() < deadline) {
    if (!ignoreLauncherExit && chrome.exitCode !== null) fail('Chrome exited before DevTools was ready.', stderrLines.join(''))
    if (expectedPort) {
      try {
        await fetchJson(`http://127.0.0.1:${expectedPort}/json/version`)
        return expectedPort
      } catch (err) {
        // Chrome has not opened the debugging endpoint yet.
      }
    }
    const stderr = stderrLines.join('')
    const stderrMatch = stderr.match(/DevTools listening on ws:\/\/[^:]+:(\d+)\//)
    if (stderrMatch?.[1]) return stderrMatch[1]
    if (existsSync(portFile)) {
      const [port] = (await readFile(portFile, 'utf8')).trim().split('\n')
      if (port) return port
    }
    await delay(100)
  }
  fail('Timed out waiting for Chrome DevTools port.', stderrLines.join(''))
}

async function evaluate(cdp, expression) {
  const result = await cdp.send('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true,
  })
  if (result.exceptionDetails) fail('Browser evaluation failed.', result.exceptionDetails)
  return result.result?.value
}

async function waitForExpression(cdp, expression, label, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs
  let lastError = ''
  while (Date.now() < deadline) {
    try {
      if (await evaluate(cdp, expression)) return true
    } catch (err) {
      lastError = err.message
    }
    await delay(100)
  }
  fail(`Timed out waiting for ${label}.`, lastError)
}

async function setViewport(cdp, width, height, mobile = false) {
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width,
    height,
    mobile,
    deviceScaleFactor: mobile ? 3 : 1,
  })
}

async function navigate(cdp, url) {
  await cdp.send('Page.navigate', { url })
  await waitForExpression(
    cdp,
    'location.pathname === "/chat" && document.querySelector("textarea")',
    `page load ${url}`,
  )
}

async function seedAuth(cdp, loginData) {
  await cdp.send('Page.navigate', { url: `${BASE_URL}/login` })
  await waitForExpression(cdp, 'document.body', 'login origin load')
  await evaluate(cdp, `(() => {
    localStorage.setItem('token', ${JSON.stringify(loginData.access_token)});
    localStorage.setItem('user', ${JSON.stringify(JSON.stringify(loginData.user))});
    return true;
  })()`)
}

async function clickByText(cdp, text, options = {}) {
  const selector = options.selector || 'button,a,[role="button"]'
  const index = options.last ? 'matches.length - 1' : '0'
  const result = await evaluate(cdp, `(() => {
    const text = ${JSON.stringify(text)};
    const selector = ${JSON.stringify(selector)};
    const matches = [...document.querySelectorAll(selector)].filter((el) => {
      const content = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
      const rect = el.getBoundingClientRect();
      return content.includes(text) && rect.width > 0 && rect.height > 0 && !el.disabled;
    });
    const el = matches[${index}];
    if (!el) {
      return {
        ok: false,
        available: [...document.querySelectorAll(selector)]
          .map((node) => (node.innerText || node.textContent || '').replace(/\\s+/g, ' ').trim())
          .filter(Boolean)
          .slice(0, 30),
      };
    }
    el.scrollIntoView({ block: 'center', inline: 'nearest' });
    window.scrollTo(0, window.scrollY);
    el.click();
    return { ok: true, tag: el.tagName, text: (el.innerText || el.textContent || '').trim() };
  })()`)
  if (!result?.ok) fail(`Could not click text: ${text}`, result)
  return result
}

const CHAT_SSE_MOCK_SOURCE = `(() => {
      if (window.__chatSmokeMockInstalled) return;
      window.__chatSmokeMockInstalled = true;
      const originalFetch = window.fetch.bind(window);
      window.__chatSmokeCalls = [];
      window.__chatSmokeCompletions = [];
      const stocks = [
        {
          code: '600036.SH',
          name: '招商银行',
          industry: '银行',
          close: 40.2,
          change_pct: 0.82,
          pe: 6.1,
          pb: 0.88,
          roe: 15.4,
          dividend_yield: 5.2,
          score: 92,
          signals: ['股息率 5.2%', 'PE 6.1'],
        },
        {
          code: '601009.SH',
          name: '南京银行',
          industry: '银行',
          close: 10.8,
          change_pct: -0.28,
          pe: 5.5,
          pb: 0.72,
          roe: 16.8,
          dividend_yield: 5.8,
          score: 89,
          signals: ['股息率 5.8%', 'PB 0.72'],
        },
      ];
      const secondPageStocks = [
        {
          code: '601166.SH',
          name: '兴业银行',
          industry: '银行',
          close: 18.1,
          change_pct: 0.2,
          pe: 5.7,
          pb: 0.64,
          roe: 13.2,
          dividend_yield: 5.0,
          score: 86,
          signals: ['下一批结果', '股息率 5.0%'],
        },
      ];
      const strategyStocks = [
        {
          code: '688256.SH',
          name: '寒武纪',
          industry: '半导体',
          close: 1299.2,
          change_pct: -4.39,
          pe: 300.44,
          pb: 18.2,
          roe: 32.8,
          dividend_yield: 0.12,
          score: 96,
          signals: ['海龟突破', '成交额过亿'],
        },
        {
          code: '688041.SH',
          name: '海光信息',
          industry: '半导体',
          close: 274.06,
          change_pct: -4.1,
          pe: 233.67,
          pb: 12.4,
          roe: 11.96,
          dividend_yield: 0.03,
          score: 91,
          signals: ['阶段新高', '趋势强势'],
        },
      ];
      const designConditions = [
        { field: 'roe', op: 'gte', value: 12 },
        { field: 'dividend_yield', op: 'gte', value: 3 },
        { field: 'debt_ratio', op: 'lte', value: 70 },
      ];
      const bankConditions = [
        { field: 'industry', op: 'in', value: ['银行'] },
        { field: 'pe', op: 'lte', value: 8 },
        { field: 'dividend_yield', op: 'gte', value: 4.5 },
      ];
      const aiStatus = {
        source: 'ai_agent',
        used: true,
        fallback: false,
        configured: true,
        label: 'AI Agent',
      };
      const chatOnlyStatus = {
        source: 'ai_agent',
        used: true,
        fallback: false,
        configured: true,
        label: 'AI Agent',
      };
      function plan(tool, label, conditions = []) {
        return {
          tool,
          tool_label: label,
          logic: 'AND',
          conditions,
          sort_by: tool === 'result_sort' ? 'dividend_yield' : 'score',
          sort_desc: true,
          ai_configured: true,
          ai_used: true,
        };
      }
      function toolCall(name, label, status = 'done', result = {}, message = '') {
        return { id: name, name, label, status, result, message };
      }
      function resultEvent(items, offset = 0, conditions = bankConditions, sortBy = 'score', resultTool = null, resultLabel = null, timings = null) {
        const tool = resultTool || (sortBy === 'dividend_yield' ? 'result_sort' : 'stock_screen');
        const label = resultLabel || (tool === 'result_sort' ? '结果排序' : '股票筛选');
        return {
          type: 'result',
          plan: plan(tool, label, conditions),
          conditions,
          logic: 'AND',
          sort_by: sortBy,
          sort_desc: true,
          limit: 20,
          offset,
          total: 3,
          trade_date: '2026-06-04',
          parsed_conditions: conditions,
          items,
          ai_status: aiStatus,
          tool_trace: ['ReAct step 1: 模型选择 ' + tool, '调用 screener_engine.screen'],
          tool_calls: [toolCall(tool, label, 'done', { total: 3 })],
          timings: timings || { planning_ms: 940, model_ms: 920, tool_ms: 18, fallback_reason: null },
        };
      }
      function textEvents(query, tool, label, answer, conditions = [], status = aiStatus) {
        const calls = label === '普通回复'
          ? [toolCall('tool_router', '意图判断', 'done', { tool, label }, '模型判断这是普通对话')]
          : [toolCall(tool, label, 'done', {}, '未执行股票筛选')];
        return [
          { type: 'thinking', text: '模型判断下一步。' },
          {
            type: 'planning',
            plan: plan(tool, label, conditions),
            answer,
            conditions,
            ai_status: status,
            tool_trace: ['ReAct final：模型未调用工具，直接回答'],
            tool_calls: calls,
            timings: { planning_ms: 860, model_ms: 860, tool_ms: 0, fallback_reason: null },
          },
          {
            type: 'agent',
            plan: plan(tool, label, conditions),
            answer,
            conditions,
            ai_status: status,
            tool_trace: ['ReAct final：模型未调用工具，直接回答'],
            tool_calls: calls,
            timings: { planning_ms: 860, model_ms: 860, tool_ms: 0, fallback_reason: null },
          },
          { type: 'done' },
        ];
      }
      function eventsFor(query) {
        if (query === '你好') {
          return textEvents(query, 'ask_clarification', '普通回复', '你好，我可以帮你筛选 A 股、解释上一轮结果，或查看个股详情。', [], chatOnlyStatus);
        }
        if (query === '可以，做吧') {
          return textEvents(query, 'ask_clarification', '补充追问', '还没有可执行的筛选条件，请先告诉我选股目标。');
        }
        if (query === '这个 Agent 是什么') {
          return textEvents(
            query,
            'ask_clarification',
            '普通回复',
            '**有界选股 Agent** 可以执行：\\n\\n- 明确选股条件\\n- 内置策略、结果解释、排序、分页和详情定位\\n\\n普通 AI 对话不会自动调用本地筛选工具。',
            [],
            chatOnlyStatus,
          );
        }
        if (query === '找最近强势突破的股票') {
          const strategyPlan = {
            ...plan('strategy_select', '策略选股', []),
            strategy_id: 'turtle_breakout',
            ai_used: true,
          };
          return [
            { type: 'thinking', text: '模型选择内置策略。' },
            {
              type: 'planned',
              plan: strategyPlan,
              conditions: [],
              ai_status: aiStatus,
              tool_trace: ['ReAct step 1: 模型选择 strategy_select', '策略：海龟突破'],
              tool_calls: [toolCall('strategy_select', '策略选股', 'running', {}, '执行海龟突破')],
              timings: { planning_ms: 920, model_ms: 920, tool_ms: 0, fallback_reason: null },
            },
            {
              type: 'screening',
              tool: 'strategy_select',
              tool_label: '策略选股',
              tool_call: toolCall('strategy_select', '策略选股', 'running', {}, '执行海龟突破'),
              timings: { planning_ms: 920, model_ms: 920, tool_ms: 18, fallback_reason: null },
            },
            {
              type: 'agent',
              plan: strategyPlan,
              answer: '已匹配内置策略「海龟突破」，命中 2 只，前排结果：寒武纪、海光信息。',
              conditions: [],
              ai_status: aiStatus,
              result: {
                total: 2,
                offset: 0,
                limit: 20,
                trade_date: '2026-06-04',
                parsed_conditions: [],
                strategy: { id: 'turtle_breakout', name: '海龟突破' },
                items: strategyStocks,
              },
              tool_trace: ['ReAct step 1: 模型选择 strategy_select', '调用 strategy_selector.run_strategy_selection'],
              tool_calls: [toolCall('strategy_select', '策略选股', 'done', { total: 2, strategy_id: 'turtle_breakout' }, '策略选股完成')],
              timings: { planning_ms: 920, model_ms: 920, tool_ms: 18, fallback_reason: null },
            },
            { type: 'done' },
          ];
        }
        if (query === '为什么这些股票排在前面') {
          return textEvents(query, 'explain_result', '结果解释', '招商银行排在前面，主要因为银行行业、低估值和较高股息率同时满足上一轮条件。', bankConditions);
        }
        if (query === '按股息率排序') {
          return [
            { type: 'thinking', text: '复用上一轮结果，调整排序。' },
            {
              type: 'planned',
              plan: plan('result_sort', '结果排序', bankConditions),
              conditions: bankConditions,
              ai_status: aiStatus,
              tool_trace: ['ReAct step 1: 模型选择 result_sort'],
              tool_calls: [toolCall('result_sort', '结果排序', 'running', {}, '按股息率排序')],
              timings: { planning_ms: 780, model_ms: 780, tool_ms: 0, fallback_reason: null },
            },
            resultEvent([...stocks].reverse(), 0, bankConditions, 'dividend_yield'),
            { type: 'done' },
          ];
        }
        if (query === '换一批') {
          return [
            { type: 'thinking', text: '读取下一批结果。' },
            {
              type: 'planned',
              plan: { ...plan('result_sort', '结果分页', bankConditions), offset: 2 },
              conditions: bankConditions,
              ai_status: aiStatus,
              tool_trace: ['ReAct step 1: 模型选择 result_sort'],
              tool_calls: [toolCall('result_sort', '结果分页', 'running', {}, '下一批结果')],
              timings: { planning_ms: 760, model_ms: 760, tool_ms: 0, fallback_reason: null },
            },
            resultEvent(secondPageStocks, 2, bankConditions, 'score', 'result_sort', '结果分页'),
            { type: 'done' },
          ];
        }
        if (query === '查看第一只详情') {
          const detailCall = toolCall('stock_detail', '个股详情', 'done', { code: '600036.SH', name: '招商银行' }, '目标 招商银行');
          return [
            { type: 'thinking', text: '定位上一轮第一只股票。' },
            {
              type: 'agent',
              plan: plan('stock_detail', '个股详情', []),
              answer: '已定位第一只股票：招商银行，可以打开详情页查看本地行情和 K 线。',
              conditions: [],
              ai_status: aiStatus,
              tool_trace: ['ReAct step 1: 模型选择 stock_detail', '未调用 screener_engine.screen：详情工具'],
              tool_calls: [detailCall],
              timings: { planning_ms: 720, model_ms: 720, tool_ms: 0, fallback_reason: null },
            },
            { type: 'done' },
          ];
        }
        if (query === '帮我设计一个稳健的选股策略，先别执行') {
          return [
            { type: 'thinking', text: '只设计策略，不执行筛选。' },
            {
              type: 'design',
              plan: plan('strategy_design', '策略设计', designConditions),
              answer: '策略设计：优先选择 ROE 稳定、股息率不低、资产负债率可控的公司；先不执行筛选。',
              conditions: designConditions,
              ai_status: aiStatus,
              tool_trace: ['ReAct step 1: 模型选择 strategy_design', '不调用 screener_engine：仅设计策略'],
              tool_calls: [toolCall('strategy_design', '策略设计', 'done', {}, '仅生成条件')],
              timings: { planning_ms: 900, model_ms: 900, tool_ms: 0, fallback_reason: null },
            },
            { type: 'done' },
          ];
        }
        if (query === '现在执行') {
          return [
            { type: 'thinking', text: '执行上一轮策略条件。' },
            {
              type: 'planned',
              plan: plan('stock_screen', '股票筛选', designConditions),
              conditions: designConditions,
              ai_status: aiStatus,
              tool_trace: ['ReAct step 1: 模型选择 stock_screen'],
              tool_calls: [toolCall('stock_screen', '股票筛选', 'running')],
              timings: { planning_ms: 820, model_ms: 820, tool_ms: 0, fallback_reason: null },
            },
            resultEvent(stocks, 0, designConditions),
            { type: 'done' },
          ];
        }
        return [
          { type: 'thinking', text: '解析筛选条件。' },
          {
            type: 'planned',
            plan: plan('stock_screen', '股票筛选', bankConditions),
            conditions: bankConditions,
            ai_status: aiStatus,
            tool_trace: ['ReAct step 1: 模型选择 stock_screen'],
            tool_calls: [toolCall('stock_screen', '股票筛选', 'running')],
            timings: { planning_ms: 1200, model_ms: 1200, tool_ms: 0, fallback_reason: null },
          },
          {
            type: 'screening',
            tool: 'stock_screen',
            tool_label: '股票筛选',
            tool_call: toolCall('stock_screen', '股票筛选', 'running'),
            timings: { planning_ms: 1200, model_ms: 1200, tool_ms: 12, fallback_reason: null },
          },
          resultEvent(stocks, 0, bankConditions, 'score', null, null, {
            planning_ms: 4,
            model_ms: 1200,
            tool_ms: 18,
            fallback_reason: null,
          }),
          { type: 'done' },
        ];
      }
      function frame(event) {
        return 'data: ' + JSON.stringify(event) + '\\n\\n';
      }
      window.fetch = async (input, init = {}) => {
        const url = typeof input === 'string' ? input : input?.url || String(input);
        if (!url.includes('/api/v1/screener/nl/stream')) {
          return originalFetch(input, init);
        }
        const body = JSON.parse(init.body || '{}');
        const query = body.query || '';
        const events = eventsFor(query);
        window.__chatSmokeCalls.push({
          query,
          tools: [...new Set(events.flatMap((ev) => [
            ev.plan?.tool,
            ev.tool_call?.name,
            ...(ev.tool_calls || []).map((call) => call.name),
          ]).filter(Boolean))],
          resultEvents: events.filter((ev) => ev.type === 'result').length,
          hasEmbeddedResult: events.some((ev) => ev.type === 'agent' && ev.result),
          terminal: events.find((ev) => ev.type === 'agent' || ev.type === 'design' || ev.type === 'result') || null,
        });
        const encoder = new TextEncoder();
        const stream = new ReadableStream({
          start(controller) {
            let index = 0;
            function push() {
              if (index >= events.length) {
                window.__chatSmokeCompletions.push(query);
                controller.close();
                return;
              }
              controller.enqueue(encoder.encode(frame(events[index])));
              index += 1;
              setTimeout(push, 20);
            }
            push();
          },
        });
        return new Response(stream, {
          status: 200,
          headers: { 'Content-Type': 'text/event-stream; charset=utf-8' },
        });
      };
    })();`

async function installMockChatSse(cdp) {
  await cdp.send('Page.addScriptToEvaluateOnNewDocument', {
    source: CHAT_SSE_MOCK_SOURCE,
  })
}

async function ensureMockChatSse(cdp) {
  const installed = await evaluate(cdp, `${CHAT_SSE_MOCK_SOURCE}\nwindow.__chatSmokeMockInstalled === true`)
  if (!installed) fail('Chat mock SSE failed to install in current document.')
}

async function sendChat(cdp, query, expectedText, expectedTool, expectsResult) {
  await evaluate(cdp, `(() => {
    const input = document.querySelector('textarea');
    if (!input) return false;
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
    if (setter) setter.call(input, ${JSON.stringify(query)});
    else input.value = ${JSON.stringify(query)};
    input.focus();
    input.dispatchEvent(new InputEvent('input', {
      bubbles: true,
      inputType: 'insertText',
      data: ${JSON.stringify(query)},
    }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  })()`)
  await waitForExpression(
    cdp,
    `[...document.querySelectorAll('button')].some((btn) => {
      const label = [btn.textContent, btn.getAttribute('title'), btn.getAttribute('aria-label')].join(' ');
      return label.includes('发送') && !btn.disabled;
    })`,
    `send button enabled for ${query}`,
  )
  const clicked = await evaluate(cdp, `(() => {
    const matches = [...document.querySelectorAll('button')].filter((btn) => {
      const label = [btn.textContent, btn.getAttribute('title'), btn.getAttribute('aria-label')].join(' ');
      const rect = btn.getBoundingClientRect();
      return label.includes('发送') && rect.width > 0 && rect.height > 0 && !btn.disabled;
    });
    const el = matches[matches.length - 1];
    if (!el) return false;
    el.scrollIntoView({ block: 'center', inline: 'nearest' });
    el.click();
    return true;
  })()`)
  if (!clicked) fail(`Could not click send button for ${query}`)
  await waitForExpression(
    cdp,
    `window.__chatSmokeCompletions && window.__chatSmokeCompletions.includes(${JSON.stringify(query)})`,
    `mock SSE completion for ${query}`,
  )
  await waitForExpression(
    cdp,
    `document.body.innerText.includes(${JSON.stringify(expectedText)})`,
    `chat response text for ${query}`,
  )
  await waitForExpression(
    cdp,
    `(() => {
      const input = document.querySelector('textarea');
      const stopping = [...document.querySelectorAll('button')].some((btn) => {
        const label = [btn.textContent, btn.getAttribute('title'), btn.getAttribute('aria-label')].join(' ');
        return label.includes('停止');
      });
      return input && !input.disabled && !stopping;
    })()`,
    `chat ready after ${query}`,
    5000,
  )
  const call = await evaluate(cdp, `window.__chatSmokeCalls[window.__chatSmokeCalls.length - 1]`)
  if (!call?.tools?.includes(expectedTool)) fail(`Unexpected tool for ${query}.`, call)
  if (expectsResult && call.resultEvents < 1 && !call.hasEmbeddedResult) fail(`Expected result payload for ${query}.`, call)
  if (!expectsResult && call.resultEvents !== 0) fail(`Did not expect result event for ${query}.`, call)
  return call
}

async function chatSnapshot(cdp) {
  return evaluate(cdp, `(() => {
    const text = document.body.innerText;
    return {
      href: location.href,
      turns: document.querySelectorAll('.conversation-turn, .msg-pair').length,
      resultPreviews: document.querySelectorAll('.result-preview').length,
      toolRows: [...document.querySelectorAll('.tool-call-row')]
        .map((el) => el.textContent.replace(/\\s+/g, ' ').trim())
        .slice(-8),
      runtimeRows: [...document.querySelectorAll('.runtime-row')]
        .map((el) => el.textContent.replace(/\\s+/g, ' ').trim())
        .slice(-4),
      detailButtons: [...document.querySelectorAll('.agent-detail-button')]
        .map((el) => el.textContent.replace(/\\s+/g, ' ').trim()),
      hasFullResults: text.includes('完整列表'),
      hasFallbackReason: text.includes('未执行原因') || text.includes('本地快速路径') || text.includes('模型耗时') || text.includes('ReAct 模型'),
      markdown: {
        strongCount: document.querySelectorAll('.agent-answer-panel strong').length,
        listItemCount: document.querySelectorAll('.agent-answer-panel li').length,
        leakedBoldMarkers: text.includes('**有界选股 Agent**'),
      },
      calls: window.__chatSmokeCalls || [],
    };
  })()`)
}

async function run() {
  const chromePath = findChrome()
  if (!chromePath) fail('Chrome executable not found. Set CHROME_PATH to run this smoke test.')

  const loginData = await createSmokeLogin()
  const userDataDir = await mkdtemp(join(tmpdir(), 'qwen-chat-smoke-'))
  const stderrLines = []
  const debugPort = String(11222 + Math.floor(Math.random() * 1000))
  const chromeArgs = [
    ...(process.platform === 'darwin' ? [] : ['--headless=new']),
    '--disable-gpu',
    '--disable-dev-shm-usage',
    '--disable-background-networking',
    '--no-proxy-server',
    '--proxy-server=direct://',
    '--proxy-bypass-list=*',
    '--no-first-run',
    '--no-default-browser-check',
    '--remote-debugging-address=127.0.0.1',
    `--remote-debugging-port=${process.env.CHROME_DEBUG_PORT || debugPort}`,
    `--user-data-dir=${userDataDir}`,
    'about:blank',
  ]
  const launchWithOpen = false
  const chrome = spawn(chromePath, chromeArgs, { stdio: ['ignore', 'ignore', 'pipe'] })
  chrome.stderr.on('data', (chunk) => stderrLines.push(chunk.toString()))

  let cdp
  try {
    const port = await waitForChromePort(userDataDir, chrome, stderrLines, debugPort, launchWithOpen)
    const targets = await fetchJson(`http://127.0.0.1:${port}/json/list`)
    const pageTarget = targets.find((target) => target.type === 'page' && target.webSocketDebuggerUrl)
    if (!pageTarget) fail('No debuggable Chrome page target found.', targets)

    cdp = await connectCdp(pageTarget.webSocketDebuggerUrl)
    await cdp.send('Page.enable')
    await cdp.send('Runtime.enable')
    await installMockChatSse(cdp)
    await seedAuth(cdp, loginData)

    await setViewport(cdp, 1440, 900)
    await navigate(cdp, `${BASE_URL}/chat`)
    await ensureMockChatSse(cdp)

    const calls = []
    calls.push(await sendChat(cdp, '你好', '你好，我可以帮你筛选', 'ask_clarification', false))
    calls.push(await sendChat(cdp, '这个 Agent 是什么', '有界选股 Agent', 'ask_clarification', false))
    calls.push(await sendChat(cdp, '可以，做吧', '还没有可执行的筛选条件', 'ask_clarification', false))
    calls.push(await sendChat(cdp, '低估值高分红的银行股', '命中 3 只', 'stock_screen', true))
    calls.push(await sendChat(cdp, '找最近强势突破的股票', '策略选股结果', 'strategy_select', true))
    calls.push(await sendChat(cdp, '为什么这些股票排在前面', '招商银行排在前面', 'explain_result', false))
    calls.push(await sendChat(cdp, '按股息率排序', '南京银行', 'result_sort', true))
    calls.push(await sendChat(cdp, '换一批', '兴业银行', 'result_sort', true))
    calls.push(await sendChat(cdp, '帮我设计一个稳健的选股策略，先别执行', '策略设计', 'strategy_design', false))
    calls.push(await sendChat(cdp, '现在执行', '命中 3 只', 'stock_screen', true))
    calls.push(await sendChat(cdp, '查看第一只详情', '打开详情', 'stock_detail', false))

    await clickByText(cdp, '打开详情', { selector: 'button' })
    await waitForExpression(cdp, 'location.pathname.startsWith("/detail/")', 'detail navigation', 60000)
    await waitForExpression(cdp, 'document.body.innerText.includes("600036") || document.body.innerText.includes("招商银行")', 'detail content', 60000)
    const detailHref = await evaluate(cdp, 'location.href')
    await evaluate(cdp, 'history.back(); true')
    await waitForExpression(cdp, 'location.pathname === "/chat"', 'browser back to chat')
    await waitForExpression(
      cdp,
      'location.pathname === "/chat" && document.querySelectorAll(".conversation-turn, .msg-pair").length >= 11',
      'chat state after back',
    )

    await cdp.send('Page.reload')
    await waitForExpression(cdp, 'location.pathname === "/chat" && document.body.innerText.includes("现在执行")', 'chat refresh restore')
    const desktop = await chatSnapshot(cdp)
    if (desktop.turns < 11) fail('Chat did not render the expected multi-turn thread.', desktop)
    if (!desktop.hasFullResults) fail('Chat result preview did not expose full results.', desktop)
    if (!desktop.hasFallbackReason) fail('Chat runtime panel did not expose fallback/timing details.', desktop)
    if (desktop.markdown.strongCount < 1 || desktop.markdown.listItemCount < 2 || desktop.markdown.leakedBoldMarkers) {
      fail('Chat AI Markdown did not render structured content.', desktop.markdown)
    }
    if (!calls.some((call) => call.query === '这个 Agent 是什么' && call.terminal?.plan?.tool_label === '普通回复')) {
      fail('Chat smoke did not preserve the plain-chat model-final route.', calls)
    }
    if (!calls.some((call) => call.query === '找最近强势突破的股票' && call.hasEmbeddedResult && call.terminal?.plan?.tool === 'strategy_select')) {
      fail('Chat smoke did not preserve the strategy_select model-action route.', calls)
    }

    await setViewport(cdp, 390, 844, true)
    await navigate(cdp, `${BASE_URL}/chat`)
    await waitForExpression(cdp, 'document.body.innerText.includes("现在执行")', 'mobile chat restore')
    const mobile = await evaluate(cdp, `(() => {
      window.scrollTo(0, window.scrollY);
      const overflowers = [...document.querySelectorAll('.ai-page, .ai-shell, .main-panel, .thread-shell, .chat-scroll, .msg-pair, .result-preview, .result-preview-row, .composer, textarea')]
        .map((el) => {
          const rect = el.getBoundingClientRect();
          const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 60);
          return { text, left: Math.round(rect.left), right: Math.round(rect.right), width: Math.round(rect.width) };
        })
        .filter((item) => item.left < -2 || item.right > window.innerWidth + 2);
      return {
        innerWidth: window.innerWidth,
        scrollX: window.scrollX,
        bodyScrollWidth: document.documentElement.scrollWidth,
        turns: document.querySelectorAll('.conversation-turn, .msg-pair').length,
        overflowers,
      };
    })()`)
    if (mobile.overflowers.length) fail('Mobile chat layout has visible overflow.', mobile)

    console.log(JSON.stringify({
      status: 'ok',
      baseUrl: BASE_URL,
      desktop: {
        turns: desktop.turns,
        resultPreviews: desktop.resultPreviews,
        toolRows: desktop.toolRows,
        runtimeRows: desktop.runtimeRows,
        detailHref,
        calls: calls.map((call) => ({
          query: call.query,
          tools: call.tools,
          resultEvents: call.resultEvents,
          hasEmbeddedResult: call.hasEmbeddedResult,
        })),
      },
      mobile,
    }, null, 2))
  } finally {
    if (cdp) {
      await Promise.race([
        cdp.send('Browser.close').catch(() => {}),
        delay(500),
      ])
      cdp.close()
    }
    if (!launchWithOpen) {
      chrome.kill('SIGTERM')
    } else if (!process.env.CHROME_DEBUG_PORT) {
      spawnSync('pkill', ['-f', `remote-debugging-port=${debugPort}`], { stdio: 'ignore' })
    }
    await delay(300)
    await rm(userDataDir, { recursive: true, force: true }).catch(() => {})
  }
}

run().catch((err) => {
  console.error(err.message)
  process.exitCode = 1
})
