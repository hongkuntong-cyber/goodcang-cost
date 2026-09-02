<script setup>
import { ref, onMounted, computed } from 'vue'
import * as echarts from 'echarts'
import {
  getCostSummary, getCostTrend, getInventoryHealth,
  getRiskSku, getMonthlyReport, runSync, getSyncLogs
} from './api/analysis'

// ---- 状态 ----
const activeTab = ref('cost') // cost | structure | inventory | risk | report
const loading = ref(false)
const error = ref('')
const syncing = ref(false)
const syncLogs = ref([])

const summary = ref(null)
const trend = ref([])
const health = ref(null)
const risk = ref([])
const report = ref(null)

// 图表 refs
const trendChartRef = ref(null)
const structureChartRef = ref(null)
const healthChartRef = ref(null)
const riskChartRef = ref(null)

const tabs = [
  { key: 'cost', label: '月度成本' },
  { key: 'structure', label: '费用结构' },
  { key: 'inventory', label: '库存健康' },
  { key: 'risk', label: '风险SKU' },
  { key: 'report', label: '月度报告' }
]

// ---- 加载数据 ----
async function loadAll() {
  loading.value = true
  error.value = ''
  try {
    summary.value = await getCostSummary()
    const t = await getCostTrend(12)
    trend.value = t.trend || []
    health.value = await getInventoryHealth()
    risk.value = (await getRiskSku(null, 20)).items || []
    report.value = await getMonthlyReport()
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
    renderCharts()
  }
}

function renderCharts() {
  // 用 nextTick 确保 DOM 渲染后再画
  import('vue').then(({ nextTick }) => nextTick(() => {
    drawTrend()
    drawStructure()
    drawHealth()
    drawRisk()
  }))
}

function baseOption() {
  return {
    textStyle: { fontFamily: 'PingFang SC, Microsoft YaHei, sans-serif' },
    tooltip: { trigger: 'axis' },
    grid: { left: 50, right: 20, top: 40, bottom: 30 }
  }
}

function drawTrend() {
  if (!trendChartRef.value || !trend.value.length) return
  const chart = echarts.getInstanceByDom(trendChartRef.value) || echarts.init(trendChartRef.value)
  const months = trend.value.map((x) => x.month)
  const totals = trend.value.map((x) => x.total)
  const storage = trend.value.map((x) => x.storage)
  const transport = trend.value.map((x) => x.transport)
  chart.setOption({
    ...baseOption(),
    tooltip: { trigger: 'axis' },
    legend: { data: ['总成本', '仓储费', '运输费'] },
    xAxis: { type: 'category', data: months },
    yAxis: { type: 'value', name: '¥' },
    series: [
      { name: '总成本', type: 'line', data: totals, smooth: true, itemStyle: { color: '#2f6bff' }, areaStyle: { opacity: 0.1 } },
      { name: '仓储费', type: 'bar', data: storage, itemStyle: { color: '#94a3b8' } },
      { name: '运输费', type: 'bar', data: transport, itemStyle: { color: '#cbd5e1' } }
    ]
  })
}

function drawStructure() {
  if (!structureChartRef.value || !summary.value) return
  const chart = echarts.getInstanceByDom(structureChartRef.value) || echarts.init(structureChartRef.value)
  const items = summary.value.structure || []
  chart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: ¥{c} ({d}%)' },
    legend: { orient: 'vertical', left: 'left' },
    series: [{
      type: 'pie', radius: ['40%', '68%'], center: ['55%', '50%'],
      itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 },
      label: { formatter: '{b}\n{d}%' },
      data: items.map((i) => ({ name: i.label, value: i.amount }))
    }]
  })
}

function drawHealth() {
  if (!healthChartRef.value || !health.value) return
  const chart = echarts.getInstanceByDom(healthChartRef.value) || echarts.init(healthChartRef.value)
  const buckets = health.value.buckets || []
  const colors = { healthy: '#16a34a', watch: '#f59e0b', stale: '#f97316', critical: '#e64545' }
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: buckets.map((b) => b.label) },
    xAxis: { type: 'category', data: buckets.map((b) => b.label) },
    yAxis: { type: 'value', name: '件' },
    series: [{
      type: 'bar', barWidth: '45%',
      data: buckets.map((b) => ({ value: b.quantity, itemStyle: { color: colors[b.bucket] } }))
    }]
  })
}

function drawRisk() {
  if (!riskChartRef.value || !risk.value.length) return
  const chart = echarts.getInstanceByDom(riskChartRef.value) || echarts.init(riskChartRef.value)
  const top10 = risk.value.slice(0, 10).reverse()
  chart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 90, right: 30, top: 20, bottom: 30 },
    xAxis: { type: 'value', name: '库龄(天)' },
    yAxis: { type: 'category', data: top10.map((x) => x.sku) },
    series: [{
      type: 'bar', barWidth: '55%',
      data: top10.map((x) => ({
        value: x.warehouse_age,
        itemStyle: { color: x.age_bucket === 'critical' ? '#e64545' : x.age_bucket === 'stale' ? '#f97316' : '#f59e0b' }
      }))
    }]
  })
}

async function handleSync() {
  syncing.value = true
  try {
    await runSync()
    await loadAll()
    syncLogs.value = await getSyncLogs()
  } catch (e) {
    error.value = e.message
  } finally {
    syncing.value = false
  }
}

function fmt(v) {
  return v == null ? '—' : Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

const momClass = computed(() => {
  const m = summary.value?.mom_pct
  if (m == null) return ''
  return m > 0 ? 'up' : m < 0 ? 'down' : ''
})

onMounted(async () => {
  await loadAll()
  try { syncLogs.value = await getSyncLogs() } catch (e) { /* 忽略 */ }
})
</script>

<template>
  <div>
    <header class="topbar">
      <h1>谷仓海外仓成本健康分析</h1>
      <div class="actions">
        <button @click="loadAll">刷新</button>
        <button class="primary" :disabled="syncing" @click="handleSync">
          {{ syncing ? '同步中…' : '立即同步' }}
        </button>
      </div>
    </header>

    <div class="layout">
      <aside class="sidebar">
        <a v-for="t in tabs" :key="t.key" class="nav-item"
           :class="{ active: activeTab === t.key }" @click="activeTab = t.key">
          {{ t.label }}
        </a>
      </aside>

      <main class="content">
        <div v-if="error" class="card" style="color:#e64545">{{ error }}</div>

        <div v-if="loading" class="card">加载中…</div>

        <template v-else>
          <!-- 月度成本 -->
          <section v-if="activeTab === 'cost'">
            <div class="kpi-row">
              <div class="kpi">
                <div class="label">本月总成本</div>
                <div class="value">¥{{ fmt(summary?.total) }}</div>
              </div>
              <div class="kpi">
                <div class="label">环比变化</div>
                <div class="value" :class="momClass">
                  {{ summary?.mom_pct == null ? '—' : (summary.mom_pct > 0 ? '+' : '') + summary.mom_pct + '%' }}
                </div>
                <div class="sub">较上月</div>
              </div>
              <div class="kpi">
                <div class="label">统计月份</div>
                <div class="value" style="font-size:20px">{{ summary?.month || '—' }}</div>
              </div>
            </div>
            <div class="card">
              <h2>12 个月成本趋势</h2>
              <div ref="trendChartRef" class="chart"></div>
            </div>
          </section>

          <!-- 费用结构 -->
          <section v-if="activeTab === 'structure'">
            <div class="card">
              <h2>费用结构（{{ summary?.month }}）</h2>
              <div ref="structureChartRef" class="chart"></div>
            </div>
            <div class="card">
              <h2>费用明细</h2>
              <table>
                <thead><tr><th>类别</th><th>金额</th></tr></thead>
                <tbody>
                  <tr v-for="i in summary?.structure || []" :key="i.category">
                    <td>{{ i.label }}</td><td>¥{{ fmt(i.amount) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <!-- 库存健康 -->
          <section v-if="activeTab === 'inventory'">
            <div class="card">
              <h2>库存年龄健康度（{{ health?.snapshot_date }}）</h2>
              <div ref="healthChartRef" class="chart"></div>
            </div>
            <div class="card">
              <table>
                <thead><tr><th>分类</th><th>SKU 数</th><th>库存件数</th><th>占比</th></tr></thead>
                <tbody>
                  <tr v-for="b in health?.buckets || []" :key="b.bucket">
                    <td><span class="badge" :class="b.bucket">{{ b.label }}</span></td>
                    <td>{{ b.sku_count }}</td>
                    <td>{{ b.quantity }}</td>
                    <td>{{ b.qty_pct }}%</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <!-- 风险 SKU -->
          <section v-if="activeTab === 'risk'">
            <div class="card">
              <h2>TOP 风险 SKU（按库龄 → 数量排序）</h2>
              <div ref="riskChartRef" class="chart"></div>
            </div>
            <div class="card">
              <table>
                <thead><tr><th>排名</th><th>SKU</th><th>商品名称</th><th>库龄(天)</th><th>库存数量</th><th>状态</th></tr></thead>
                <tbody>
                  <tr v-for="r in risk" :key="r.sku">
                    <td>#{{ r.rank }}</td>
                    <td>{{ r.sku }}</td>
                    <td>{{ r.product_name || '—' }}</td>
                    <td>{{ r.warehouse_age }}</td>
                    <td>{{ r.quantity }}</td>
                    <td><span class="badge" :class="r.age_bucket">{{ r.label }}</span></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <!-- 月度报告 -->
          <section v-if="activeTab === 'report'">
            <div class="card">
              <h2>{{ report?.title }}</h2>
              <div class="report-md">{{ report?.content_md }}</div>
            </div>
          </section>
        </template>

        <!-- 同步日志 -->
        <div class="card" v-if="syncLogs.length">
          <h2>最近同步日志</h2>
          <table>
            <thead><tr><th>任务</th><th>接口</th><th>状态</th><th>记录数</th><th>时间</th></tr></thead>
            <tbody>
              <tr v-for="(l, i) in syncLogs" :key="i">
                <td>{{ l.task_name }}</td>
                <td>{{ l.endpoint }}</td>
                <td>{{ l.status }}</td>
                <td>{{ l.records_affected }}</td>
                <td>{{ l.started_at }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </main>
    </div>
  </div>
</template>
