import client from './client'

export async function analyze(code) {
  const { data } = await client.get(`/qwen/analysis/${code}`)
  return data
}

/**
 * 流式拉取千问分析。
 * @param {string} code 股票代码
 * @param {(payload:{type:string, text?:string, snapshot?:object, message?:string}) => void} onEvent
 *   每个 SSE 事件都会触发；payload.type ∈ 'meta' | 'chunk' | 'done' | 'error'
 * @param {AbortSignal} [signal]
 * @returns {Promise<void>} 解析时表示流已正常结束
 */
export async function streamAnalyze(code, onEvent, signal) {
  const token = localStorage.getItem('token')
  const headers = { Accept: 'text/event-stream' }
  if (token) headers.Authorization = `Bearer ${token}`

  const resp = await fetch(`/api/v1/qwen/analysis/${code}/stream`, {
    method: 'GET',
    headers,
    signal,
  })
  if (!resp.ok) {
    const txt = await resp.text().catch(() => '')
    throw new Error(`HTTP ${resp.status}: ${txt.slice(0, 200) || '请求失败'}`)
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // SSE 事件以 \n\n 分隔；按双换行切，把最后一段不完整的留下次拼
    let idx
    while ((idx = buffer.indexOf('\n\n')) >= 0) {
      const raw = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      // 一个事件块里可能有多行 'data: ...'；目前后端单行
      const line = raw.split('\n').find((l) => l.startsWith('data:'))
      if (!line) continue
      const json = line.slice(5).trim()
      if (!json) continue
      try {
        const payload = JSON.parse(json)
        onEvent(payload)
        if (payload.type === 'done' || payload.type === 'error') return
      } catch {
        // 忽略畸形帧
      }
    }
  }
}
