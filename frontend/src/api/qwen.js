import client from './client'
import { streamSSE } from './sse'

/** 基本面评分：数字为规则算法；reason 为千问解读（可缓存 7 天） */
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
