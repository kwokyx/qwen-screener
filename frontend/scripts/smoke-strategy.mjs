#!/usr/bin/env node
import { existsSync } from 'node:fs'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'

const BASE_URL = (process.env.SMOKE_BASE_URL || 'http://127.0.0.1:8080').replace(/\/$/, '')
const STRATEGY_NAMES = [
  '海龟突破',
  '均线放量',
  'RPS 强势突破',
  '高位窄幅整理',
  '涨停后承接',
  '趋势急跌修复',
]

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
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} for ${url}: ${await response.text()}`)
  }
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
  const username = process.env.SMOKE_USERNAME || 'strategy_smoke'
  const password = process.env.SMOKE_PASSWORD || 'strategy_smoke_123456'
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
      for (const { reject } of this.pending.values()) {
        reject(new Error('Chrome DevTools socket closed'))
      }
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
  if (typeof WebSocket !== 'function') {
    fail('This smoke script requires Node.js with global WebSocket support.')
  }
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
    if (!ignoreLauncherExit && chrome.exitCode !== null) {
      fail('Chrome exited before DevTools was ready.', stderrLines.join(''))
    }
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
  if (result.exceptionDetails) {
    fail('Browser evaluation failed.', result.exceptionDetails)
  }
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

async function waitForExpressionMaybe(cdp, expression, timeoutMs = 2000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      if (await evaluate(cdp, expression)) return true
    } catch (err) {
      // Keep polling while Vue is replacing the document during navigation.
    }
    await delay(50)
  }
  return false
}

function browserClickHelperSource() {
  return `function smokeClick(el) {
    if (!el) return false;
    el.scrollIntoView({ block: 'center', inline: 'nearest' });
    const rect = el.getBoundingClientRect();
    const init = {
      bubbles: true,
      cancelable: true,
      view: window,
      clientX: rect.left + Math.max(1, rect.width / 2),
      clientY: rect.top + Math.max(1, rect.height / 2),
    };
    for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
      el.dispatchEvent(type.startsWith('pointer')
        ? new PointerEvent(type, init)
        : new MouseEvent(type, init));
    }
    return true;
  }`
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
  await waitForExpression(cdp, 'document.body && document.body.innerText.includes("策略选股")', `page load ${url}`)
}

async function seedAuth(cdp, loginData) {
  await cdp.send('Page.navigate', { url: `${BASE_URL}/login` })
  await waitForExpression(cdp, 'document.body', 'login origin load')
  await evaluate(cdp, `(() => {
    localStorage.setItem('token', ${JSON.stringify(loginData.access_token)});
    localStorage.setItem('user', ${JSON.stringify(JSON.stringify(loginData.user))});
    localStorage.removeItem('qwen-stock:saved-condition-strategies:v1');
    sessionStorage.removeItem('qwen-stock:strategy-page-state:v1');
    return true;
  })()`)
}

async function clickByText(cdp, text, options = {}) {
  const selector = options.selector || 'button,label,a,[role="button"]'
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

async function clickFirst(cdp, selector) {
  const result = await evaluate(cdp, `(() => {
    const el = document.querySelector(${JSON.stringify(selector)});
    if (!el) return { ok: false };
    el.scrollIntoView({ block: 'center', inline: 'nearest' });
    window.scrollTo(0, window.scrollY);
    el.click();
    return { ok: true, text: (el.innerText || el.textContent || '').trim() };
  })()`)
  if (!result?.ok) fail(`Could not click selector: ${selector}`)
  return result
}

async function chooseVisibleOrVirtualSelectOption(cdp, text, label = text) {
  const result = await evaluate(cdp, `(async () => {
    ${browserClickHelperSource()}
    const wanted = ${JSON.stringify(text)};
    const optionText = (el) => (el.innerText || el.textContent || '').trim();
    const findOption = () => [...document.querySelectorAll('.n-base-select-option')]
      .find((el) => optionText(el) === wanted);
    const scrollEl = document.querySelector('.n-virtual-list.v-vl')
      || document.querySelector('.n-base-select-menu .n-scrollbar')
      || document.querySelector('.n-base-select-menu');
    for (let step = 0; step < 36; step += 1) {
      const option = findOption();
      if (option) return { ok: smokeClick(option), text: optionText(option), step };
      if (!scrollEl) break;
      const maxTop = Math.max(0, (scrollEl.scrollHeight || 0) - (scrollEl.clientHeight || 0));
      scrollEl.scrollTop = Math.min(maxTop, step * 48);
      scrollEl.dispatchEvent(new Event('scroll', { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 80));
    }
    return {
      ok: false,
      reason: 'option not found',
      options: [...document.querySelectorAll('.n-base-select-option')]
        .map((el) => optionText(el))
        .filter(Boolean),
    };
  })()`)
  if (!result?.ok) fail(`Could not choose select option: ${label}.`, result)
  return result
}

async function verifyConditionBuilderDefault(cdp) {
  await waitForExpression(
    cdp,
    'document.body.innerText.includes("条件选股") && document.querySelectorAll(".condition-row").length === 0 && document.body.innerText.includes("暂无条件")',
    'empty structured condition builder',
  )
  await clickByText(cdp, '添加条件', { selector: 'button' })
  await waitForExpression(cdp, 'document.querySelectorAll(".condition-row").length === 1', 'first structured condition row')
  await waitForExpression(
    cdp,
    'document.querySelector(".condition-row .n-select .n-base-selection")',
    'structured field metadata',
  )
  return evaluate(cdp, `(() => ({
    ok: document.querySelectorAll('.condition-row').length === 1,
    sawEmptyDefault: true,
    rowText: (document.querySelector('.condition-row')?.innerText || '').replace(/\\s+/g, ' ').trim(),
  }))()`)
}

async function strategySnapshot(cdp) {
  return evaluate(cdp, `(() => {
    const rows = document.querySelectorAll('.n-data-table tbody tr').length;
    const emptyText = [...document.querySelectorAll('.n-empty')]
      .map((el) => el.textContent.trim())
      .filter(Boolean)
      .join(' | ');
    return {
      href: location.href,
      heading: document.querySelector('.table-head')?.textContent?.trim() || '',
      rows,
      emptyText,
      stockLinks: [...document.querySelectorAll('.stock-link')].map((el) => el.textContent.trim()).slice(0, 5),
      skeletonRows: document.querySelectorAll('.strategy-skeleton-row').length,
      strategyCards: document.querySelectorAll('.strategy-item:not(.skeleton-card)').length,
      disabledStrategyCards: [...document.querySelectorAll('.strategy-item:not(.skeleton-card)')].filter((el) => el.disabled).length,
      disabledExecuteButtons: [...document.querySelectorAll('button')]
        .filter((el) => el.textContent.includes('执行策略筛选') && el.disabled)
        .length,
    };
  })()`)
}

async function waitForRestoredStrategyResult(cdp, label, timeoutMs = 60000) {
  try {
    await waitForExpression(
      cdp,
      `(() => {
        const onStrategy = location.pathname === '/strategy';
        const rows = document.querySelectorAll('.n-data-table tbody tr').length;
        const text = document.body.innerText || '';
        const empty = text.includes('当前条件没有命中股票');
        const loading = text.includes('正在计算策略') || document.querySelectorAll('.strategy-skeleton-row').length > 0;
        return onStrategy && !loading && (rows > 0 || empty);
      })()`,
      label,
      timeoutMs,
    )
  } catch (err) {
    const snapshot = await strategySnapshot(cdp).catch((snapshotErr) => ({ snapshot_error: snapshotErr.message }))
    fail(`${err.message}\nLast strategy snapshot`, snapshot)
  }
}

async function mobileLayoutSnapshot(cdp) {
  return evaluate(cdp, `(() => {
    window.scrollTo(0, window.scrollY);
    const overflowers = [...document.querySelectorAll('.strategy-item, .strategy-action, .page-head, .table-loading')]
      .map((el) => {
        const rect = el.getBoundingClientRect();
        const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 60);
        return { text, left: Math.round(rect.left), right: Math.round(rect.right), width: Math.round(rect.width) };
      })
      .filter((item) => item.left < -2 || item.right > window.innerWidth + 2);
    const table = document.querySelector('.n-data-table');
    return {
      innerWidth: window.innerWidth,
      scrollX: window.scrollX,
      bodyScrollWidth: document.documentElement.scrollWidth,
      overflowers,
      tableClientWidth: table ? Math.round(table.clientWidth) : 0,
      tableScrollWidth: table ? Math.round(table.scrollWidth) : 0,
      strategyCards: document.querySelectorAll('.strategy-item:not(.skeleton-card)').length,
      executeButtonText: [...document.querySelectorAll('button')]
        .map((el) => (el.innerText || el.textContent || '').trim())
        .find((text) => text.includes('执行策略筛选')) || '',
    };
  })()`)
}

async function run() {
  const chromePath = findChrome()
  if (!chromePath) fail('Chrome executable not found. Set CHROME_PATH to run this smoke test.')

  const userDataDir = await mkdtemp(join(tmpdir(), 'qwen-strategy-smoke-'))
  const stderrLines = []
  const debugPort = String(9222 + Math.floor(Math.random() * 1000))
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
    const loginData = await createSmokeLogin()
    const port = await waitForChromePort(userDataDir, chrome, stderrLines, debugPort, launchWithOpen)
    const targets = await fetchJson(`http://127.0.0.1:${port}/json/list`)
    const pageTarget = targets.find((target) => target.type === 'page' && target.webSocketDebuggerUrl)
    if (!pageTarget) fail('No debuggable Chrome page target found.', targets)

    cdp = await connectCdp(pageTarget.webSocketDebuggerUrl)
    await cdp.send('Page.enable')
    await cdp.send('Runtime.enable')
    await seedAuth(cdp, loginData)

    await setViewport(cdp, 1440, 900)
    await navigate(cdp, `${BASE_URL}/strategy`)
    const conditionBuilder = await verifyConditionBuilderDefault(cdp)
    await clickByText(cdp, '保存为策略', { selector: 'button' })
    await waitForExpression(cdp, 'document.querySelectorAll(".saved-condition-entry").length === 1', 'saved condition strategy card')
    const savedConditionSelectClick = await evaluate(cdp, `(() => {
      const entry = document.querySelector('.saved-condition-entry');
      const card = entry?.querySelector('.saved-condition-card');
      if (!card) return { ok: false, reason: 'saved condition card not found' };
      card.scrollIntoView({ block: 'center', inline: 'nearest' });
      card.click();
      return { ok: true, text: card.textContent.trim() };
    })()`)
    if (!savedConditionSelectClick?.ok) fail('Saved condition strategy card is not clickable.', savedConditionSelectClick)
    await waitForExpression(cdp, 'document.querySelector(".saved-condition-entry")?.getAttribute("data-active") === "true"', 'saved condition selected')
    const savedConditionSelect = await evaluate(cdp, `(() => ({
      ok: document.querySelector('.saved-condition-entry')?.getAttribute('data-active') === 'true',
      rows: document.querySelectorAll('.n-data-table tbody tr').length,
    }))()`)
    if (!savedConditionSelect?.ok) fail('Saved condition strategy card was not selected.', savedConditionSelect)
    if (savedConditionSelect.rows) fail('Saved condition strategy card ran before explicit execute.', savedConditionSelect)
    await clickByText(cdp, '执行筛选', { selector: 'button' })
    const savedConditionRun = { ok: true, text: '执行筛选' }
    await waitForExpression(
      cdp,
      'document.querySelector(".n-data-table tbody tr") || document.body.innerText.includes("当前条件没有命中股票")',
      'saved condition strategy result table or empty state',
      60000,
    )
    const savedConditionSnapshot = await strategySnapshot(cdp)
    if (!savedConditionSnapshot.rows && !savedConditionSnapshot.emptyText.includes('当前条件没有命中股票')) {
      fail('Saved condition strategy did not finish with rows or a clear empty state.', savedConditionSnapshot)
    }
    await clickByText(cdp, '策略选股', { selector: 'label,button' })
    await waitForExpression(
      cdp,
      `(() => ${JSON.stringify(STRATEGY_NAMES)}.every((name) => document.body.innerText.includes(name)))()`,
      'six strategy cards',
    )

    const beforeRun = await strategySnapshot(cdp)
    if (beforeRun.strategyCards !== 6) fail('Expected 6 strategy cards.', beforeRun)
    if (beforeRun.rows !== 0) fail('Strategy page ran automatically before confirmation.', beforeRun)

    await clickByText(cdp, '涨停后承接', { selector: '.strategy-item' })
    await waitForExpression(cdp, 'document.querySelector(".table-head")?.textContent.includes("待筛选：涨停后承接")', 'selected strategy title')
    await clickByText(cdp, '执行策略筛选', { selector: 'button', last: true })

    const loadingSeen = await waitForExpressionMaybe(
      cdp,
      'document.body.innerText.includes("正在计算策略") || document.querySelectorAll(".strategy-skeleton-row").length > 0',
      3000,
    )
    await waitForExpression(
      cdp,
      'document.querySelector(".n-data-table tbody tr") || document.body.innerText.includes("当前条件没有命中股票")',
      'strategy result table or empty state',
      60000,
    )
    const afterRun = await strategySnapshot(cdp)
    if (!afterRun.rows && !afterRun.emptyText.includes('当前条件没有命中股票')) {
      fail('Strategy run finished without rows or a clear empty state.', afterRun)
    }

    let detail = null
    let afterBack = null
    if (afterRun.rows > 0) {
      const firstCode = await evaluate(cdp, 'document.querySelector(".strategy-page .stock-cell .stock-code")?.textContent.trim() || ""')
      await clickFirst(cdp, '.strategy-page .stock-cell .stock-link')
      await waitForExpression(cdp, 'location.pathname.startsWith("/detail/")', 'detail navigation')
      await waitForExpression(
        cdp,
        `document.querySelector(".detail-page .stock-code")?.textContent.includes(${JSON.stringify(firstCode)})`,
        'detail page content',
        60000,
      )
      detail = await evaluate(cdp, '({ href: location.href, code: document.querySelector(".detail-page .stock-code")?.textContent.trim(), name: document.querySelector(".detail-page .stock-name")?.textContent.trim() })')
      await evaluate(cdp, 'history.back(); true')
      await waitForExpression(cdp, 'location.pathname === "/strategy"', 'browser back to strategy')
      await waitForRestoredStrategyResult(cdp, 'restored strategy result after back')
      afterBack = await strategySnapshot(cdp)
    }

    await setViewport(cdp, 390, 844, true)
    await navigate(cdp, `${BASE_URL}/strategy`)
    await clickByText(cdp, '策略选股', { selector: 'label,button' })
    await waitForExpression(cdp, 'document.querySelectorAll(".strategy-item:not(.skeleton-card)").length === 6', 'mobile strategy cards')
    const mobile = await mobileLayoutSnapshot(cdp)
    if (mobile.overflowers.length) fail('Mobile strategy layout has visible overflow.', mobile)

    console.log(JSON.stringify({
      status: 'ok',
      baseUrl: BASE_URL,
      desktop: {
        conditionBuilder,
        savedConditionRun,
        savedConditionSnapshot,
        strategyCards: beforeRun.strategyCards,
        loadingSeen,
        heading: afterRun.heading,
        rows: afterRun.rows,
        emptyText: afterRun.emptyText,
        stockLinks: afterRun.stockLinks,
        detail,
        afterBack,
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
