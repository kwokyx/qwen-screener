import client from './client'
import { streamSSE } from './sse'

export async function analyze(code) {
  const { data } = await client.get(`/qwen/analysis/${code}`)
  return data
}

/**
 * 流式拉取千问分析。事件 type ∈ 'meta' | 'chunk' | 'done' | 'error'
 */
export function streamAnalyze(code, onEvent, signal) {
  return streamSSE(`/api/v1/qwen/analysis/${code}/stream`, { onEvent, signal })
}
