<!--
  全局错误边界。

  捕获什么：
    - 子组件 render / 生命周期 / async setup 抛出的异常（Vue onErrorCaptured）
    - window 级未处理的 promise rejection（unhandledrejection）

  捕获后做什么：
    - 切到 fallback 视图，展示"服务暂不可达"+ 重试按钮
    - 重试按钮强制 remount 子树（递增 epoch，作 v-if key）

  不捕获什么：
    - 同步事件处理器里 throw（这种 Vue 默认会冒泡到 window.onerror）
    - 已经 .catch 吞掉的 axios 错误（视图自己负责 toast）
-->
<script setup>
import { onErrorCaptured, onMounted, onUnmounted, ref } from 'vue'
import { A2 } from '../shared/theme.js'
import Icon from './Icon.vue'

const error = ref(null)
const epoch = ref(0)

onErrorCaptured((err) => {
  console.error('[ErrorBoundary]', err)
  error.value = err
  return false // 阻止继续向上冒泡
})

function onUnhandled(e) {
  // axios 错误通常是 { message, response, code }，挑一条人话出来
  const reason = e.reason || e
  console.error('[ErrorBoundary unhandledrejection]', reason)
  // 网络层错误吃掉，避免每次后端短暂抖动都白屏；仅在真的渲染挂掉时显示 fallback
  // 这里仍然 log，但不触发 error 状态——视图本身的 try/catch + toast 已经够了
}

onMounted(() => {
  window.addEventListener('unhandledrejection', onUnhandled)
})
onUnmounted(() => {
  window.removeEventListener('unhandledrejection', onUnhandled)
})

function retry() {
  error.value = null
  epoch.value++
}

function isNetworkError(err) {
  const msg = String(err?.message || err || '').toLowerCase()
  return msg.includes('network') || msg.includes('timeout') || err?.code === 'ERR_NETWORK'
}
</script>

<template>
  <div v-if="!error" :key="epoch">
    <slot />
  </div>
  <div v-else class="error-fallback">
    <div class="card">
      <div class="icon" :style="{ color: A2.up }">
        <Icon name="alert" :size="32" />
      </div>
      <h2 :style="{ color: A2.text }">
        {{ isNetworkError(error) ? '服务暂不可达' : '页面渲染出错了' }}
      </h2>
      <p :style="{ color: A2.textMuted }">
        {{ isNetworkError(error)
          ? '后端可能正在重启 / 网络中断，可以稍后重试。'
          : '刚刚出现一个未预期的错误，已记录到控制台。' }}
      </p>
      <pre :style="{ color: A2.textMuted, background: A2.surfaceAlt || '#f5f5f5', border: `1px solid ${A2.borderHair}` }">{{ String(error?.message || error) }}</pre>
      <div class="actions">
        <button class="btn-primary" :style="{ background: A2.qwen, color: '#fff' }" @click="retry">
          <Icon name="refresh" :size="14" /> 重试
        </button>
        <button class="btn-secondary" :style="{ color: A2.text, border: `1px solid ${A2.borderHair}` }" @click="$router?.push?.('/dashboard') || (location.href='/')">
          返回首页
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.error-fallback {
  min-height: 60vh;
  display: grid;
  place-items: center;
  padding: 40px 20px;
}
.card {
  max-width: 520px;
  text-align: center;
  display: flex;
  flex-direction: column;
  gap: 16px;
  align-items: center;
}
.icon { display: grid; place-items: center; }
h2 { margin: 0; font-size: 18px; font-weight: 600; }
p { margin: 0; font-size: 14px; line-height: 1.6; }
pre {
  width: 100%;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 12px;
  text-align: left;
  padding: 10px 12px;
  border-radius: 6px;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 160px;
  overflow: auto;
}
.actions { display: flex; gap: 12px; margin-top: 8px; }
.actions button {
  padding: 8px 18px;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: none;
}
.btn-secondary { background: transparent; }
</style>
