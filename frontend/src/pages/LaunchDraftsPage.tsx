import DraftEditDialog from '@/components/ads-create/DraftEditDialog'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@/contexts/AuthContext'
import { useLaunchDraft } from '@/components/ads-create/useLaunchDraft'
import { DRAFT_STATUS_LABEL, listLaunchDrafts, type LaunchDraft } from '@/services/launch-drafts'

function creationSteps(value: unknown, label = ''): { label: string; success: boolean; id?: string; error?: string }[] {
  if (!value || typeof value !== 'object') return []
  if (Array.isArray(value)) return value.flatMap((item, index) => creationSteps(item, `${label} ${index+1}`))
  const row = value as Record<string, unknown>
  const own = typeof row.success === 'boolean' ? [{
    label: String(row.adset_name || row.ad_name || label || '创建步骤'), success: row.success,
    id: [row.campaign_id, row.adset_id, row.adgroup_id, row.ad_id].find(v => typeof v === 'string') as string | undefined,
    error: typeof row.error === 'string' ? row.error : undefined,
  }] : []
  const labels: Record<string, string> = { campaign: '广告系列', adgroup: '广告组', adsets: '广告组', ads: '广告', ad: '广告' }
  const children = Object.entries(row).filter(([key]) => key === 'data' || key in labels).flatMap(([key, child]) => creationSteps(child, labels[key] || label))
  return [...own, ...children]
}

export default function LaunchDraftsPage() {
  const { currentApplication, username } = useAuth()
  const [page, setPage] = useState(1)
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState('')
  const [editing, setEditing] = useState<LaunchDraft | null>(null)
  const { resume, dialog } = useLaunchDraft()
  const query = useQuery({ queryKey: ['launch-drafts', username, currentApplication?.id, page], queryFn: () => listLaunchDrafts(page), refetchInterval: busy ? 3000 : false })
  return <div className="max-w-5xl mx-auto space-y-5">
    {dialog}
    {editing && <DraftEditDialog key={editing.id} draft={editing} close={() => setEditing(null)} saved={() => { setEditing(null); setMessage('草稿已更新，创建前会重新检查'); void query.refetch() }} />}
    <div className="flex justify-between items-center"><div><h1 className="text-xl font-semibold">广告草稿</h1><p className="text-sm text-gray-500 mt-1">当前应用下由我保存的广告配置、创建进度和执行结果</p></div><Link to="/ads/create" className="text-sm text-blue-600">新建广告</Link></div>
    {message && <p role="status" className="text-sm text-gray-700">{message}</p>}
    {query.isLoading && <p className="text-sm text-gray-500">正在加载草稿…</p>}
    {query.error && <div role="alert" className="text-red-600 text-sm">{query.error.message}<button onClick={() => void query.refetch()} className="ml-3 underline">重试</button></div>}
    {query.data?.total === 0 && <div className="bg-white border rounded-xl p-8 text-center text-gray-500">暂无广告草稿。新建广告时会先保存配置，再检查创建条件。</div>}
    {query.data?.list.map(draft => <article key={draft.id} className="bg-white border rounded-xl p-5 space-y-3">
      <div className="flex justify-between gap-3"><h2 className="font-medium">{draft.name}</h2><span className={`text-sm ${draft.status === 'SUCCEEDED' ? 'text-green-700' : draft.status === 'UNKNOWN' ? 'text-amber-700' : 'text-gray-500'}`}>{DRAFT_STATUS_LABEL[draft.status]}</span></div>
      <p className="text-xs text-gray-500">{draft.platform === 'meta' ? 'Meta' : 'TikTok'} · 账户 {String(draft.payload.ad_account_id || draft.payload.advertiser_id || '尚未选择')} · 保存于 {draft.created_at}</p>
      {draft.status === 'DRAFT' && <button disabled={busy !== null} onClick={() => setEditing(draft)} className="text-sm text-blue-600 disabled:opacity-40">编辑名称和预算</button>}
      {draft.last_error && <p className="text-sm text-amber-700">{draft.last_error}</p>}
      {draft.status === 'UNKNOWN' || draft.status === 'RUNNING' ? <p className="text-sm text-amber-700">系统不会重复执行未确认的写入。请先核对平台中的广告和创建编号。</p> : draft.status !== 'SUCCEEDED' && <button disabled={busy !== null} className="text-sm px-3 py-1.5 border rounded-lg text-blue-600 disabled:opacity-40" onClick={async () => {
        setBusy(draft.id); setMessage('')
        try { const result = await resume(draft); setMessage(result.error || '执行结束，请查看草稿结果'); void query.refetch() }
        catch (e) { setMessage(e instanceof Error ? e.message : '操作失败') }
        finally { setBusy(null) }
      }}>{busy === draft.id ? '处理中…' : draft.status === 'DRAFT' ? '检查并创建' : '检查并继续未完成步骤'}</button>}
      <details className="text-xs text-gray-500"><summary className="cursor-pointer">配置和步骤结果</summary>
        <div className="mt-3 space-y-2">
          <p>模板：{draft.template_name || '投放模板'} · 基础日预算：{String(draft.payload.budget ?? '—')} {String(draft.payload.budget_currency || '币种待确认')}</p>
          <p>素材数：{Array.isArray(draft.payload.materials) ? draft.payload.materials.length : draft.payload.video_id ? 1 : '按模板配置'}</p>
          {creationSteps(draft.result).map((step, index) => <p key={index} className={step.success ? 'text-green-700' : 'text-red-600'}>{step.success ? '✓' : '×'} {step.label}{step.id ? ` · 平台编号 ${step.id}` : ''}{step.error ? ` · ${step.error}` : ''}</p>)}
          {!draft.result && <p>尚未执行平台创建。</p>}
        </div>
      </details>
    </article>)}
    {query.data && query.data.total > 20 && <div className="flex justify-end gap-3 text-sm"><button disabled={page === 1} onClick={() => setPage(page-1)}>上一页</button><span>第 {page} 页</span><button disabled={page*20 >= query.data.total} onClick={() => setPage(page+1)}>下一页</button></div>}
  </div>
}
