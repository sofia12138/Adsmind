import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchAdAccounts } from '@/services/accounts-mgmt'
import { updateLaunchDraft, type LaunchDraft } from '@/services/launch-drafts'

export default function DraftEditDialog({ draft, close, saved }: { draft: LaunchDraft; close: () => void; saved: () => void }) {
  const [name, setName] = useState(String(draft.payload.campaign_name || ''))
  const [budget, setBudget] = useState(String(draft.payload.budget || ''))
  const overrides = draft.payload.overrides as { campaign?: { daily_budget?: number } } | undefined
  const adsets = draft.payload.adsets as { name?: string; daily_budget?: number }[] | undefined
  const isAbo = draft.platform === 'meta' && draft.budget_mode !== 'CBO' && !overrides?.campaign?.daily_budget && Array.isArray(adsets)
  const [budgets, setBudgets] = useState(isAbo ? adsets.map(a => String((a.daily_budget || 0)/100)) : [])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const accounts = useQuery({ queryKey: ['draft-edit-accounts', draft.id], queryFn: () => fetchAdAccounts(draft.platform) })
  const aid = String(draft.payload.ad_account_id || draft.payload.advertiser_id || '')
  const currency = accounts.data?.data.find(account => account.account_id === aid)?.currency
  const inputClass = 'block w-full border rounded p-2 mt-1'
  return <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-labelledby="edit-draft-title">
    <form className="bg-white p-6 rounded-xl w-full max-w-lg space-y-4 max-h-[85vh] overflow-auto" onSubmit={async event => {
      event.preventDefault(); setBusy(true); setError('')
      try { await updateLaunchDraft(draft, { campaign_name: name, budget: budgets[0] || budget, adset_budgets: budgets }); saved() }
      catch (error) { setError(error instanceof Error ? error.message : '保存失败') }
      finally { setBusy(false) }
    }}>
      <h2 id="edit-draft-title" className="font-semibold">编辑广告草稿</h2>
      <p className="text-sm text-gray-500">账户币种：{currency || '待确认'}。金额不换算汇率，素材、定向与模板配置保留。</p>
      {accounts.error && <p role="alert" className="text-red-600 text-sm">{accounts.error.message}<button type="button" onClick={() => void accounts.refetch()} className="ml-2 underline">重试</button></p>}
      <label className="block text-sm">广告系列名称<input required maxLength={255} value={name} disabled={busy} onChange={e => setName(e.target.value)} className={inputClass} /></label>
      {budgets.length === 0 ? <label className="block text-sm">日预算（{currency || '待确认'}）<input required type="number" min="0.01" step="0.01" value={budget} disabled={busy} onChange={e => setBudget(e.target.value)} className={inputClass} /></label> : budgets.map((value, index) => <label key={index} className="block text-sm">{adsets?.[index].name || `广告组 ${index+1}`} 日预算（{currency || '待确认'}）<input required type="number" min="0.01" step="0.01" value={value} disabled={busy} onChange={e => setBudgets(values => values.map((old, i) => i === index ? e.target.value : old))} className={inputClass} /></label>)}
      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
      <div className="flex justify-end gap-3"><button type="button" disabled={busy} onClick={close}>取消</button><button disabled={busy || !currency} className="bg-blue-600 text-white rounded px-3 py-2 disabled:opacity-40">{busy ? '保存中…' : '确认币种并保存'}</button></div>
    </form>
  </div>
}
