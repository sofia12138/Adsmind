import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useAuth } from '@/contexts/AuthContext'
import { checkLaunchDraft, executeLaunchDraft, saveLaunchDraft, type LaunchDraft, type LaunchResponse, type Precheck } from '@/services/launch-drafts'

export function useLaunchDraft() {
  const client = useQueryClient()
  const { currentApplication, username } = useAuth()
  const [review, setReview] = useState<{ draft: LaunchDraft; precheck: Precheck } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const resolve = useRef<((response: LaunchResponse) => void) | null>(null)
  useEffect(() => () => { resolve.current?.({ error: '草稿已保存，创建确认已关闭', draft_saved: true }) }, [])
  async function launch(payload: Record<string, unknown>): Promise<LaunchResponse> {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(payload)))
    const hash = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('')
    const storageKey = `launch-draft:${username}:${currentApplication?.id}:${hash}`
    const requestKey = sessionStorage.getItem(storageKey) ?? crypto.randomUUID()
    sessionStorage.setItem(storageKey, requestKey)
    const saved = await saveLaunchDraft(payload, requestKey)
    void client.invalidateQueries({ queryKey: ['launch-drafts'] })
    return openReview(saved)
  }
  async function resume(draft: LaunchDraft): Promise<LaunchResponse> {
    return openReview(await checkLaunchDraft(draft.id))
  }
  function openReview(saved: { data: LaunchDraft; precheck: Precheck }): Promise<LaunchResponse> {
    if (saved.data.status === 'SUCCEEDED') return Promise.resolve(saved.data.result ?? { error: '请到广告草稿查看已完成的结果' })
    setError('')
    setReview({ draft: saved.data, precheck: saved.precheck })
    return new Promise<LaunchResponse>(done => { resolve.current = done })
  }
  function finish(response: LaunchResponse) {
    resolve.current?.(response)
    resolve.current = null
    setReview(null)
  }
  async function execute() {
    if (!review) return
    setBusy(true)
    setError('')
    try {
      const draft = await executeLaunchDraft(review.draft)
      void client.invalidateQueries({ queryKey: ['launch-drafts'] })
      if (draft.status === 'UNKNOWN' || draft.status === 'RUNNING') {
        finish({ ...draft.result, error: '平台创建结果尚未确认，请先在平台核对，勿重复创建' })
      } else finish(draft.result ?? { error: draft.last_error || '创建未完成，请到广告草稿查看结果' })
    } catch (e) {
      setError(e instanceof Error ? e.message : '创建失败，请查看草稿记录')
    } finally { setBusy(false) }
  }
  const dialog = review ? <div className="fixed inset-0 z-[100] bg-black/40 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-labelledby="launch-review-title">
    <div className="bg-white rounded-xl p-6 w-full max-w-xl max-h-[85vh] overflow-auto space-y-4">
      <h2 id="launch-review-title" className="font-semibold text-lg">确认创建 · {review.draft.name}</h2>
      <p className="text-sm text-gray-600">已保存模板「{review.draft.template_name || '投放模板'}」与本次配置。平台：{review.draft.platform === 'meta' ? 'Meta' : 'TikTok'} · 账户：{String(review.draft.payload.ad_account_id || review.draft.payload.advertiser_id || '尚未选择')}</p>
      <p className="text-sm text-gray-600">基础日预算：{String(review.draft.payload.budget ?? '—')} {String(review.draft.payload.budget_currency || '币种待确认')} · 素材：{Array.isArray(review.draft.payload.materials) ? review.draft.payload.materials.length : review.draft.payload.video_id ? 1 : '按模板配置'} 条</p>
      <div className="space-y-1 text-sm">{review.precheck.checks.map(check => <p key={check.code} className={check.ok ? 'text-green-700' : 'text-red-600'}>{check.ok ? '✓' : '×'} {check.message}</p>)}</div>
      {review.precheck.checks.some(check => !check.ok && ['account', 'account_status', 'application_scope', 'assigned_account'].includes(check.code)) && <Link to="/data-source" onClick={event => { if (busy) event.preventDefault(); else finish({ error: '草稿已保存，请先处理广告账户', draft_saved: true }) }} className="inline-block text-sm text-blue-600 underline">前往数据源配置处理账户</Link>}
      <p className="text-xs text-gray-500">{review.precheck.notice}</p>
      <p className="text-xs text-gray-500">创建状态沿用所选模板；确认后会调用广告平台。已经成功的步骤会复用返回结果。</p>
      {['UNKNOWN', 'RUNNING'].includes(review.draft.status) && <p role="alert" className="text-sm text-amber-700">已有创建正在执行或结果尚未确认，请先在平台核对，勿重复创建。</p>}
      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
      <div className="flex flex-wrap justify-end gap-3">
        <Link to="/ads/drafts" onClick={event => { if (busy) event.preventDefault(); else finish({ error: '草稿已保存', draft_saved: true }) }} className="text-sm text-blue-600">查看草稿</Link>
        <button type="button" disabled={busy} onClick={() => finish({ error: '草稿已保存，可在广告草稿中继续', draft_saved: true })} className="px-3 py-2 text-sm border rounded-lg disabled:opacity-40">仅保存草稿</button>
        <button type="button" disabled={busy || !review.precheck.ok || ['UNKNOWN', 'RUNNING'].includes(review.draft.status)} onClick={() => void execute()} className="px-3 py-2 text-sm bg-blue-600 text-white rounded-lg disabled:opacity-40">{busy ? '正在创建…' : review.draft.status === 'PARTIAL' || review.draft.status === 'FAILED' ? '继续未完成的步骤' : '确认创建广告'}</button>
      </div>
    </div>
  </div> : null
  return { launch, resume, dialog }
}
