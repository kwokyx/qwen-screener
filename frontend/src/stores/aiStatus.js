// 全局 AI 上游可用性状态。每 2 分钟主动 ping 一次后端 /health/ai。
// 前端 AI 触发处（Detail 问千问 / Chat 发送）直接读 isUp 决定按钮是否灰。

import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '../api/client'

export const useAiStatusStore = defineStore('aiStatus', () => {
  const isUp = ref(true)        // 默认乐观；首次探之前不要禁用按钮
  const reason = ref('')
  const latencyMs = ref(null)
  const configured = ref(false)
  const backend = ref('')
  const model = ref('')
  const mode = ref('')
  const fallback = ref(false)
  const pending = ref(false)
  const stale = ref(false)
  const lastChecked = ref(0)
  let timer = null
  let retryTimer = null

  function clearRetry() {
    if (retryTimer) clearTimeout(retryTimer)
    retryTimer = null
  }

  function scheduleRetry() {
    if (retryTimer) return
    retryTimer = setTimeout(() => {
      retryTimer = null
      check()
    }, 10_000)
  }

  async function check() {
    try {
      const { data } = await client.get('/health/ai')
      isUp.value = !!data.ok
      reason.value = data.reason || ''
      latencyMs.value = data.latency_ms
      configured.value = !!data.configured
      backend.value = data.backend || ''
      model.value = data.model || ''
      mode.value = data.mode || ''
      fallback.value = !!data.fallback
      pending.value = !!data.pending
      stale.value = !!data.stale
    } catch {
      isUp.value = false
      reason.value = '后端无响应'
      latencyMs.value = null
      configured.value = false
      backend.value = ''
      model.value = ''
      mode.value = 'local_rules'
      fallback.value = true
      pending.value = false
      stale.value = false
    } finally {
      lastChecked.value = Date.now()
      if (isUp.value) clearRetry()
      else scheduleRetry()
    }
  }

  function startAutoProbe() {
    if (timer) return
    check()
    timer = setInterval(check, 120_000)
  }

  function stopAutoProbe() {
    if (timer) { clearInterval(timer); timer = null }
    clearRetry()
  }

  // 每次发起 AI 调用前/后都可以手动让前端立刻重测
  async function recheck() { await check() }

  return {
    isUp, reason, latencyMs, configured, backend, model, mode, fallback, pending, stale, lastChecked,
    check, recheck, startAutoProbe, stopAutoProbe,
  }
})
