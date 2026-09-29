<template>
  <section class="page" data-module="alert">
    <header class="page-head">
      <div>
        <h2>报警管理管理</h2>
        <p class="page-desc">维护报警记录，围绕报警编号、报警类型、关联设备、报警阈值做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="exportRows">导出报警管理清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in statCards" :key="item.label" class="stat-card">
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
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
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
const columns = ["报警编号", "报警类型", "关联设备", "报警阈值", "触发值", "触发时间", "处置措施", "来源记录编号", "报警状态"]
const actions = ["确认报警", "开始处理", "消除报警"]
const statuses = ["未处理", "已确认", "处理中", "已消除"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

// 统计直接来自当前列表（size 放大到 200 拉全量），与待办明细同源。
const statCards = computed(() => {
  const count = (status: string) => rows.value.filter((row) => row.status === status).length
  const tempOpen = rows.value.filter((row) => row['来源记录编号'] && row.status !== '已消除').length
  return [
    { label: '未处理报警', value: count('未处理') },
    { label: '处理中报警', value: count('已确认') + count('处理中') },
    { label: '超温待办', value: tempOpen },
    { label: '今日消除', value: count('已消除') },
  ]
})

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '报警管理动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '报警管理操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams({ ...(filters.value as Record<string, string>), size: '200' }).toString()
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
