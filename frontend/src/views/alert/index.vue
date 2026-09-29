<template>
  <section class="page" data-module="alert">
    <header class="page-head">
      <div>
        <h2>报警管理管理</h2>
        <p class="page-desc">维护报警记录，温度超温结论由温控监测自动回写，报警处置后与温控看板、记录明细保持一致。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记报警记录</button>
        <button class="btn" type="button" @click="exportRows">导出报警管理清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <span v-if="column === '超温等级' && row[column]" :class="['level-badge', levelClass(row[column])]">{{ row[column] }}</span>
            <span v-else-if="column === '报警状态'" :class="['status-badge', statusClass(row[column])]">{{ row[column] ?? '—' }}</span>
            <span v-else>{{ row[column] ?? '—' }}</span>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无报警管理数据，可先登记报警记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条报警管理记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/alert'
const columns = ["报警编号", "报警类型", "关联设备", "报警阈值", "触发值", "超温等级", "关联温度记录", "触发时间", "处置措施", "报警状态"]
const actions = ["确认报警", "开始处理", "消除报警"]
const filterFields = columns.slice(0, 3)

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})

const stats = computed(() => {
  const pending = rows.value.filter((r) => r['报警状态'] === '未处理').length
  const processing = rows.value.filter((r) => r['报警状态'] === '处理中').length
  const eliminated = rows.value.filter((r) => r['报警状态'] === '已消除').length
  return [
    { label: '未处理报警', value: pending },
    { label: '处理中报警', value: processing },
    { label: '今日消除', value: eliminated },
  ]
})

function levelClass(level: unknown): string {
  const s = String(level ?? '')
  if (s === '严重超温') return 'level-severe'
  if (s === '超温') return 'level-overtemp'
  return ''
}

function statusClass(status: unknown): string {
  const s = String(status ?? '')
  if (s === '未处理') return 'status-pending'
  if (s === '已确认') return 'status-confirmed'
  if (s === '处理中') return 'status-processing'
  if (s === '已消除') return 'status-eliminated'
  return ''
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '报警记录登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('报警管理动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '报警管理操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('报警记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '报警管理列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.level-badge,
.status-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 12px;
}

.level-severe { background: #fde2e2; color: #9b1c1c; font-weight: 600; }
.level-overtemp { background: #fde8e8; color: #c0392b; }

.status-pending { background: #fde8e8; color: #c0392b; }
.status-confirmed { background: #fff4e0; color: #b25e09; }
.status-processing { background: #eef2ff; color: #3b5bdb; }
.status-eliminated { background: #e6f7ec; color: #1a7f37; }
</style>
