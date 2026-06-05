#!/usr/bin/env node
import { existsSync } from 'node:fs'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'

const BASE_URL = (process.env.SMOKE_BASE_URL || 'http://127.0.0.1:8080').replace(/\/$/, '')
const DETAIL_PATH = '/detail/600036.SH'

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
      } catch {
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

async function navigateDetail(cdp) {
  await cdp.send('Page.navigate', { url: `${BASE_URL}${DETAIL_PATH}` })
  await waitForExpression(
    cdp,
    'location.pathname === "/detail/600036.SH" && document.body.innerText.includes("招商银行")',
    'detail page content',
    60000,
  )
}

async function detailSnapshot(cdp) {
  return evaluate(cdp, `(() => {
    const text = document.body.innerText || '';
    const canvases = [...document.querySelectorAll('canvas')].map((el) => {
      const rect = el.getBoundingClientRect();
      return {
        width: el.width,
        height: el.height,
        clientWidth: Math.round(rect.width),
        clientHeight: Math.round(rect.height),
      };
    });
    const klineContainers = [...document.querySelectorAll('[class*="kline"], [class*="chart"]')]
      .map((el) => {
        const rect = el.getBoundingClientRect();
        return {
          className: String(el.className),
          text: (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 120),
          width: Math.round(rect.width),
          height: Math.round(rect.height),
        };
      })
      .filter((item) => item.width > 0 && item.height > 0)
      .slice(0, 12);
    const blockingErrorText = [...document.querySelectorAll('.n-alert, .status-desc, .empty-state, .section-card')]
      .map((el) => (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim())
      .find((item) => /加载失败|接口异常/.test(item)) || '';
    const overflowers = [...document.querySelectorAll('.detail-page, .section-card, .chart-card, .quote-card, .n-card')]
      .map((el) => {
        const rect = el.getBoundingClientRect();
        const nodeText = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 70);
        return { text: nodeText, left: Math.round(rect.left), right: Math.round(rect.right), width: Math.round(rect.width) };
      })
      .filter((item) => item.left < -2 || item.right > window.innerWidth + 2);
    return {
      href: location.href,
      hasCode: text.includes('600036'),
      hasName: text.includes('招商银行'),
      hasLocalQuote: text.includes('本地日线') || text.includes('交易日'),
      hasKlineText: text.includes('K 线走势') || text.includes('日线') || text.includes('均线'),
      hasLargeCanvas: canvases.some((item) => item.clientWidth >= 300 && item.clientHeight >= 200),
      hasKlineContainer: klineContainers.some((item) => item.width >= 300 && item.height >= 240),
      blockingErrorText,
      innerWidth: window.innerWidth,
      scrollX: window.scrollX,
      bodyScrollWidth: document.documentElement.scrollWidth,
      overflowers,
      canvasCount: canvases.length,
      canvases,
      klineContainers,
      textSample: text.replace(/\\s+/g, ' ').slice(0, 500),
    };
  })()`)
}

async function run() {
  const chromePath = findChrome()
  if (!chromePath) fail('Chrome executable not found. Set CHROME_PATH to run this smoke test.')

  const userDataDir = await mkdtemp(join(tmpdir(), 'qwen-detail-smoke-'))
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

    await setViewport(cdp, 1440, 900)
    await navigateDetail(cdp)
    await waitForExpression(
      cdp,
      'document.querySelectorAll("canvas").length > 0 || document.body.innerText.includes("K 线走势")',
      'desktop kline render',
      60000,
    )
    const desktop = await detailSnapshot(cdp)
    if (!desktop.hasCode || !desktop.hasName) fail('Detail page did not show local stock identity.', desktop)
    if (!desktop.hasLocalQuote) fail('Detail page did not show local quote/date information.', desktop)
    if (!desktop.hasKlineText || (!desktop.hasLargeCanvas && !desktop.hasKlineContainer)) {
      fail('Detail page did not render a non-empty K-line area.', desktop)
    }
    if (desktop.blockingErrorText) fail('Detail page showed a blocking load error.', desktop)

    await setViewport(cdp, 390, 844, true)
    await navigateDetail(cdp)
    const mobile = await detailSnapshot(cdp)
    if (!mobile.hasCode || !mobile.hasName) fail('Mobile detail page did not show local stock identity.', mobile)
    if (!mobile.hasKlineText || (!mobile.hasLargeCanvas && !mobile.hasKlineContainer)) {
      fail('Mobile detail page did not render a non-empty K-line area.', mobile)
    }
    if (mobile.blockingErrorText) fail('Mobile detail page showed a blocking load error.', mobile)
    if (mobile.overflowers.length || mobile.bodyScrollWidth > mobile.innerWidth + 2) {
      fail('Mobile detail layout has visible overflow.', mobile)
    }

    console.log(JSON.stringify({
      status: 'ok',
      baseUrl: BASE_URL,
      desktop: {
        href: desktop.href,
        canvasCount: desktop.canvasCount,
        hasLargeCanvas: desktop.hasLargeCanvas,
        hasKlineContainer: desktop.hasKlineContainer,
        blockingErrorText: desktop.blockingErrorText,
      },
      mobile: {
        innerWidth: mobile.innerWidth,
        scrollX: mobile.scrollX,
        bodyScrollWidth: mobile.bodyScrollWidth,
        overflowers: mobile.overflowers,
        canvasCount: mobile.canvasCount,
      },
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
