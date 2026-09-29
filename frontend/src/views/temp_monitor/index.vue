<template>
  <section class="page" data-module="temp_monitor">
    <header class="page-head">
      <div>
        <h2>温控监测管理</h2>
        <p class="page-desc">按温度上下限建立多级超温规则，多规则同时命中时以业务优先级为准；超温结论回写报警待办，报警、看板与记录明细保持一致。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记温度记录</button>
        <button class="btn" type="button" @click="exportRows">导出温控监测清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div class="rules-panel">
      <div class="rules-head">
        <h3>多级超温规则</h3>
        <span class="interface-state" :class="interfaceState">{{ interfaceLabel }}</span>
      </div>
      <ul class="rules-list">
        <li v-for="rule in rules" :key="rule.name" class="rule-item">
          <span class="rule-priority">优先级 {{ rule.priority }}</span>
          <span class="rule-name">{{ rule.name }}</span>
          <span class="rule-desc">{{ rule.desc }}</span>
        </li>
      </ul>
      <div class="rules-actions">
        <button class="btn" type="button" @click="retryWriteBack">断点续传补写报警</button>
        <button class="btn" type="button" @click="toggleInterface">
          {{ interfaceState === 'normal' ? '中断接入接口' : '恢复接入接口' }}
        </button>
        <span class="checkpoint-info">断点：{{ checkpoint }} · 待回写：{{ pendingWriteBack }} 条</span>
      </div>
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
            <span v-if="column === '记录状态'" :class="['status-badge', statusClass(row[column])]">{{ row[column] ?? '—' }}</span>
            <span v-else-if="column === '回写状态'" :class="['write-badge', writeBackClass(row[column])]">{{ writeBackLabel(row[column]) }}</span>
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
          <td :colspan="columns.length + 1" class="empty-state">暂无温控监测数据，可先登记温度记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条温控监测记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      <span v-if="successMessage" class="success-text">{{ successMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/temp_monitor'
const columns = ["记录编号", "运单编号", "当前温度", "温度上限", "温度下限", "记录时间", "设备编号", "记录状态", "回写状态"]
const actions = ["标记预警", "确认超温", "数据补录"]
const filterFields = columns.slice(0, 3)

const RULE_DESCRIPTIONS: Record<string, string> = {
  "严重超温": "温度超出上限+3℃ 或 低于下限-3℃",
  "超温": "温度高于上限 或 低于下限",
  "接近临界": "温度距上限/下限 1℃ 以内",
  "正常": "温度在上下限范围内",
}

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const successMessage = ref('')
const filters = ref<Record<string, string>>({})
const rules = ref<{ name: string; priority: number; desc: string }[]>([])
const checkpoint = ref(0)
const pendingWriteBack = ref(0)
const interfaceState = ref<'normal' | 'interrupted'>('normal')

const interfaceLabel = computed(() =>
  interfaceState.value === 'normal' ? '接口正常' : '接口中断'
)

const stats = computed(() => {
  const normal = rows.value.filter((r) => r['记录状态'] === '正常').length
  const warning = rows.value.filter((r) => r['记录状态'] === '接近临界').length
  const overTemp = rows.value.filter((r) => r['记录状态'] === '超温' || r['记录状态'] === '严重超温').length
  return [
    { label: '正常运单', value: normal },
    { label: '预警运单', value: warning },
    { label: '超温运单', value: overTemp },
  ]
})

function statusClass(status: unknown): string {
  const s = String(status ?? '')
  if (s === '正常') return 'status-normal'
  if (s === '接近临界') return 'status-warning'
  if (s === '超温') return 'status-overtemp'
  if (s === '严重超温') return 'status-severe'
  if (s === '数据缺失') return 'status-missing'
  return ''
}

function writeBackClass(state: unknown): string {
  const s = String(state ?? '')
  if (s === 'done') return 'write-done'
  if (s === 'pending') return 'write-pending'
  return 'write-not-required'
}

function writeBackLabel(state: unknown): string {
  const s = String(state ?? '')
  if (s === 'done') return '已回写'
  if (s === 'pending') return '待回写'
  return '无需回写'
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '温度记录登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('温控监测动作未生效，请稍后重试')
    }
    successMessage.value = `已执行「${action}」，结论已重新判定并回写`
    await reload()
    await loadMeta()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '温控监测操作失败'
  }
}

async function retryWriteBack() {
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/retry`, { method: 'POST' })
    if (!response.ok) {
      throw new Error('断点续传失败，请稍后重试')
    }
    const payload = await response.json()
    successMessage.value = payload.message ?? '断点续传完成'
    await reload()
    await loadMeta()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '断点续传失败'
  }
}

async function toggleInterface() {
  errorMessage.value = ''
  successMessage.value = ''
  const next = interfaceState.value === 'normal' ? 'interrupted' : 'normal'
  try {
    const response = await request(`${ENDPOINT}/interface`, {
      method: 'POST',
      body: JSON.stringify({ values: { state: next } }),
    })
    if (!response.ok) {
      throw new Error('接口状态切换失败')
    }
    const payload = await response.json()
    successMessage.value = payload.message ?? '接口状态已更新'
    await loadMeta()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '接口状态切换失败'
  }
}

async function loadMeta() {
  try {
    const [rulesRes, checkpointRes] = await Promise.all([
      request(`${ENDPOINT}/rules`),
      request(`${ENDPOINT}/checkpoint`),
    ])
    if (rulesRes.ok) {
      const payload = await rulesRes.json()
      rules.value = (payload.rules ?? []).map((r: { name: string; priority: number }) => ({
        ...r,
        desc: RULE_DESCRIPTIONS[r.name] ?? '',
      }))
    }
    if (checkpointRes.ok) {
      const payload = await checkpointRes.json()
      checkpoint.value = payload.checkpoint ?? 0
      pendingWriteBack.value = payload.pending_write_back ?? 0
      interfaceState.value = payload.interface === 'interrupted' ? 'interrupted' : 'normal'
    }
  } catch {
    // 元数据加载失败不阻断列表展示
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('温度记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '温控监测列表读取失败'
  }
}

onMounted(async () => {
  await Promise.all([reload(), loadMeta()])
})
</script>

<style scoped>
.rules-panel {
  background: var(--panel-bg, #f7f8fa);
  border: 1px solid var(--border-color, #e5e7eb);
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
}

.rules-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.rules-head h3 {
  margin: 0;
  font-size: 15px;
}

.interface-state {
  font-size: 12px;
  padding: 2px 10px;
  border-radius: 12px;
}

.interface-state.normal {
  background: #e6f7ec;
  color: #1a7f37;
}

.interface-state.interrupted {
  background: #fde8e8;
  color: #c0392b;
}

.rules-list {
  list-style: none;
  margin: 0 0 12px;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 8px;
}

.rule-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.rule-priority {
  background: #eef2ff;
  color: #3b5bdb;
  padding: 1px 8px;
  border-radius: 4px;
  font-size: 12px;
  white-space: nowrap;
}

.rule-name {
  font-weight: 600;
}

.rule-desc {
  color: #6b7280;
  font-size: 12px;
}

.rules-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.checkpoint-info {
  font-size: 12px;
  color: #6b7280;
  margin-left: auto;
}

.status-badge,
.write-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 12px;
}

.status-normal { background: #e6f7ec; color: #1a7f37; }
.status-warning { background: #fff4e0; color: #b25e09; }
.status-overtemp { background: #fde8e8; color: #c0392b; }
.status-severe { background: #fde2e2; color: #9b1c1c; font-weight: 600; }
.status-missing { background: #f3f4f6; color: #6b7280; }

.write-done { background: #e6f7ec; color: #1a7f37; }
.write-pending { background: #fff4e0; color: #b25e09; }
.write-not-required { background: #f3f4f6; color: #6b7280; }

.success-text {
  color: #1a7f37;
}
</style>
