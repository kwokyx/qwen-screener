#!/usr/bin/env node
import { existsSync } from 'node:fs'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'

const BASE_URL = (process.env.SMOKE_BASE_URL || 'http://127.0.0.1:8080').replace(/\/$/, '')
const USER_MENU_TRIGGER = `document.querySelector('.user-chip') || [...document.querySelectorAll('.n-avatar')]
  .find((el) => {
    const title = el.getAttribute('title') || '';
    return title && title !== '点击登录' && title !== '通知';
  })`
const LOGIN_TRIGGER = `document.querySelector('.auth-link') || [...document.querySelectorAll('.n-avatar')]
  .find((el) => (el.getAttribute('title') || '') === '点击登录')`

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
  let snapshot = null
  try {
    snapshot = await evaluate(cdp, `(() => ({
      href: location.href,
      token: Boolean(localStorage.getItem('token')),
      user: localStorage.getItem('user'),
      hasUserChip: Boolean(document.querySelector('.user-chip')),
      avatarTitles: [...document.querySelectorAll('.n-avatar')].map((el) => el.getAttribute('title') || ''),
      text: document.body.innerText.replace(/\\s+/g, ' ').slice(0, 500),
    }))()`)
  } catch {
    snapshot = lastError
  }
  fail(`Timed out waiting for ${label}.`, snapshot)
}

async function setViewport(cdp, width, height, mobile = false) {
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width,
    height,
    mobile,
    deviceScaleFactor: mobile ? 3 : 1,
  })
}

async function navigateLogin(cdp, query = '') {
  await cdp.send('Page.navigate', { url: `${BASE_URL}/login${query}` })
  await waitForExpression(cdp, 'location.pathname === "/login" && document.querySelector(".login-card form")', 'login page load')
  await waitForExpression(cdp, 'document.querySelector(".captcha-image img")?.src?.startsWith("data:image/svg+xml;base64,")', 'captcha image')
}

async function clickByText(cdp, text, { selector = 'button', last = false } = {}) {
  const clicked = await evaluate(cdp, `(() => {
    const nodes = [...document.querySelectorAll(${JSON.stringify(selector)})]
      .filter((el) => (el.innerText || el.textContent || '').includes(${JSON.stringify(text)}));
    const el = nodes[${last ? 'nodes.length - 1' : '0'}];
    if (!el) return false;
    el.click();
    return true;
  })()`)
  if (!clicked) fail(`Could not click ${text}.`)
}

async function clickDropdownOption(cdp, text) {
  const clicked = await evaluate(cdp, `(() => {
    const option = [...document.querySelectorAll('.n-dropdown-option')]
      .find((el) => (el.innerText || el.textContent || '').includes(${JSON.stringify(text)}));
    if (!option) return false;
    const target = option.querySelector('.n-dropdown-option-body') || option;
    for (const type of ['mouseenter', 'mousedown', 'mouseup', 'click']) {
      target.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
    }
    return true;
  })()`)
  if (!clicked) fail(`Could not click dropdown option ${text}.`)
}

async function clickUserMenu(cdp) {
  const clicked = await evaluate(cdp, `(() => {
    const el = ${USER_MENU_TRIGGER};
    if (!el) return false;
    el.click();
    return true;
  })()`)
  if (!clicked) fail('Could not click logged-in user menu.')
}

async function clickLoginEntry(cdp) {
  const clicked = await evaluate(cdp, `(() => {
    const el = ${LOGIN_TRIGGER};
    if (!el) return false;
    el.click();
    return true;
  })()`)
  if (!clicked) fail('Could not click login entry.')
}

async function captchaCode(cdp) {
  const code = await evaluate(cdp, `(() => {
    const src = document.querySelector('.captcha-image img')?.src || '';
    const encoded = src.split(',')[1] || '';
    const svg = atob(encoded);
    return [...svg.matchAll(/<text[^>]*>([^<]+)<\\/text>/g)].map((item) => item[1]).join('');
  })()`)
  if (!code || code.length < 4) fail('Could not parse captcha from rendered SVG image.', { code })
  return code
}

async function captchaSrc(cdp) {
  return evaluate(cdp, `document.querySelector('.captcha-image img')?.src || ''`)
}

async function fillAuthForm(cdp, { username, password, email = '', captcha = '' }) {
  await evaluate(cdp, `(() => {
    const inputs = [...document.querySelectorAll('.login-card form input')];
    const setValue = (el, value) => {
      el.value = value;
      el.dispatchEvent(new Event('input', { bubbles: true }));
    };
    setValue(inputs[0], ${JSON.stringify(username)});
    setValue(inputs[1], ${JSON.stringify(password)});
    if (inputs.length === 4) {
      setValue(inputs[2], ${JSON.stringify(email)});
      setValue(inputs[3], ${JSON.stringify(captcha)});
    } else {
      setValue(inputs[2], ${JSON.stringify(captcha)});
    }
    return true;
  })()`)
}

async function loginSnapshot(cdp) {
  return evaluate(cdp, `(() => {
    const text = document.body.innerText;
    const captcha = document.querySelector('.captcha-image img');
    const overflowers = [...document.querySelectorAll('.login-grid, .login-card, .captcha-row, input, button')]
      .map((el) => {
        const rect = el.getBoundingClientRect();
        return {
          text: (el.innerText || el.textContent || el.placeholder || '').replace(/\\s+/g, ' ').trim().slice(0, 80),
          left: Math.round(rect.left),
          right: Math.round(rect.right),
          width: Math.round(rect.width),
        };
      })
      .filter((item) => item.left < -2 || item.right > window.innerWidth + 2);
    return {
      href: location.href,
      hasCaptcha: Boolean(captcha?.src?.startsWith('data:image/svg+xml;base64,')),
      modeText: [...document.querySelectorAll('.login-card button')].map((el) => el.textContent.trim()).join('|'),
      hasEmptyCaptchaError: text.includes('请输入图形验证码'),
      hasWrongCaptchaError: text.includes('验证码错误或已过期'),
      hasRegisterNotice: text.includes('注册成功，请输入验证码登录'),
      overflowers,
    };
  })()`)
}

async function run() {
  const chromePath = findChrome()
  if (!chromePath) fail('Chrome executable not found. Set CHROME_PATH to run this smoke test.')

  const username = process.env.SMOKE_USERNAME || `auth_smoke_${Date.now().toString(36)}`
  const password = process.env.SMOKE_PASSWORD || 'auth_smoke_123456'
  const userDataDir = await mkdtemp(join(tmpdir(), 'qwen-auth-smoke-'))
  const stderrLines = []
  const debugPort = String(13222 + Math.floor(Math.random() * 1000))
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
    await navigateLogin(cdp)

    const initial = await loginSnapshot(cdp)
    if (!initial.hasCaptcha) fail('Login captcha did not render.', initial)
    if (initial.overflowers.length) fail('Desktop login layout has visible overflow.', initial)

    const beforeRefresh = await captchaSrc(cdp)
    await clickByText(cdp, '', { selector: '.captcha-image' })
    await waitForExpression(
      cdp,
      `${JSON.stringify(beforeRefresh)} !== (document.querySelector('.captcha-image img')?.src || '')`,
      'captcha refresh',
    )

    await fillAuthForm(cdp, { username, password, captcha: '' })
    await clickByText(cdp, '登 录', { selector: 'button' })
    await waitForExpression(cdp, 'document.body.innerText.includes("请输入图形验证码")', 'empty captcha validation')

    await fillAuthForm(cdp, { username, password, captcha: 'WRNG' })
    await clickByText(cdp, '登 录', { selector: 'button' })
    await waitForExpression(cdp, 'document.body.innerText.includes("验证码错误或已过期")', 'wrong captcha validation')

    const beforeRegisterMode = await captchaSrc(cdp)
    await clickByText(cdp, '注册', { selector: '.login-card > div:first-child button', last: true })
    await waitForExpression(cdp, 'document.body.innerText.includes("邮箱（选填）")', 'register mode')
    await waitForExpression(
      cdp,
      `${JSON.stringify(beforeRegisterMode)} !== (document.querySelector('.captcha-image img')?.src || '')`,
      'register mode captcha refresh',
    )
    await fillAuthForm(cdp, {
      username,
      password,
      email: `${username}@example.com`,
      captcha: await captchaCode(cdp),
    })
    await clickByText(cdp, '注册账号', { selector: 'button' })
    await waitForExpression(cdp, 'document.body.innerText.includes("注册成功，请输入验证码登录")', 'register success notice')
    await waitForExpression(cdp, 'document.body.innerText.includes("登 录") && !document.body.innerText.includes("邮箱（选填）")', 'back to login mode')

    await fillAuthForm(cdp, { username, password, captcha: await captchaCode(cdp) })
    await clickByText(cdp, '登 录', { selector: 'button' })
    await waitForExpression(cdp, 'location.pathname === "/dashboard"', 'login redirects to dashboard', 30000)
    await waitForExpression(cdp, `Boolean(${USER_MENU_TRIGGER})`, 'logged-in user menu')

    await clickUserMenu(cdp)
    await waitForExpression(cdp, 'document.body.innerText.includes("退出登录")', 'logout dropdown')
    await clickDropdownOption(cdp, '退出登录')
    await waitForExpression(cdp, 'location.pathname === "/dashboard" && !localStorage.getItem("token")', 'logged out dashboard')
    await clickLoginEntry(cdp)
    await navigateLogin(cdp)
    await fillAuthForm(cdp, { username, password, captcha: await captchaCode(cdp) })
    await clickByText(cdp, '登 录', { selector: 'button' })
    await waitForExpression(cdp, `location.pathname === "/dashboard" && Boolean(${USER_MENU_TRIGGER})`, 'relogin works', 30000)

    const finalSnapshot = await loginSnapshot(cdp)
    console.log(JSON.stringify({
      status: 'ok',
      baseUrl: BASE_URL,
      username,
      checks: {
        captchaRendered: initial.hasCaptcha,
        captchaRefresh: true,
        emptyCaptchaValidation: true,
        wrongCaptchaValidation: true,
        registerSuccess: true,
        loginSuccess: true,
        logoutAndRelogin: true,
        desktopOverflowers: initial.overflowers.length,
      },
      finalPath: finalSnapshot.href,
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
  console.error(err.stack || err.message)
  process.exit(1)
})
