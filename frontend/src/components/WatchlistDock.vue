<script setup>
// 浮动在右下的"自选股快捷栏"，常驻所有页面。
// 收起态是一个小标签；展开后显示自选列表，点击直达详情。

import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useWatchlistStore } from '../stores/watchlist'
import { A2 } from '../shared/theme.js'
import { fetchWatchSnapshots } from '../shared/stockSnapshot.js'
import Icon from './Icon.vue'

const wl = useWatchlistStore()
const router = useRouter()
const route = useRoute()

const open = ref(false)
const snapshots = ref({})

async function refreshDetails() {
  snapshots.value = {
    ...snapshots.value,
    ...(await fetchWatchSnapshots(wl.items)),
  }
}

function toggle() {
  open.value = !open.value
  if (open.value) refreshDetails()
}

function close() {
  open.value = false
}

function goto(code) {
  close()
  router.push(`/detail/${code}`)
}

function onClickOutside(e) {
  if (!open.value) return
  const dock = document.querySelector('.watchdock')
  if (dock && !dock.contains(e.target)) close()
}

// 当前页是 chat / detail 等页面，dock 不要遮挡。在 detail 页默认收起
onMounted(() => {
  if (route.name === 'detail') open.value = false
})

// 全局快捷键 W 切换
function onKey(e) {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable) return
  if (e.key === 'w' || e.key === 'W') toggle()
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
onMounted(() => document.addEventListener('mousedown', onClickOutside))
onBeforeUnmount(() => document.removeEventListener('mousedown', onClickOutside))

watch(() => route.fullPath, () => { if (open.value) close() })

watch(() => wl.items.map((item) => item.code).join('|'), () => {
  if (open.value) refreshDetails()
})

const items = computed(() => wl.items)
const dockItems = computed(() => items.value.map((item) => {
  const snapshot = snapshots.value[item.code] || {}
  const price = snapshot.close ?? item.refPrice ?? null
  return {
    ...item,
    displayName: snapshot.name || item.name || item.code,
    displaySector: snapshot.industry || item.sector || '',
    displayPrice: price,
    priceSource: snapshot.close != null ? snapshot.source_label : (item.refPrice != null ? '加入价' : ''),
    priceTitle: snapshot.close != null ? snapshot.source_title : '加入自选时保存的基准价',
  }
}))
</script>

<template>
  <Teleport to="body">
    <div class="watchdock" :class="{ open }">
      <!-- 收起态：小标签 -->
      <button v-if="!open" class="watchdock-tab" @click="toggle" title="自选股 (W)">
        <Icon name="starF" :size="13" color="#F59E0B" />
        <span>自选 {{ items.length }}</span>
      </button>

      <!-- 展开态：面板 -->
      <div v-else class="watchdock-panel" :style="{ background: A2.surface, boxShadow: A2.shadowLg, border: `1px solid ${A2.borderHair}` }">
        <div class="watchdock-head">
          <span :style="{ display: 'flex', alignItems: 'center', gap: '6px' }">
            <Icon name="starF" :size="13" color="#F59E0B" />
            <span :style="{ fontSize: '12px', fontWeight: 700 }">我的自选</span>
            <span :style="{ fontSize: '10px', color: A2.textMuted, fontFamily: 'IBM Plex Mono, monospace' }">{{ items.length }}</span>
          </span>
          <button @click="close" class="watchdock-close" title="收起 (W)">
            <Icon name="x" :size="12" />
          </button>
        </div>

        <div v-if="!items.length" :style="{ padding: '24px 16px', textAlign: 'center', color: A2.textMuted, fontSize: '11.5px' }">
          <div :style="{ display: 'inline-grid', placeItems: 'center', width: '34px', height: '34px', borderRadius: '50%', background: A2.bgDeep, color: A2.textDim, marginBottom: '8px' }">
            <Icon name="star" :size="15" />
          </div>
          <div :style="{ color: A2.text, fontWeight: 600, marginBottom: '3px' }">还没有自选股</div>
          <div :style="{ fontSize: '10.5px', color: A2.textDim, lineHeight: 1.5 }">在任意股票旁点 ★ 即可加入<br/>或按 ⌘K 搜索</div>
        </div>
        <div v-else class="watchdock-list">
          <div v-for="w in dockItems" :key="w.code"
               class="watchdock-item"
               @click="goto(w.code)">
            <div :style="{ flex: 1, minWidth: 0 }">
              <div :style="{ fontSize: '12px', fontWeight: 600, color: A2.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }">{{ w.displayName }}</div>
              <div :style="{ fontSize: '9.5px', color: A2.textDim, fontFamily: 'IBM Plex Mono, monospace', marginTop: '1px' }">
                {{ w.code }}<span v-if="w.displaySector"> · {{ w.displaySector }}</span>
              </div>
            </div>
            <div :style="{ textAlign: 'right', flexShrink: 0 }">
              <div :style="{ fontSize: '12px', fontWeight: 700, fontFamily: 'IBM Plex Mono, monospace', color: A2.text }">
                {{ w.displayPrice == null ? '—' : w.displayPrice.toFixed(2) }}
              </div>
              <div v-if="w.priceSource || (w.alerts && w.alerts.length)"
                   :style="{ display: 'inline-flex', alignItems: 'center', justifyContent: 'flex-end', gap: '5px', fontSize: '9.5px', color: A2.textDim, fontFamily: 'IBM Plex Mono, monospace', marginTop: '1px' }">
                <span v-if="w.priceSource" :title="w.priceTitle">{{ w.priceSource }}</span>
                <span v-if="w.alerts && w.alerts.length" :style="{ color: A2.qwen, display: 'inline-flex', alignItems: 'center', gap: '3px' }">
                  <Icon name="bell" :size="9" /> {{ w.alerts.length }}
                </span>
              </div>
            </div>
          </div>
        </div>
        <div v-if="items.length" class="watchdock-foot">
          <button @click="router.push('/portfolio')" class="watchdock-foot-btn">
            管理自选 →
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.watchdock {
  position: fixed;
  right: 16px;
  bottom: 16px;
  z-index: 80;
  font-family: 'IBM Plex Sans', 'Noto Sans SC', sans-serif;
}
.watchdock-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  background: #FFFFFF;
  border: 1px solid rgba(14,14,12,0.10);
  border-radius: 6px;
  box-shadow: 0 3px 10px rgba(14,14,12,0.08);
  font-size: 12px;
  font-weight: 600;
  color: #111110;
  cursor: pointer;
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}
.watchdock-tab:hover {
  transform: translateY(-1px);
  box-shadow: 0 5px 16px rgba(14,14,12,0.12);
}
.watchdock-panel {
  width: 280px;
  max-height: 60vh;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.watchdock-head {
  padding: 10px 12px;
  border-bottom: 1px solid rgba(14,14,12,0.06);
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.watchdock-close {
  background: transparent;
  border: none;
  color: #7A776F;
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 4px;
}
.watchdock-close:hover { background: rgba(14,14,12,0.06); color: #111110; }
.watchdock-list {
  overflow-y: auto;
  flex: 1;
  padding: 4px 0;
}
.watchdock-item {
  display: flex;
  gap: 10px;
  padding: 8px 12px;
  cursor: pointer;
  transition: background 0.12s ease;
  align-items: center;
}
.watchdock-item:hover { background: rgba(36, 86, 216, 0.05); }
.watchdock-foot {
  border-top: 1px solid rgba(14,14,12,0.06);
  padding: 6px 8px;
  background: #FBFBF9;
}
.watchdock-foot-btn {
  width: 100%;
  background: transparent;
  border: none;
  padding: 6px;
  font-size: 11px;
  color: #2456D8;
  cursor: pointer;
  font-weight: 600;
  border-radius: 4px;
}
.watchdock-foot-btn:hover { background: rgba(36, 86, 216, 0.08); }
</style>
