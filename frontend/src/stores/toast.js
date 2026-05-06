// 全局轻量 Toast。用法：
//   import { toast } from '../stores/toast'
//   toast.success('已加入自选')
//   toast.error('请求失败', { duration: 5000 })

import { defineStore } from 'pinia'
import { ref } from 'vue'

let _seq = 0

export const useToastStore = defineStore('toast', () => {
  // items: { id, type: 'success'|'info'|'warning'|'error', message, duration }
  const items = ref([])

  function push(type, message, opts = {}) {
    const id = ++_seq
    const duration = opts.duration ?? (type === 'error' ? 5000 : 2500)
    items.value.push({ id, type, message })
    if (duration > 0) setTimeout(() => dismiss(id), duration)
    return id
  }

  function dismiss(id) {
    items.value = items.value.filter((t) => t.id !== id)
  }

  return { items, push, dismiss }
})

// 在组件之外也能调用：先访问已挂载的 store 实例
let _store = null
function _ensure() {
  if (!_store) _store = useToastStore()
  return _store
}

export const toast = {
  success: (msg, opts) => _ensure().push('success', msg, opts),
  info:    (msg, opts) => _ensure().push('info',    msg, opts),
  warning: (msg, opts) => _ensure().push('warning', msg, opts),
  error:   (msg, opts) => _ensure().push('error',   msg, opts),
}
