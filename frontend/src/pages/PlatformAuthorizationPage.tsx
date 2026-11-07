import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getPlatformAuthorization, finishPlatformAuthorization, type AuthorizationPlatform } from '@/services/integrations'
import { useAuth } from '@/contexts/AuthContext'

export default function PlatformAuthorizationPage({ platform }: { platform: AuthorizationPlatform }) {
  const label = platform === 'tiktok' ? 'TikTok' : 'Meta'
  const [params] = useSearchParams()
  const sid = params.get('session_id') ?? ''
  const { currentApplication, tenant } = useAuth()
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)
  const details = useQuery({
    queryKey: ['platform-authorization', tenant.id, platform, sid, currentApplication?.id],
    queryFn: () => getPlatformAuthorization(platform, sid, currentApplication!.id),
    enabled: !!sid && !!currentApplication && !done && params.get('result') !== 'failed',
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    gcTime: 0,
  })

  async function save() {
    if (busy || !currentApplication || !details.data || details.data.application_id !== currentApplication.id) return
    if (!details.data.accounts.some(account => account.account_id === selected)) return
    setBusy(true); setError('')
    try {
      await finishPlatformAuthorization(platform, sid, selected, currentApplication.id)
      setDone(true)
      queryClient.removeQueries({ queryKey: ['platform-authorization', tenant.id, platform, sid] })
      window.history.replaceState(null, '', `/settings/integrations/${platform}/complete`)
      for (const key of ['integrations-overview', 'integrations-credentials', 'ad-accounts', 'application-accounts', 'available-accounts', 'biz', 'quota']) {
        void queryClient.invalidateQueries({ queryKey: [key] })
      }
    } catch (e) { setError(e instanceof Error ? e.message : '账号连接失败，请重试') }
    finally { setBusy(false) }
  }

  const mismatch = !!details.data && details.data.application_id !== currentApplication?.id
  const failure = params.get('result') === 'failed' || !sid || mismatch
  const accounts = mismatch ? [] : details.data?.accounts ?? []
  return <section className="max-w-2xl mx-auto bg-white border rounded-2xl p-6 space-y-5">
    <h1 className="text-xl font-semibold">{done ? `${label} 账号已连接` : `选择 ${label} 广告账号`}</h1>
    {done ? <><p>连接已保存。下一步同步投放数据。</p><div className="flex gap-4"><Link className="text-blue-600" to="/data-source">前往数据源配置 →</Link><Link className="text-blue-600" to="/settings/integrations">返回集成中心</Link></div></> : <>
      <p className="text-sm text-gray-500">连接到「{tenant.name} / {currentApplication?.name ?? '加载中…'}」。授权凭证由服务端加密保存。</p>
      {failure || details.error ? <><p role="alert" className="text-red-600">{mismatch ? '当前应用与发起授权时不一致，请切回原应用或重新连接。' : details.error?.message ?? '授权未完成或已取消，请重新连接。'}</p><Link to="/settings/integrations" className="text-blue-600">返回集成中心重新连接</Link></> : <>
        {details.isPending ? <p>正在读取授权账号…</p> : accounts.map(account => <label key={account.account_id} className="flex gap-3 border rounded-lg p-3 cursor-pointer">
          <input type="radio" name="advertiser" value={account.account_id} checked={selected === account.account_id} disabled={busy} onChange={() => setSelected(account.account_id)} />
          <span><span className="block font-medium">{account.account_name}</span><span className="text-xs text-gray-500">{account.account_id} · {account.currency} · {account.timezone}</span></span>
        </label>)}
        {details.isSuccess && accounts.length === 0 && <p role="status">本次授权没有可连接的广告账号，请返回集成中心重新连接。</p>}
        {error && <p role="alert" className="text-red-600">{error}</p>}
        <button disabled={!accounts.some(account => account.account_id === selected) || busy} onClick={save} className="bg-blue-600 text-white px-5 py-2 rounded-lg disabled:opacity-50">{busy ? '连接中…' : '连接所选账号'}</button>
        <Link to="/settings/integrations" className="block text-sm text-blue-600">返回集成中心</Link>
      </>}
    </>}
  </section>
}
