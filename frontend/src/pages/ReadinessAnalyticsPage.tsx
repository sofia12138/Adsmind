import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Boxes, CheckCircle2, Clock3, FileSearch, Loader2, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import { PageHeader } from '@/components/common/PageHeader'
import { getReadinessDetails, type ReadinessEntityType } from '@/services/readiness-analytics'

const entityOptions: Array<{ value: ReadinessEntityType | ''; label: string }> = [
  { value: '', label: '全部对象' }, { value: 'material', label: '应用素材' },
  { value: 'creative_group', label: '创意组' }, { value: 'draft', label: '广告草稿' },
  { value: 'preflight', label: '平台预检' },
]

const statusOptions: Record<string, Array<{ value: string; label: string }>> = {
  material: [
    { value: 'uploaded', label: '已上传' }, { value: 'pending_upload', label: '待上传' },
    { value: 'uploading', label: '上传中' }, { value: 'failed', label: '上传失败' },
    { value: 'missing', label: '缺少版本' }, { value: 'unknown', label: '状态未知' },
  ],
  creative_group: [{ value: 'deliverable', label: '可投放' }, { value: 'blocked', label: '已阻断' }, { value: 'unknown', label: '状态未知' }],
  draft: [{ value: 'ready', label: 'READY' }, { value: 'blocked', label: '已阻断' }, { value: 'pending', label: '待标记就绪' }, { value: 'unknown', label: '状态未知' }],
  preflight: [{ value: 'passed', label: '已通过' }, { value: 'blocked', label: '已阻断' }, { value: 'not_run', label: '未运行' }, { value: 'unknown', label: '状态未知' }],
}

function formatTime(value: string | null | undefined) {
  if (!value) return '暂无变化记录'
  const date = new Date(value.includes('T') ? value : value.replace(' ', 'T') + 'Z')
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function Metric({ label, value, tone = 'neutral' }: { label: string; value: number; tone?: 'good' | 'warn' | 'neutral' }) {
  const color = tone === 'good' ? 'text-emerald-700' : tone === 'warn' ? 'text-amber-700' : 'text-slate-700'
  return <div className="rounded-lg border border-slate-200 bg-white px-3 py-2"><div className="text-xs text-slate-500">{label}</div><div className={`mt-1 text-xl font-semibold ${color}`}>{value}</div></div>
}

function StatusBadge({ status, label }: { status: string; label: string }) {
  const good = ['uploaded', 'deliverable', 'ready', 'passed'].includes(status)
  const unknown = ['unknown', 'missing', 'not_run', 'pending'].includes(status)
  return <span className={`inline-flex rounded-full px-2 py-1 text-xs font-medium ${good ? 'bg-emerald-50 text-emerald-700' : unknown ? 'bg-slate-100 text-slate-700' : 'bg-amber-50 text-amber-800'}`}>{label}</span>
}

export default function ReadinessAnalyticsPage() {
  const [entityType, setEntityType] = useState<ReadinessEntityType | ''>('')
  const [status, setStatus] = useState('')
  const [reasonCode, setReasonCode] = useState('')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const result = useQuery({
    queryKey: ['readiness-analytics', entityType, status, reasonCode, query, page],
    queryFn: () => getReadinessDetails({ entityType: entityType || undefined, status: status || undefined, reasonCode: reasonCode || undefined, query, page }),
  })
  const data = result.data
  const statuses = entityType ? statusOptions[entityType] : []
  const pageCount = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1

  return <div className="mx-auto max-w-7xl">
    <PageHeader title="投放准备就绪度" description="汇总当前应用的素材、创意组、广告草稿与 dry-run 预检状态，提供可追溯的待处理清单。" />
    <div className="mb-5 flex items-start gap-3 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900">
      <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0" />
      <div><div className="font-medium">只读准备分析</div><div className="mt-1 text-xs text-blue-700">本页不会上传素材、创建广告或调用真实平台；也不展示广告效果、消耗、ROI 或实际投放结果。缺失、未知和未运行均单独展示。</div></div>
    </div>
    {result.isLoading && <Loader2 className="mx-auto mt-24 h-7 w-7 animate-spin text-slate-400" />}
    {result.error && <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{result.error instanceof Error ? result.error.message : '加载失败'}</div>}
    {data && <>
      <div className="mb-5 grid gap-4 xl:grid-cols-4">
        <section className="rounded-xl border border-slate-200 bg-slate-50 p-4"><div className="mb-3 flex items-center gap-2 font-medium"><Boxes className="h-4 w-4" />素材上传状态</div><div className="grid grid-cols-2 gap-2"><Metric label="已上传" value={data.summary.materials.uploaded} tone="good" /><Metric label="待上传" value={data.summary.materials.pending_upload} tone="warn" /><Metric label="上传中" value={data.summary.materials.uploading} /><Metric label="上传失败" value={data.summary.materials.failed} tone="warn" /><Metric label="缺少版本" value={data.summary.materials.missing} tone="warn" /><Metric label="状态未知" value={data.summary.materials.unknown} /></div></section>
        <section className="rounded-xl border border-slate-200 bg-slate-50 p-4"><div className="mb-3 flex items-center gap-2 font-medium"><CheckCircle2 className="h-4 w-4" />创意组可投放率</div><div className="grid grid-cols-2 gap-2"><Metric label="可投放" value={data.summary.creative_groups.deliverable} tone="good" /><Metric label="已阻断" value={data.summary.creative_groups.blocked} tone="warn" /><Metric label="状态未知" value={data.summary.creative_groups.unknown} /></div><div className="mt-3 text-xs text-slate-500">可投放率：{data.summary.creative_groups.deliverable + data.summary.creative_groups.blocked > 0 ? `${Math.round(data.summary.creative_groups.deliverable / (data.summary.creative_groups.deliverable + data.summary.creative_groups.blocked) * 100)}%` : '无可计算样本'}</div></section>
        <section className="rounded-xl border border-slate-200 bg-slate-50 p-4"><div className="mb-3 flex items-center gap-2 font-medium"><FileSearch className="h-4 w-4" />广告草稿</div><div className="grid grid-cols-2 gap-2"><Metric label="READY" value={data.summary.drafts.ready} tone="good" /><Metric label="已阻断" value={data.summary.drafts.blocked} tone="warn" /><Metric label="待标记就绪" value={data.summary.drafts.pending} /><Metric label="状态未知" value={data.summary.drafts.unknown} /></div></section>
        <section className="rounded-xl border border-slate-200 bg-slate-50 p-4"><div className="mb-3 flex items-center gap-2 font-medium"><AlertTriangle className="h-4 w-4" />平台预检</div><div className="grid grid-cols-2 gap-2"><Metric label="已通过" value={data.summary.preflights.passed} tone="good" /><Metric label="已阻断" value={data.summary.preflights.blocked} tone="warn" /><Metric label="未运行" value={data.summary.preflights.not_run} /><Metric label="状态未知" value={data.summary.preflights.unknown} /></div></section>
      </div>
      <div className="mb-5 grid gap-4 lg:grid-cols-[1fr_2fr]">
        <section className="rounded-xl border border-slate-200 bg-white p-4"><div className="font-medium">预检阻断原因分布</div>{data.summary.preflight_blocking_reasons.length ? <div className="mt-3 space-y-2">{data.summary.preflight_blocking_reasons.map(item => <button key={item.code} onClick={() => { setEntityType('preflight'); setReasonCode(item.code); setPage(1) }} className="flex w-full items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-left text-xs hover:bg-slate-100"><span className="font-mono text-slate-700">{item.code}</span><span className="font-semibold">{item.count}</span></button>)}</div> : <div className="mt-4 text-sm text-slate-500">暂无结构化预检阻断原因。</div>}</section>
        <section className="rounded-xl border border-slate-200 bg-white p-4"><div className="flex items-center gap-2 font-medium"><Clock3 className="h-4 w-4" />最近变化时间</div><div className="mt-3 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">{([['素材', data.source_freshness.materials], ['创意组', data.source_freshness.creative_groups], ['草稿', data.source_freshness.drafts], ['预检', data.source_freshness.preflights]] as const).map(([label, value]) => <div key={label}><div className="text-xs text-slate-500">{label}</div><div className="mt-1">{formatTime(value)}</div></div>)}</div><div className="mt-4 border-t pt-3 text-xs text-slate-500">全局最近变化：{formatTime(data.summary.last_changed_at)} · 待处理项目 {data.summary.pending_total} 项</div></section>
      </div>
      <section className="rounded-xl border border-slate-200 bg-white">
        <div className="grid gap-3 border-b p-4 md:grid-cols-4">
          <select value={entityType} onChange={event => { setEntityType(event.target.value as ReadinessEntityType | ''); setStatus(''); setPage(1) }} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">{entityOptions.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select>
          <select value={status} onChange={event => { setStatus(event.target.value); setPage(1) }} disabled={!entityType} className="rounded-lg border border-slate-300 px-3 py-2 text-sm disabled:bg-slate-100"><option value="">全部状态</option>{statuses.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select>
          <input value={reasonCode} onChange={event => { setReasonCode(event.target.value); setPage(1) }} placeholder="阻断代码（精确）" className="rounded-lg border border-slate-300 px-3 py-2 text-sm" />
          <input value={query} onChange={event => { setQuery(event.target.value); setPage(1) }} placeholder="搜索名称、ID、剧目或文件名" className="rounded-lg border border-slate-300 px-3 py-2 text-sm" />
        </div>
        <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="bg-slate-50 text-xs text-slate-500"><tr><th className="px-4 py-3">对象</th><th className="px-4 py-3">状态</th><th className="px-4 py-3">阻断 / 待处理原因</th><th className="px-4 py-3">最近变化</th><th className="px-4 py-3">追溯</th></tr></thead><tbody>{data.data.map(item => <tr key={`${item.entity_type}-${item.entity_id}`} className="border-t align-top"><td className="px-4 py-3"><div className="font-medium text-slate-900">{item.name}</div><div className="mt-1 font-mono text-xs text-slate-400">{item.entity_type} · {item.entity_id}</div>{item.metadata.drama_title ? <div className="mt-1 text-xs text-slate-500">剧目：{String(item.metadata.drama_title)}</div> : null}</td><td className="px-4 py-3"><StatusBadge status={item.status} label={item.status_label} /></td><td className="max-w-md px-4 py-3">{item.reasons.length ? <ul className="space-y-1">{item.reasons.map((reason, index) => <li key={`${reason.code}-${index}`}><span className="font-mono text-xs text-slate-500">{reason.code}</span><span className="ml-2 text-slate-700">{reason.message}</span></li>)}</ul> : <span className="text-slate-400">无</span>}</td><td className="whitespace-nowrap px-4 py-3 text-xs text-slate-600">{formatTime(item.last_changed_at)}</td><td className="px-4 py-3"><Link to={item.trace_url} className="text-blue-600 hover:underline">查看来源</Link></td></tr>)}</tbody></table></div>
        {!data.data.length && <div className="border-t p-10 text-center text-sm text-slate-500">当前筛选条件下没有记录；这不代表成功或数值为 0。</div>}
        <div className="flex items-center justify-between border-t px-4 py-3 text-sm text-slate-600"><span>共 {data.total} 项 · 第 {data.page}/{pageCount} 页</span><div className="flex gap-2"><button onClick={() => setPage(value => Math.max(1, value - 1))} disabled={page <= 1} className="rounded border px-3 py-1 disabled:opacity-40">上一页</button><button onClick={() => setPage(value => Math.min(pageCount, value + 1))} disabled={page >= pageCount} className="rounded border px-3 py-1 disabled:opacity-40">下一页</button></div></div>
      </section>
    </>}
  </div>
}
