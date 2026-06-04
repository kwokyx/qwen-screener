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

async function fetchJson(url) {
  const response = await fetch(url)
  if (!response.ok) throw new Error(`HTTP ${response.status} for ${url}: ${await response.text()}`)
  return response.json()
}

async function probeApi(path) {
  const start = performance.now()
  const response = await fetch(`${BASE_URL}${path}`)
  const text = await response.text()
  return {
    path,
    status: response.status,
    elapsed_ms: Math.round(performance.now() - start),
    ok: response.ok,
    bytes: text.length,
  }
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
  await waitForExpression(cdp, 'document.body && document.body.innerText.includes("市场概况")', `page load ${url}`)
}

async function dashboardSnapshot(cdp) {
  return evaluate(cdp, `(() => {
    const text = document.body.innerText;
    const skeletons = document.querySelectorAll('.sk-line, .sk-metric, .dashboard-skeleton-row, .sector-skeleton-row, .strength-skeleton-row').length;
    const alerts = [...document.querySelectorAll('.n-alert')].map((el) => el.textContent.trim()).filter(Boolean);
    const rows = document.querySelectorAll('.n-data-table tbody tr').length;
    const cards = document.querySelectorAll('.terminal-card').length;
    const apiTimings = performance.getEntriesByType('resource')
      .filter((entry) => entry.name.includes('/api/v1/market/') || entry.name.includes('/api/v1/health/data'))
      .map((entry) => ({
        path: new URL(entry.name).pathname + new URL(entry.name).search,
        duration_ms: Math.round(entry.duration),
      }));
    return {
      href: location.href,
      hasDataFreshness: text.includes('数据 '),
      hasIndices: ['上证指数', '深证成指', '创业板指', '科创50'].some((name) => text.includes(name)),
      hasMarketStats: text.includes('上涨') && text.includes('下跌') && text.includes('总成交'),
      hasMovers: text.includes('市场异动'),
      hasSectors: text.includes('板块涨跌'),
      skeletons,
      alerts,
      rows,
      cards,
      apiTimings,
    };
  })()`)
}

async function mobileSnapshot(cdp) {
  return evaluate(cdp, `(() => {
    window.scrollTo(0, window.scrollY);
    const overflowers = [...document.querySelectorAll('.terminal-card, .market-overview-grid, .main-grid, .top-nav-inner')]
      .map((el) => {
        const rect = el.getBoundingClientRect();
        const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 70);
        return { text, left: Math.round(rect.left), right: Math.round(rect.right), width: Math.round(rect.width) };
      })
      .filter((item) => item.left < -2 || item.right > window.innerWidth + 2);
    return {
      innerWidth: window.innerWidth,
      scrollX: window.scrollX,
      bodyScrollWidth: document.documentElement.scrollWidth,
      overflowers,
      cards: document.querySelectorAll('.terminal-card').length,
      dataTables: document.querySelectorAll('.n-data-table').length,
    };
  })()`)
}

async function run() {
  const chromePath = findChrome()
  if (!chromePath) fail('Chrome executable not found. Set CHROME_PATH to run this smoke test.')

  const userDataDir = await mkdtemp(join(tmpdir(), 'qwen-dashboard-smoke-'))
  const stderrLines = []
  const apiProbeTimings = []
  for (const path of [
    '/api/v1/market/indices',
    '/api/v1/market/sectors?limit=20',
    '/api/v1/market/movers?limit=10',
    '/api/v1/market/ticker',
    '/api/v1/health/data',
  ]) {
    apiProbeTimings.push(await probeApi(path))
  }
  const failedProbe = apiProbeTimings.find((item) => !item.ok)
  if (failedProbe) fail('Dashboard API probe failed.', failedProbe)

  const debugPort = String(10222 + Math.floor(Math.random() * 1000))
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

    await setViewport(cdp, 1440, 900)
    await navigate(cdp, `${BASE_URL}/dashboard`)
    const loadingSeen = await evaluate(cdp, 'document.querySelectorAll(".sk-line, .sk-metric, .dashboard-skeleton-row, .sector-skeleton-row").length > 0')
    await waitForExpression(
      cdp,
      `(() => {
        const noSkeletons = document.querySelectorAll('.sk-line, .sk-metric, .dashboard-skeleton-row, .sector-skeleton-row, .strength-skeleton-row').length === 0;
        const hasClearFailure = document.body.innerText.includes('加载失败');
        const hasCoreContent = document.body.innerText.includes('市场异动') && document.body.innerText.includes('板块涨跌') && document.body.innerText.includes('市场概况');
        return noSkeletons && (hasCoreContent || hasClearFailure);
      })()`,
      'dashboard data blocks to resolve',
      60000,
    )
    const desktop = await dashboardSnapshot(cdp)
    if (!desktop.hasDataFreshness) fail('Data freshness badge did not render.', desktop)
    if (!desktop.hasMarketStats && !desktop.alerts.length) fail('Market overview neither rendered nor failed clearly.', desktop)
    if (!desktop.hasMovers && !desktop.alerts.length) fail('Market movers neither rendered nor failed clearly.', desktop)
    if (!desktop.hasSectors && !desktop.alerts.length) fail('Sectors neither rendered nor failed clearly.', desktop)

    await setViewport(cdp, 390, 844, true)
    await navigate(cdp, `${BASE_URL}/dashboard`)
    await waitForExpression(
      cdp,
      `document.querySelectorAll('.terminal-card').length >= 3 && document.body.innerText.includes('市场概况')`,
      'mobile dashboard content',
      60000,
    )
    const mobile = await mobileSnapshot(cdp)
    if (mobile.overflowers.length) fail('Mobile dashboard layout has visible overflow.', mobile)

    console.log(JSON.stringify({
      status: 'ok',
      baseUrl: BASE_URL,
      desktop: {
        loadingSeen,
        cards: desktop.cards,
        rows: desktop.rows,
        alerts: desktop.alerts,
        apiProbeTimings,
        apiTimings: desktop.apiTimings,
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
