// 通用 SSE 客户端：fetch + ReadableStream + TextDecoder。
//
// 后端按 `data: <json>\n\n` 协议发，每帧 payload 必须含 `type` 字段；
// 收到 `type: 'done'` 或 `type: 'error'` 时本函数会优雅返回。
//
// 适用于 /qwen/analysis/{code}/stream、/screener/nl/stream 等所有 SSE 端点。

import { useAuthStore } from '../stores/auth'

/**
 * @param {string} url        后端路径，如 '/api/v1/qwen/analysis/600519.SH/stream'
 * @param {object} opts
 * @param {'GET'|'POST'} [opts.method='GET']
 * @param {object} [opts.body]   POST 时的 JSON 请求体
 * @param {(p:object)=>void} opts.onEvent  每帧 payload 回调
 * @param {AbortSignal} [opts.signal]
 */
export async function streamSSE(url, { method = 'GET', body, onEvent, signal } = {}) {
  // 兼容 main.js 之前用 localStorage 直存 token 的写法
  let token
  try { token = useAuthStore().token } catch { token = localStorage.getItem('token') }

  const headers = { Accept: 'text/event-stream' }
  if (token) headers.Authorization = `Bearer ${token}`
  if (method === 'POST') headers['Content-Type'] = 'application/json'

  const resp = await fetch(url, {
    method,
    headers,
    body: method === 'POST' && body != null ? JSON.stringify(body) : undefined,
    signal,
  })
  if (!resp.ok) {
    const txt = await resp.text().catch(() => '')
    throw new Error(`HTTP ${resp.status}: ${txt.slice(0, 240) || '请求失败'}`)
  }
  if (!resp.body) throw new Error('浏览器不支持流式 fetch')

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let idx
    while ((idx = buffer.indexOf('\n\n')) >= 0) {
      const raw = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      const line = raw.split('\n').find((l) => l.startsWith('data:'))
      if (!line) continue
      const json = line.slice(5).trim()
      if (!json) continue
      try {
        const payload = JSON.parse(json)
        onEvent(payload)
        if (payload.type === 'done' || payload.type === 'error') return
      } catch {
        /* 跳过畸形帧 */
      }
    }
  }
}
