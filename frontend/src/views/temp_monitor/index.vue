<template>
  <section class="page" data-module="temp_monitor">
    <header class="page-head">
      <div>
        <h2>温控监测管理</h2>
        <p class="page-desc">
          温度记录接入后按上下限执行多级超温规则，多规则命中时以业务优先级为准；
          超温结论自动回写报警待办，看板、记录明细与报警待办保持一致。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" :disabled="busy" @click="ingestDemo(false)">接入演示温度批次</button>
        <button class="btn" type="button" :disabled="busy" @click="ingestDemo(true)">模拟接口中断</button>
        <button class="btn ghost" type="button" :disabled="busy" @click="ingestDemo(false)">从断点继续</button>
        <button class="btn" type="button" @click="exportRows">导出温控监测清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in statCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <section class="rule-panel">
      <h3>多级超温规则（按业务优先级生效）</h3>
      <div class="rule-chips">
        <span v-for="rule in rules" :key="rule.code" class="rule-chip" :class="{ alarm: rule.alarm }">
          <em>P{{ rule.priority }}</em>{{ rule.name }}
          <small>{{ ruleText(rule) }}{{ rule.alarm ? ' · 回写报警' : ' · 仅预警' }}</small>
        </span>
      </div>
    </section>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>记录编号/运单编号</span>
        <input v-model="keyword" placeholder="按记录编号或运单编号检索" />
      </label>
      <label class="filter-item">
        <span>记录状态</span>
        <select v-model="statusFilter">
          <option value="">全部</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
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
            <button class="link" type="button" @click="runAction('标记预警', row)">标记预警</button>
            <button class="link" type="button" @click="runAction('确认超温', row)">确认超温</button>
            <button class="link" type="button" @click="supplement(row)">数据补录</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无温控监测数据，可先接入温度记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条温控监测记录 ｜ 接入断点：流 default，已处理到序号 {{ checkpoint.seq }}（{{ checkpoint.processed }} 条）</span>
      <span v-if="infoMessage" class="info-text">{{ infoMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type Rule = {
  code: string
  name: string
  status: string
  direction: string
  min_delta: number | null
  max_delta: number | null
  priority: number
  alarm: boolean
}
type Dashboard = Record<string, number> & { rules: Rule[] }

const ENDPOINT = '/api/temp_monitor'
const columns = [
  '记录编号', '运单编号', '当前温度', '温度上限', '温度下限', '记录时间', '设备编号',
  '记录状态', '命中规则', '同时命中', '超温方向', '超温幅度', '判定依据', '关联报警',
]
const statuses = ['正常', '接近临界', '超温', '数据缺失']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const infoMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const busy = ref(false)
const dashboard = ref<Dashboard | null>(null)
const checkpoint = ref({ seq: 0, processed: 0 })

// 演示批次：覆盖正常、临界限、超限、一级/二级/三级超温（后两级同时命中多条规则）、上下限缺失
const DEMO_BATCH = [
  { seq: 1, 记录编号: 'TEMP-D01', 运单编号: 'SHIP-D01', 当前温度: '4.0', 温度上限: '8', 温度下限: '0', 记录时间: '2026-09-29 10:00', 设备编号: 'RF-301' },
  { seq: 2, 记录编号: 'TEMP-D02', 运单编号: 'SHIP-D02', 当前温度: '7.2', 温度上限: '8', 温度下限: '0', 记录时间: '2026-09-29 10:05', 设备编号: 'RF-302' },
  { seq: 3, 记录编号: 'TEMP-D03', 运单编号: 'SHIP-D03', 当前温度: '9.3', 温度上限: '8', 温度下限: '0', 记录时间: '2026-09-29 10:10', 设备编号: 'RF-303' },
  { seq: 4, 记录编号: 'TEMP-D04', 运单编号: 'SHIP-D04', 当前温度: '10.8', 温度上限: '8', 温度下限: '0', 记录时间: '2026-09-29 10:15', 设备编号: 'RF-304' },
  { seq: 5, 记录编号: 'TEMP-D05', 运单编号: 'SHIP-D05', 当前温度: '13.6', 温度上限: '8', 温度下限: '0', 记录时间: '2026-09-29 10:20', 设备编号: 'RF-305' },
  { seq: 6, 记录编号: 'TEMP-D06', 运单编号: 'SHIP-D06', 当前温度: '17.5', 温度上限: '8', 温度下限: '0', 记录时间: '2026-09-29 10:25', 设备编号: 'RF-306' },
  { seq: 7, 记录编号: 'TEMP-D07', 运单编号: 'SHIP-D07', 当前温度: '5.5', 温度上限: '', 温度下限: '', 记录时间: '2026-09-29 10:30', 设备编号: 'RF-307' },
]

const rules = computed<Rule[]>(() => dashboard.value?.rules ?? [])

const statCards = computed(() => {
  const d = dashboard.value
  return [
    { label: '正常记录', value: d?.['正常'] ?? 0 },
    { label: '接近临界', value: d?.['接近临界'] ?? 0 },
    { label: '超温记录', value: d?.['超温'] ?? 0 },
    { label: '三级超温', value: d?.['三级超温'] ?? 0 },
    { label: '数据缺失', value: d?.['数据缺失'] ?? 0 },
    { label: '待处理超温报警', value: d?.['待处理超温报警'] ?? 0 },
  ]
})

function ruleText(rule: Rule): string {
  if (rule.max_delta !== null) {
    return `${rule.direction} ${rule.min_delta ?? 0}~${rule.max_delta}℃`
  }
  if (rule.min_delta !== null && rule.min_delta > 0) {
    return `${rule.direction} ≥${rule.min_delta}℃`
  }
  return `${rule.direction} 0~2℃ 临近带`
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function ingestDemo(simulateInterrupt: boolean) {
  errorMessage.value = ''
  infoMessage.value = ''
  busy.value = true
  try {
    const response = await request(`${ENDPOINT}/ingest`, {
      method: 'POST',
      body: JSON.stringify({ records: DEMO_BATCH, fail_after: simulateInterrupt ? 4 : null }),
    })
    const payload = await response.json()
    if (payload.interrupted) {
      infoMessage.value = `${payload.message}；本次处理 ${payload.processed} 条，点击「从断点继续」恢复`
    } else {
      infoMessage.value = `接入完成：新增 ${payload.ingested} 条，更新 ${payload.updated} 条，幂等跳过 ${payload.skipped} 条，新生成报警 ${payload.new_alarms} 条（断点序号 ${payload.checkpoint}）`
    }
    await Promise.all([reload(), refreshDashboard(), refreshCheckpoint()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '温度记录接入失败'
  } finally {
    busy.value = false
  }
}

function supplement(row: Row) {
  const temp = window.prompt(`补录 ${String(row['记录编号'])} 的当前温度（留空保持原值，恢复正常可填 4.0）`, String(row['当前温度'] ?? ''))
  if (temp === null) return
  const upper = window.prompt('温度上限（留空保持原值）', String(row['温度上限'] ?? ''))
  if (upper === null) return
  const lower = window.prompt('温度下限（留空保持原值）', String(row['温度下限'] ?? ''))
  if (lower === null) return
  const values: Record<string, string> = { action: '数据补录' }
  if (temp.trim()) values['当前温度'] = temp.trim()
  if (upper.trim()) values['温度上限'] = upper.trim()
  if (lower.trim()) values['温度下限'] = lower.trim()
  void runAction('数据补录', row, values)
}

async function runAction(action: string, row: Row, values: Record<string, string> = { action }) {
  errorMessage.value = ''
  infoMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '温控监测动作未生效，请稍后重试')
    }
    infoMessage.value = payload.message
    await Promise.all([reload(), refreshDashboard()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '温控监测操作失败'
  }
}

async function refreshDashboard() {
  try {
    const response = await request(`${ENDPOINT}/dashboard`)
    if (response.ok) dashboard.value = await response.json()
  } catch {
    // 看板读失败不阻塞明细
  }
}

async function refreshCheckpoint() {
  try {
    const response = await request(`${ENDPOINT}/checkpoint`)
    if (response.ok) checkpoint.value = await response.json()
  } catch {
    // 断点读取失败时保持页面可用
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value) query.set('keyword', keyword.value)
  if (statusFilter.value) query.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
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
  await Promise.all([reload(), refreshDashboard(), refreshCheckpoint()])
})
</script>

<style scoped>
.rule-panel {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 12px;
}

.rule-panel h3 {
  margin: 0 0 8px;
  font-size: 13px;
}

.rule-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.rule-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 3px 10px;
  background: #f6f8fa;
}

.rule-chip.alarm {
  border-color: #f0b8b0;
  background: #fdf3f2;
}

.rule-chip em {
  font-style: normal;
  font-weight: 700;
  color: var(--brand);
}

.rule-chip small {
  color: var(--muted);
}

.info-text {
  color: #175cd3;
}
</style>
