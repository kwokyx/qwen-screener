import client from './client'
import { streamSSE } from './sse'

/** 千问基本面评分（后端缓存，同一快照 7 天内不重复调 API） */
export async function fetchScore(code, refresh = false) {
  const { data } = await client.get(`/qwen/score/${code}`, {
    params: refresh ? { refresh: true } : {},
  })
  return data
}

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
