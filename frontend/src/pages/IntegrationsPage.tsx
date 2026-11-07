import { useMemo, useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import {
  Link2, CheckCircle2, AlertTriangle, XCircle, Loader2,
  PlayCircle, Trash2, ShieldOff,
} from 'lucide-react'

import { SectionCard } from '@/components/common/SectionCard'
import {
  getIntegrationOverview,
  listCredentials,
  startOAuth,
  revokeCredential,
  type IntegrationOverviewItem,
  type CredentialItem,
  type AuthorizationPlatform,
} from '@/services/integrations'
import { useAuth } from '@/contexts/AuthContext'
import { cn } from '@/utils/cn'

const PLATFORM_LABEL: Record<string, string> = {
  tiktok: 'TikTok Ads',
  meta: 'Meta Ads (Facebook / Instagram)',
}

function fmtDate(s?: string | null): string {
  if (!s) return '—'
  return s.replace('T', ' ').slice(0, 16)
}

export default function IntegrationsPage() {
  const { currentApplication: application, tenant, role } = useAuth()
  const canAuthorize = role === 'admin' || role === 'super_admin'
  const [busy, setBusy] = useState<string | null>(null)
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)

  const overview = useQuery({
    queryKey: ['integrations-overview', tenant.id, application?.id],
    queryFn: getIntegrationOverview,
  })

  const creds = useQuery({
    queryKey: ['integrations-credentials', tenant.id, application?.id],
    queryFn: () => listCredentials(),
  })

  const revoke = useMutation({
    mutationFn: ({ platform, externalId }: { platform: string; externalId: string }) =>
      revokeCredential(platform, externalId),
    onSuccess: () => {
      setMsg({ kind: 'ok', text: '已撤销该凭证' })
      creds.refetch()
      overview.refetch()
    },
    onError: (e: any) => {
      setMsg({ kind: 'err', text: e?.message || '撤销失败' })
    },
  })

  const credsByPlatform = useMemo(() => {
    const m: Record<string, CredentialItem[]> = {}
    for (const c of creds.data?.items ?? []) {
      m[c.platform] = m[c.platform] || []
      m[c.platform].push(c)
    }
    return m
  }, [creds.data])

  async function handleAuthorize(platform: string) {
    if (busy || !canAuthorize) return
    if (platform !== 'tiktok' && platform !== 'meta') return
    if (!application?.id) {
      setMsg({ kind: 'err', text: '请先选择一个应用再授权' })
      return
    }
    setBusy(platform)
    setMsg(null)
    try {
      const res = await startOAuth(platform as AuthorizationPlatform, application.id)
      if (res.mock_mode || !res.authorize_url) throw new Error('官方授权连接不可用，请联系系统管理员')
      window.location.assign(res.authorize_url)
    } catch (e: unknown) {
      setMsg({ kind: 'err', text: e instanceof Error ? e.message : '授权失败' })
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="p-6 space-y-6 max-w-6xl mx-auto">
      <header className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Link2 className="w-5 h-5 text-blue-600" />
            集成中心
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            在 TikTok / Meta 官方页面授权，无需填写 Token。返回后选择连接到当前应用的账号。
          </p>
        </div>
        {application && (
          <div className="text-xs text-gray-500">
            当前应用：
            <span className="ml-1 text-gray-800 font-medium">{application.name}</span>
          </div>
        )}
      </header>

      {!canAuthorize && <p className="text-sm text-amber-700" role="status">请联系管理员连接广告平台。</p>}
      {!application && <p className="text-sm text-amber-700" role="status">请先选择一个应用，再连接广告平台。</p>}

      {msg && (
        <div
          className={cn(
            'text-sm rounded-lg px-4 py-2 flex items-center gap-2',
            msg.kind === 'ok'
              ? 'bg-green-50 text-green-700 border border-green-200'
              : 'bg-red-50 text-red-700 border border-red-200',
          )}
        >
          {msg.kind === 'ok' ? <CheckCircle2 className="w-4 h-4" /> : <AlertTriangle className="w-4 h-4" />}
          {msg.text}
        </div>
      )}

      <SectionCard title="平台授权状态">
        {overview.isLoading && (
          <div className="flex items-center gap-2 text-sm text-gray-500 py-6 justify-center">
            <Loader2 className="w-4 h-4 animate-spin" />
            加载中…
          </div>
        )}
        {overview.isError && (
          <div className="text-sm text-red-600 py-6 text-center">
            加载失败
            <button onClick={() => overview.refetch()} className="ml-2 underline">
              重试
            </button>
          </div>
        )}
        {overview.data && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {overview.data.items.map(item => (
              <PlatformCard
                key={item.platform}
                item={item}
                busyKey={busy}
                canAuthorize={canAuthorize && !!application}
                onAuthorize={() => handleAuthorize(item.platform)}
              />
            ))}
          </div>
        )}
      </SectionCard>

      <SectionCard title={`已授权凭证（${creds.data?.items?.length ?? 0}）`} noPadding>
        {creds.isLoading && (
          <div className="flex items-center gap-2 text-sm text-gray-500 py-10 justify-center">
            <Loader2 className="w-4 h-4 animate-spin" />
            加载中…
          </div>
        )}
        {creds.isError && (
          <div className="text-sm text-red-600 py-10 text-center">加载失败</div>
        )}
        {creds.isSuccess && creds.data.items.length === 0 && (
          <div className="text-sm text-gray-400 py-12 text-center">
            还没有任何凭证。在上方点击"授权"按钮开始接入广告账号。
          </div>
        )}
        {!creds.isLoading && (creds.data?.items?.length ?? 0) > 0 && (
          <table className="w-full text-sm">
            <thead className="bg-gray-50/60">
              <tr className="text-left text-xs text-gray-500">
                <th className="px-5 py-3 font-medium">平台</th>
                <th className="px-3 py-3 font-medium">外部账号 ID</th>
                <th className="px-3 py-3 font-medium">Scopes</th>
                <th className="px-3 py-3 font-medium">过期时间</th>
                <th className="px-3 py-3 font-medium text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {Object.keys(credsByPlatform).sort().flatMap(p =>
                credsByPlatform[p].map(c => (
                  <CredentialRow
                    key={c.id}
                    cred={c}
                    onRevoke={() =>
                      revoke.mutate({ platform: c.platform, externalId: c.external_id })
                    }
                    revoking={revoke.isPending}
                  />
                )),
              )}
            </tbody>
          </table>
        )}
      </SectionCard>
    </div>
  )
}

function PlatformCard({
  item, busyKey, canAuthorize, onAuthorize,
}: {
  item: IntegrationOverviewItem
  busyKey: string | null
  canAuthorize: boolean
  onAuthorize: () => void
}) {
  const realBusy = busyKey === item.platform
  const total = item.credentials.total
  const stateBadge = (() => {
    if (total === 0) {
      return { cls: 'bg-gray-100 text-gray-500', label: '尚未授权', Icon: ShieldOff }
    }
    if (item.credentials.expired > 0) {
      return {
        cls: 'bg-red-50 text-red-600',
        label: `${item.credentials.expired} 个已过期`,
        Icon: XCircle,
      }
    }
    if (item.credentials.expiring > 0) {
      return {
        cls: 'bg-amber-50 text-amber-600',
        label: `${item.credentials.expiring} 个 14 天内到期`,
        Icon: AlertTriangle,
      }
    }
    return {
      cls: 'bg-green-50 text-green-600',
      label: `${item.credentials.valid} 个有效`,
      Icon: CheckCircle2,
    }
  })()
  const StateIcon = stateBadge.Icon

  return (
    <div className="rounded-xl border border-gray-100 p-4 hover:border-blue-200 transition-colors">
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="text-base font-semibold text-gray-900">
            {PLATFORM_LABEL[item.platform] ?? item.platform.toUpperCase()}
          </div>
          <div className="text-xs text-gray-500 mt-1">
            {item.configured ? (
              <span className="text-green-600">已开通官方授权连接</span>
            ) : (
              <span className="text-amber-600">授权连接尚未开通，请联系系统管理员</span>
            )}
          </div>
        </div>
        <span
          className={cn(
            'inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full whitespace-nowrap',
            stateBadge.cls,
          )}
        >
          <StateIcon className="w-3 h-3" />
          {stateBadge.label}
        </span>
      </div>

      <div className="flex items-center gap-2">
        {(item.platform === 'tiktok' || item.platform === 'meta') ? (
          <button
            onClick={() => onAuthorize()}
            disabled={busyKey !== null || !item.configured || !canAuthorize}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
          >
            {realBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <PlayCircle className="w-4 h-4" />}
            {item.platform === 'tiktok' ? '连接 TikTok' : '连接 Meta'}
          </button>
        ) : null}
      </div>
    </div>
  )
}

function CredentialRow({
  cred, onRevoke, revoking,
}: {
  cred: CredentialItem
  onRevoke: () => void
  revoking: boolean
}) {
  return (
    <tr className="border-t border-gray-100 hover:bg-blue-50/30">
      <td className="px-5 py-3 text-gray-900 font-medium">{PLATFORM_LABEL[cred.platform] ?? cred.platform}</td>
      <td className="px-3 py-3 text-gray-700 font-mono text-xs">{cred.external_id}</td>
      <td className="px-3 py-3 text-gray-500 text-xs">
        {(cred.scopes && cred.scopes.length > 0) ? cred.scopes.join(', ') : '—'}
      </td>
      <td className="px-3 py-3 text-gray-500 text-xs">{fmtDate(cred.expires_at)}</td>
      <td className="px-3 py-3 text-right">
        <button
          onClick={() => {
            if (confirm(`确定撤销 ${cred.platform} / ${cred.external_id} 的授权吗？`)) onRevoke()
          }}
          disabled={revoking}
          className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-red-600 disabled:opacity-50"
        >
          <Trash2 className="w-3.5 h-3.5" />
          撤销
        </button>
      </td>
    </tr>
  )
}
