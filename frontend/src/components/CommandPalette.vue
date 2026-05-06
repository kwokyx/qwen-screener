<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import * as stockApi from '../api/stock'
import { A2 } from '../shared/theme.js'
import Icon from './Icon.vue'

const props = defineProps({ open: Boolean })
const emit = defineEmits(['close'])

const router = useRouter()
const query = ref('')
const items = ref([])
const cursor = ref(0)
const loading = ref(false)
const inputRef = ref(null)

let abort = null
let debounce = null

const recents = computed(() => {
  try {
    return JSON.parse(localStorage.getItem('qwen.recents.v1') || '[]')
  } catch { return [] }
})

const display = computed(() => (query.value.trim() ? items.value : recents.value))

watch(() => props.open, async (v) => {
  if (v) {
    query.value = ''
    items.value = []
    cursor.value = 0
    await nextTick()
    inputRef.value?.focus()
  }
})

watch(query, (q) => {
  cursor.value = 0
  if (debounce) clearTimeout(debounce)
  if (!q.trim()) {
    items.value = []
    return
  }
  debounce = setTimeout(async () => {
    loading.value = true
    if (abort) abort.abort?.()
    abort = new AbortController()
    try {
      const data = await stockApi.search(q, 12)
      items.value = Array.isArray(data) ? data : (data.items || [])
    } catch {
      // 后端 down → 不阻塞，仅清空
      items.value = []
    } finally {
      loading.value = false
    }
  }, 180)
})

function pushRecent(s) {
  try {
    const cur = JSON.parse(localStorage.getItem('qwen.recents.v1') || '[]')
    const filtered = cur.filter((x) => x.code !== s.code)
    filtered.unshift({ code: s.code, name: s.name, sector: s.industry || s.sector })
    localStorage.setItem('qwen.recents.v1', JSON.stringify(filtered.slice(0, 8)))
  } catch { /* ignore */ }
}

function pick(s) {
  if (!s) return
  pushRecent(s)
  router.push(`/detail/${s.code}`)
  emit('close')
}

function onKey(e) {
  if (!props.open) return
  if (e.key === 'Escape') { e.preventDefault(); emit('close') }
  else if (e.key === 'ArrowDown') {
    e.preventDefault()
    cursor.value = Math.min(display.value.length - 1, cursor.value + 1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    cursor.value = Math.max(0, cursor.value - 1)
  } else if (e.key === 'Enter') {
    e.preventDefault()
    pick(display.value[cursor.value])
  }
}

window.addEventListener('keydown', onKey)
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <Transition name="page-fade">
    <div v-if="open" class="cmdk-backdrop" @click.self="$emit('close')">
      <div class="cmdk-shell" :style="{ background: A2.surface, boxShadow: A2.shadowLg }">
        <div class="cmdk-input-row">
          <Icon name="search" :size="16" :color="A2.textMuted" />
          <input ref="inputRef" v-model="query"
                 placeholder="搜索股票名称 / 代码 / 拼音首字母…"
                 :style="{ fontSize: '15px', flex: 1, border: 'none', outline: 'none', background: 'transparent', fontFamily: 'inherit', color: A2.text }" />
          <span class="kbd">ESC</span>
        </div>

        <div class="cmdk-body">
          <div v-if="loading" :style="{ padding: '24px', textAlign: 'center', color: A2.textMuted, fontSize: '12px' }">搜索中…</div>

          <div v-else-if="!display.length && !query" :style="{ padding: '32px', textAlign: 'center', color: A2.textMuted, fontSize: '12px' }">
            <div :style="{ fontSize: '20px', marginBottom: '6px' }">🔍</div>
            输入股票名 / 代码开始搜索
            <div :style="{ fontSize: '10.5px', color: A2.textDim, marginTop: '6px' }">↑↓ 选择 · Enter 进入详情 · Esc 关闭</div>
          </div>

          <div v-else-if="!display.length" :style="{ padding: '32px', textAlign: 'center', color: A2.textMuted, fontSize: '12px' }">
            未找到匹配的股票
            <div :style="{ fontSize: '10.5px', color: A2.textDim, marginTop: '6px' }">提示：搜索接口需要后端 / 数据已同步</div>
          </div>

          <template v-else>
            <div v-if="!query.trim()" :style="{ padding: '8px 14px 4px', fontSize: '10px', color: A2.textDim, fontWeight: 700, letterSpacing: '1.2px', textTransform: 'uppercase' }">最近访问</div>
            <div v-for="(s, i) in display" :key="s.code"
                 class="cmdk-item"
                 :class="{ active: i === cursor }"
                 @mouseenter="cursor = i"
                 @click="pick(s)">
              <div :style="{ fontWeight: 600, fontSize: '13px', color: A2.text }">{{ s.name || s.code }}</div>
              <div :style="{ fontFamily: 'IBM Plex Mono, monospace', fontSize: '11px', color: A2.textMuted }">{{ s.code }}</div>
              <span v-if="s.industry || s.sector" :style="{ marginLeft: '8px', fontSize: '10px', padding: '2px 7px', background: A2.bgDeep, color: A2.textSub, borderRadius: '4px' }">{{ s.industry || s.sector }}</span>
              <div style="flex:1" />
              <Icon name="arrowRight" :size="12" :color="A2.textDim" />
            </div>
          </template>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.cmdk-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(14,14,12,0.32);
  backdrop-filter: blur(2px);
  z-index: 100;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 14vh;
}
.cmdk-shell {
  width: min(560px, 92vw);
  border-radius: 12px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  max-height: 60vh;
}
.cmdk-input-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  border-bottom: 1px solid rgba(14,14,12,0.06);
}
.kbd {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  padding: 2px 6px;
  background: rgba(14,14,12,0.06);
  border-radius: 4px;
  color: #7A776F;
}
.cmdk-body {
  overflow: auto;
  flex: 1;
}
.cmdk-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 16px;
  cursor: pointer;
  border-left: 2px solid transparent;
}
.cmdk-item.active {
  background: #EAF0FE;
  border-left-color: #2456D8;
}
</style>
