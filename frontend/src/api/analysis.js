import api from './index'

// ============================================================
// 演示数据（mock）：后端未接真实谷仓数据时，用于前端预览效果。
// 上线接入真实数据后，设置 MOCK=false 或删除本文件的 fallback 即可。
// ============================================================
const MOCK = true

const DEMO = {
  summary: {
    month: '2026-08', total: 42850.32, mom_pct: 12.6,
    structure: [
      { category: 'storage', label: '仓储费', amount: 18200.0 },
      { category: 'inbound', label: '入库费', amount: 4250.0 },
      { category: 'outbound', label: '出库操作费', amount: 9800.0 },
      { category: 'transport', label: '运输费', amount: 8650.32 },
      { category: 'other', label: '其他费用', amount: 1950.0 }
    ]
  },
  trend: {
    warehouse: 'DE1',
    trend: [
      { month: '2025-09', total: 31000, storage: 14000, transport: 7000, mom_pct: null },
      { month: '2025-10', total: 33500, storage: 15000, transport: 7600, mom_pct: 8.1 },
      { month: '2025-11', total: 35800, storage: 16000, transport: 8200, mom_pct: 6.9 },
      { month: '2025-12', total: 41200, storage: 17500, transport: 9500, mom_pct: 15.1 },
      { month: '2026-01', total: 36800, storage: 16200, transport: 8300, mom_pct: -10.7 },
      { month: '2026-02', total: 35400, storage: 15800, transport: 8000, mom_pct: -3.8 },
      { month: '2026-03', total: 37900, storage: 16600, transport: 8500, mom_pct: 7.1 },
      { month: '2026-04', total: 36100, storage: 16000, transport: 8100, mom_pct: -4.7 },
      { month: '2026-05', total: 38900, storage: 17000, transport: 8600, mom_pct: 7.8 },
      { month: '2026-06', total: 39500, storage: 17200, transport: 8800, mom_pct: 1.5 },
      { month: '2026-07', total: 38050, storage: 16800, transport: 8500, mom_pct: -3.7 },
      { month: '2026-08', total: 42850, storage: 18200, transport: 8650, mom_pct: 12.6 }
    ]
  },
  health: {
    snapshot_date: '2026-09-01', total_quantity: 4820,
    buckets: [
      { bucket: 'healthy', label: '健康库存', sku_count: 120, quantity: 2650, qty_pct: 55.0 },
      { bucket: 'watch', label: '关注库存', sku_count: 38, quantity: 720, qty_pct: 14.9 },
      { bucket: 'stale', label: '呆滞库存', sku_count: 22, quantity: 680, qty_pct: 14.1 },
      { bucket: 'critical', label: '严重呆滞库存', sku_count: 15, quantity: 770, qty_pct: 16.0 }
    ]
  },
  risk: {
    snapshot_date: '2026-09-01',
    items: [
      { rank: 1, sku: 'GC-DE-88421', product_name: '智能温控杯 500ml', quantity: 220, warehouse_age: 512, age_bucket: 'critical', label: '严重呆滞库存' },
      { rank: 2, sku: 'GC-DE-77210', product_name: '折叠收纳箱 XL', quantity: 145, warehouse_age: 468, age_bucket: 'critical', label: '严重呆滞库存' },
      { rank: 3, sku: 'GC-DE-66344', product_name: '便携榨汁机', quantity: 90, warehouse_age: 431, age_bucket: 'critical', label: '严重呆滞库存' },
      { rank: 4, sku: 'GC-DE-55892', product_name: 'LED 台灯触控版', quantity: 300, warehouse_age: 366, age_bucket: 'critical', label: '严重呆滞库存' },
      { rank: 5, sku: 'GC-DE-44117', product_name: '厨房收纳架三层', quantity: 175, warehouse_age: 355, age_bucket: 'stale', label: '呆滞库存' },
      { rank: 6, sku: 'GC-DE-33581', product_name: '瑜伽垫加厚', quantity: 260, warehouse_age: 320, age_bucket: 'stale', label: '呆滞库存' },
      { rank: 7, sku: 'GC-DE-22960', product_name: '车载手机支架', quantity: 410, warehouse_age: 288, age_bucket: 'stale', label: '呆滞库存' },
      { rank: 8, sku: 'GC-DE-11874', product_name: '宠物喂食器', quantity: 130, warehouse_age: 210, age_bucket: 'stale', label: '呆滞库存' },
      { rank: 9, sku: 'GC-DE-09533', product_name: '空气炸锅纸', quantity: 520, warehouse_age: 175, age_bucket: 'watch', label: '关注库存' },
      { rank: 10, sku: 'GC-DE-08120', product_name: '电动牙刷头', quantity: 380, warehouse_age: 120, age_bucket: 'watch', label: '关注库存' },
      { rank: 11, sku: 'GC-DE-06608', product_name: '真空压缩袋', quantity: 460, warehouse_age: 98, age_bucket: 'watch', label: '关注库存' },
      { rank: 12, sku: 'GC-DE-05231', product_name: '香薰加湿器', quantity: 150, warehouse_age: 95, age_bucket: 'watch', label: '关注库存' }
    ]
  },
  report: {
    report_month: '2026-08',
    title: '德国海外仓成本健康报告（2026-08）',
    content_md: `# 德国海外仓成本健康报告（2026-08）

## 一、成本变化
- 本月总成本：¥42,850.32
- 环比变化：+12.60%

## 二、费用结构
- 仓储费：¥18,200.00
- 入库费：¥4,250.00
- 出库操作费：¥9,800.00
- 运输费：¥8,650.32
- 其他费用：¥1,950.00

## 三、库存风险
- 健康库存：120 SKU / 2650 件
- 关注库存：38 SKU / 720 件
- 呆滞库存：22 SKU / 680 件
- 严重呆滞库存：15 SKU / 770 件

TOP 风险 SKU：
- #1 GC-DE-88421（库龄 512 天，220 件）
- #2 GC-DE-77210（库龄 468 天，145 件）

## 四、优化建议
- [高] 本月总成本环比上涨 12.60%，建议核查仓储费与运输费增长原因。
- [中] 费用以「仓储费」为主（¥18,200.00），可重点优化该项。
- [高] 严重呆滞库存 770 件，建议评估促销/退运/销毁方案。`
  }
}

// 统一请求：MOCK 时直接返回演示数据，否则走真实后端
async function request(fn, mockData) {
  if (MOCK) return mockData
  return fn()
}

export const getCostSummary = (month) => request(
  () => api.get('/analysis/cost/summary', { params: { bill_month: month } }), DEMO.summary
)
export const getCostTrend = (months = 12) => request(
  () => api.get('/analysis/cost/trend', { params: { months } }), DEMO.trend
)
export const getInventoryHealth = (date) => request(
  () => api.get('/analysis/inventory/health', { params: { snapshot_date: date } }), DEMO.health
)
export const getRiskSku = (date, top = 20) => request(
  () => api.get('/analysis/inventory/risk-sku', { params: { snapshot_date: date, top } }), DEMO.risk
)
export const getMonthlyReport = (month) => request(
  () => api.get('/analysis/report/monthly', { params: { report_month: month } }), DEMO.report
)
export const runSync = () => api.post('/sync/run')
export const getSyncLogs = (limit = 20) => api.get('/sync/logs', { params: { limit } })
