import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, BarChart3, Database, Film, Search, ShieldCheck, X } from 'lucide-react'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { PageHeader } from '@/components/common/PageHeader'
import { getAssetAnalysis, type AnalysisDimension, type AnalysisItem, type CoverageStatus } from '@/services/asset-analysis'

const STATUS: Record<CoverageStatus, { label: string; classes: string }> = {
  complete: { label: '覆盖完整', classes: 'bg-emerald-50 text-emerald-700' },
  delayed: { label: '来源延迟', classes: 'bg-violet-50 text-violet-700' },
  partial: { label: '部分覆盖', classes: 'bg-amber-50 text-amber-800' },
  unmapped: { label: '未映射', classes: 'bg-orange-50 text-orange-800' },
  not_uploaded: { label: '未上传', classes: 'bg-slate-100 text-slate-700' },
  missing_version: { label: '缺少版本', classes: 'bg-red-50 text-red-700' },
  no_platform_data: { label: '无平台数据', classes: 'bg-blue-50 text-blue-700' },
}

function isoDate(daysAgo = 0) {
  const value = new Date()
  value.setDate(value.getDate() - daysAgo)
  return value.toISOString().slice(0, 10)
}

function amount(value: string | null, currency = 'USD') {
  if (value === null) return '—'
  return `${Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })} ${currency}`
}

function integer(value: number | null) {
  if (value === null) return '—'
  return value.toLocaleString('zh-CN')
}

function roi(item: AnalysisItem) {
  return item.metrics.roi === null ? <span title={item.metrics.roi_reason ?? '覆盖不足'}>—</span> : Number(item.metrics.roi).toFixed(2)
}

function StatusBadge({ status }: { status: CoverageStatus }) {
  const config = STATUS[status] ?? { label: status, classes: 'bg-slate-100 text-slate-700' }
  return <span className={`inline-flex rounded-full px-2 py-1 text-xs font-medium ${config.classes}`}>{config.label}</span>
}

function DetailDrawer({ item, onClose }: { item: AnalysisItem; onClose: () => void }) {
  return <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/25" role="dialog" aria-modal="true" aria-label="分析明细">
    <button className="flex-1" aria-label="关闭明细" onClick={onClose} />
    <aside className="h-full w-full max-w-xl overflow-y-auto bg-white p-6 shadow-2xl">
      <div className="flex items-start justify-between gap-4"><div><div className="text-xs text-slate-500">{item.entity_type === 'material' ? '素材明细' : '剧目明细'}</div><h2 className="mt-1 text-xl font-semibold">{item.name}</h2><div className="mt-2"><StatusBadge status={item.coverage_status} /></div></div><button onClick={onClose} className="rounded-lg p-2 hover:bg-slate-100"><X className="h-5 w-5" /></button></div>
      <section className="mt-6 rounded-xl border p-4"><h3 className="font-medium">指标与口径</h3><dl className="mt-3 grid grid-cols-2 gap-3 text-sm"><div><dt className="text-xs text-slate-500">消耗</dt><dd>{amount(item.metrics.spend)}</dd></div><div><dt className="text-xs text-slate-500">归因收入</dt><dd>{amount(item.metrics.revenue_attributed)}</dd></div><div><dt className="text-xs text-slate-500">ROI</dt><dd>{roi(item)}</dd></div><div><dt className="text-xs text-slate-500">数据截止</dt><dd>{item.metrics.data_cutoff_at ?? '暂无'}</dd></div><div><dt className="text-xs text-slate-500">平台映射</dt><dd>{item.matched_mapping_count}/{item.mapping_count}</dd></div><div><dt className="text-xs text-slate-500">账户币种 / 时区</dt><dd>{item.account_currencies.join('、') || '暂无'} / {item.account_timezones.join('、') || '暂无'}</dd></div></dl></section>
      <section className="mt-4 rounded-xl border p-4"><h3 className="font-medium">覆盖说明</h3>{item.coverage_reasons.length ? <ul className="mt-3 space-y-2 text-sm">{item.coverage_reasons.map(reason => <li key={reason.code} className="rounded-lg bg-slate-50 p-3"><code className="text-xs text-slate-500">{reason.code}</code><div className="mt-1">{reason.message}</div></li>)}</ul> : <p className="mt-3 text-sm text-emerald-700">当前筛选范围内的有效映射均有平台日报覆盖。</p>}</section>
      {item.source_filename !== undefined && <section className="mt-4 rounded-xl border p-4"><h3 className="font-medium">素材链路</h3><div className="mt-3 space-y-2 text-sm"><p>文件：{item.source_filename || '未登记'}</p><p>版本：{item.version_number ?? '—'} · 上传状态：{item.upload_status ?? '未知'}</p><p>平台：{item.platforms.join('、') || '未映射'}</p><p>创意组：{item.creative_groups?.map(group => `${group.name}（${group.status}）`).join('、') || '未引用'}</p><p>广告草稿/快照：{item.drafts?.map(draft => `${draft.title}（${draft.status}/${draft.snapshot}）`).join('、') || '未引用'}</p></div></section>}
      {item.materials && <section className="mt-4 rounded-xl border p-4"><h3 className="font-medium">剧目素材</h3><div className="mt-3 divide-y text-sm">{item.materials.map(material => <div key={material.id} className="flex items-center justify-between py-2"><span>{material.name}</span><span className="flex items-center gap-3"><StatusBadge status={material.coverage_status} /><span>{amount(material.spend)}</span></span></div>)}</div></section>}
    </aside>
  </div>
}

export default function AssetAnalysisPage() {
  const [dimension, setDimension] = useState<AnalysisDimension>('material')
  const [dateFrom, setDateFrom] = useState(() => isoDate(6))
  const [dateTo, setDateTo] = useState(() => isoDate())
  const [platform, setPlatform] = useState('')
  const [accountId, setAccountId] = useState('')
  const [coverageStatus, setCoverageStatus] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<AnalysisItem | null>(null)
  const query = useQuery({
    queryKey: ['asset-analysis', dimension, dateFrom, dateTo, platform, accountId, coverageStatus, search, page],
    queryFn: () => getAssetAnalysis({ dimension, dateFrom, dateTo, platform: platform || undefined, accountId: accountId || undefined, coverageStatus: coverageStatus || undefined, query: search, page }),
    enabled: Boolean(dateFrom && dateTo && dateFrom <= dateTo),
  })
  const data = query.data
  const maxPage = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1
  const chartData = useMemo(() => data?.trend.map(row => ({ ...row, spendNumber: Number(row.spend ?? 0), revenueNumber: Number(row.revenue_attributed ?? 0) })) ?? [], [data])
  return <div className="mx-auto max-w-[1500px]">
    <PageHeader title="素材与剧目分析" description="以当前租户和应用为边界，追溯素材版本、平台映射、广告草稿/快照与 BIZ 归因日报。" />
    <div className="mb-5 flex items-start gap-3 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900"><ShieldCheck className="mt-0.5 h-5 w-5 shrink-0" /><div><div className="font-medium">只读分析</div><div className="mt-1 text-xs text-blue-700">本页不会修改预算、草稿、素材或平台对象。缺失、延迟、未映射、未上传和无平台数据不会当作 0；映射覆盖不足时 ROI 留空。</div></div></div>
    <div className="mb-4 flex gap-2 rounded-xl border bg-white p-2"><button onClick={() => { setDimension('material'); setPage(1) }} className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm ${dimension === 'material' ? 'bg-slate-900 text-white' : 'hover:bg-slate-50'}`}><BarChart3 className="h-4 w-4" />素材汇总</button><button onClick={() => { setDimension('drama'); setPage(1) }} className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm ${dimension === 'drama' ? 'bg-slate-900 text-white' : 'hover:bg-slate-50'}`}><Film className="h-4 w-4" />剧目汇总</button></div>
    <section className="mb-5 grid gap-3 rounded-xl border bg-white p-4 md:grid-cols-3 xl:grid-cols-6">
      <label className="text-xs text-slate-500">开始日期<input aria-label="开始日期" type="date" value={dateFrom} onChange={e => { setDateFrom(e.target.value); setPage(1) }} className="mt-1 w-full rounded-lg border px-3 py-2 text-sm text-slate-900" /></label>
      <label className="text-xs text-slate-500">结束日期<input aria-label="结束日期" type="date" value={dateTo} onChange={e => { setDateTo(e.target.value); setPage(1) }} className="mt-1 w-full rounded-lg border px-3 py-2 text-sm text-slate-900" /></label>
      <label className="text-xs text-slate-500">平台<input aria-label="平台" value={platform} onChange={e => { setPlatform(e.target.value); setPage(1) }} placeholder="如 tiktok" className="mt-1 w-full rounded-lg border px-3 py-2 text-sm text-slate-900" /></label>
      <label className="text-xs text-slate-500">账户 ID<input aria-label="账户 ID" value={accountId} onChange={e => { setAccountId(e.target.value); setPage(1) }} className="mt-1 w-full rounded-lg border px-3 py-2 text-sm text-slate-900" /></label>
      <label className="text-xs text-slate-500">来源覆盖<select aria-label="来源覆盖" value={coverageStatus} onChange={e => { setCoverageStatus(e.target.value); setPage(1) }} className="mt-1 w-full rounded-lg border px-3 py-2 text-sm text-slate-900"><option value="">全部状态</option>{Object.entries(STATUS).map(([value, config]) => <option key={value} value={value}>{config.label}</option>)}</select></label>
      <label className="text-xs text-slate-500">搜索<div className="relative mt-1"><Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" /><input aria-label="搜索" value={search} onChange={e => { setSearch(e.target.value); setPage(1) }} placeholder="名称、ID、文件" className="w-full rounded-lg border py-2 pl-9 pr-3 text-sm text-slate-900" /></div></label>
    </section>
    {dateFrom > dateTo && <div role="alert" className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">开始日期不能晚于结束日期。</div>}
    {query.error && <div role="alert" className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{query.error instanceof Error ? query.error.message : '加载失败'}</div>}
    {data && <>
      <section className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4"><div className="rounded-xl border bg-white p-4"><div className="text-xs text-slate-500">分析对象</div><div className="mt-1 text-2xl font-semibold">{data.total}</div></div><div className="rounded-xl border bg-white p-4"><div className="text-xs text-slate-500">平台映射覆盖</div><div className="mt-1 text-2xl font-semibold">{data.coverage.matched_mapping_total}/{data.coverage.mapping_total}</div></div><div className="rounded-xl border bg-white p-4"><div className="text-xs text-slate-500">已映射 / 全部日报行</div><div className="mt-1 text-2xl font-semibold">{data.coverage.mapped_fact_rows}/{data.coverage.fact_rows_total}</div></div><div className="rounded-xl border bg-white p-4"><div className="text-xs text-slate-500">数据截止</div><div className="mt-2 text-sm font-medium">{data.coverage.data_cutoff_at ?? '暂无来源数据'}</div></div></section>
      <section className="mb-5 grid gap-4 xl:grid-cols-[2fr_1fr]"><div className="rounded-xl border bg-white p-4"><h2 className="font-medium">日趋势（USD）</h2><p className="mt-1 text-xs text-slate-500">趋势仅展示已精确映射的事实；为避免误导，不在总趋势计算 ROI。</p><div className="mt-3 h-64">{chartData.length ? <ResponsiveContainer width="100%" height="100%"><LineChart data={chartData}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="date" fontSize={11} /><YAxis fontSize={11} /><Tooltip /><Legend /><Line type="monotone" dataKey="spendNumber" name="消耗" stroke="#2563eb" /><Line type="monotone" dataKey="revenueNumber" name="归因收入" stroke="#059669" /></LineChart></ResponsiveContainer> : <div className="flex h-full items-center justify-center text-sm text-slate-500">当前范围没有已映射趋势数据。</div>}</div></div><div className="rounded-xl border bg-white p-4"><div className="flex items-center gap-2 font-medium"><Database className="h-4 w-4" />来源覆盖</div><div className="mt-3 space-y-2">{Object.entries(data.coverage.states).map(([status, count]) => <button key={status} onClick={() => setCoverageStatus(status)} className="flex w-full items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-sm"><StatusBadge status={status as CoverageStatus} /><strong>{count}</strong></button>)}</div><div className="mt-4 border-t pt-3 text-xs text-slate-500">未映射日报 {data.coverage.unmapped_fact_rows} 行 · 歧义日报 {data.coverage.ambiguous_fact_rows} 行</div></div></section>
      <section className="overflow-hidden rounded-xl border bg-white"><div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="bg-slate-50 text-xs text-slate-500"><tr><th className="px-4 py-3">{dimension === 'material' ? '素材' : '剧目'}</th><th className="px-4 py-3">覆盖</th><th className="px-4 py-3 text-right">消耗</th><th className="px-4 py-3 text-right">归因收入</th><th className="px-4 py-3 text-right">ROI</th><th className="px-4 py-3 text-right">曝光 / 点击</th><th className="px-4 py-3">来源</th></tr></thead><tbody>{data.items.map(item => <tr key={item.entity_id} onClick={() => setSelected(item)} className="cursor-pointer border-t align-top hover:bg-slate-50"><td className="px-4 py-3"><div className="font-medium">{item.name}</div><div className="mt-1 text-xs text-slate-500">{dimension === 'material' ? `${item.source_filename || '无文件'} · v${item.version_number ?? '—'}` : `${item.material_count ?? 0} 个素材 · ${item.complete_material_count ?? 0} 个覆盖完整`}</div>{item.drama_title && dimension === 'material' ? <div className="mt-1 text-xs text-slate-400">剧目：{item.drama_title}</div> : null}</td><td className="px-4 py-3"><StatusBadge status={item.coverage_status} /></td><td className="px-4 py-3 text-right">{amount(item.metrics.spend)}</td><td className="px-4 py-3 text-right">{amount(item.metrics.revenue_attributed)}</td><td className="px-4 py-3 text-right font-medium">{roi(item)}</td><td className="px-4 py-3 text-right">{integer(item.metrics.impressions)} / {integer(item.metrics.clicks)}</td><td className="px-4 py-3 text-xs text-slate-600"><div>{item.platforms.join('、') || '未映射平台'}</div><div className="mt-1">映射 {item.matched_mapping_count}/{item.mapping_count}</div><div className="mt-1">{item.account_timezones.join('、') || '无账户时区'}</div></td></tr>)}</tbody></table></div>{!data.items.length && <div className="p-12 text-center text-sm text-slate-500"><AlertTriangle className="mx-auto mb-2 h-5 w-5" />当前筛选范围没有记录；这不代表指标为 0。</div>}<div className="flex items-center justify-between border-t px-4 py-3 text-sm text-slate-600"><span>共 {data.total} 项 · 第 {data.page}/{maxPage} 页</span><div className="flex gap-2"><button disabled={page <= 1} onClick={() => setPage(value => Math.max(1, value - 1))} className="rounded border px-3 py-1 disabled:opacity-40">上一页</button><button disabled={page >= maxPage} onClick={() => setPage(value => Math.min(maxPage, value + 1))} className="rounded border px-3 py-1 disabled:opacity-40">下一页</button></div></div></section>
      <section className="mt-5 rounded-xl border bg-slate-50 p-4 text-xs text-slate-600"><div className="font-medium text-slate-800">口径与限制</div><ul className="mt-2 list-disc space-y-1 pl-5">{data.coverage.notes.map(note => <li key={note}>{note}</li>)}<li>{data.currency_policy}</li><li>来源：{data.coverage.sources.join('；')}</li></ul></section>
    </>}
    {query.isLoading && <div className="rounded-xl border bg-white p-16 text-center text-sm text-slate-500">正在读取当前应用的分析数据…</div>}
    {selected && <DetailDrawer item={selected} onClose={() => setSelected(null)} />}
  </div>
}
