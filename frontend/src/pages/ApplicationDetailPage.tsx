/**
 * ApplicationDetailPage — 应用详情（阶段 4 X1 骨架）
 *
 * Tabs：
 *   - overview     基本信息（已实现）
 *   - accounts     广告账号绑定（X3 占位）
 *   - attribution  归因 / 回传配置（X4 占位）
 *   - members      成员权限（X5 占位）
 */
import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Loader2, AlertCircle, ArrowLeft, Layers, Settings as SettingsIcon,
  Users as UsersIcon, Link2, GitMerge, Plus, Unlink, ExternalLink,
} from 'lucide-react'
import { PageHeader } from '@/components/common/PageHeader'
import { SectionCard } from '@/components/common/SectionCard'
import {
  getApplication, type Application, updateApplication,
  listApplicationAdAccounts, listAvailableAdAccounts,
  bindAdAccount, unbindAdAccount, type AdAccountRow,
  listMembers, addMember, removeMember, updateMemberRole,
  type ApplicationMember,
} from '@/services/application'
import { fetchUsers, type UserInfo } from '@/services/users'
import { useAuth } from '@/contexts/AuthContext'
import { QuotaExceededError } from '@/services/api'
import { startOAuth, openOAuthWindow } from '@/services/integrations'
import { cn } from '@/utils/cn'

const PLATFORM_LABEL: Record<string, string> = {
  ios: 'iOS',
  android: 'Android',
  web: 'Web',
  mini_program: '小程序',
  multi: '全平台',
}

type TabKey = 'overview' | 'accounts' | 'attribution' | 'members'

const TABS: { key: TabKey; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { key: 'overview',    label: '基本信息',   icon: SettingsIcon },
  { key: 'accounts',    label: '广告账号',   icon: Link2 },
  { key: 'attribution', label: '归因 / 回传', icon: GitMerge },
  { key: 'members',     label: '成员权限',   icon: UsersIcon },
]

export default function ApplicationDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { switchApplication, currentApplication } = useAuth()
  const [tab, setTab] = useState<TabKey>('overview')

  const appId = Number(id)
  const { data: app, isLoading, isError } = useQuery({
    queryKey: ['application', appId],
    queryFn: () => getApplication(appId),
    enabled: Number.isFinite(appId) && appId > 0,
  })

  if (isLoading) {
    return (
      <div className="p-6 flex items-center justify-center text-gray-400 text-sm">
        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
        加载中…
      </div>
    )
  }

  if (isError || !app) {
    return (
      <div className="p-6 flex flex-col items-center justify-center py-20 text-sm text-red-500">
        <AlertCircle className="w-6 h-6 mb-2" />
        加载应用失败或应用不存在
        <button onClick={() => navigate('/applications')} className="mt-3 text-blue-600 underline">
          返回应用列表
        </button>
      </div>
    )
  }

  const isCurrent = currentApplication?.id === app.id

  return (
    <div className="p-6">
      <button
        onClick={() => navigate('/applications')}
        className="flex items-center gap-1 text-sm text-gray-500 hover:text-blue-600 mb-3"
      >
        <ArrowLeft className="w-3.5 h-3.5" />
        应用列表
      </button>

      <PageHeader
        title={
          <span className="flex items-center gap-2">
            <Layers className="w-5 h-5 text-blue-500" />
            {app.name}
            {app.is_default && <span className="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-600">默认应用</span>}
          </span>
        }
        description={app.description || `slug: ${app.slug}`}
        action={
          !isCurrent && (
            <button
              onClick={() => switchApplication(app.id)}
              className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700"
            >
              切换到此应用
            </button>
          )
        }
      />

      {/* Tabs */}
      <div className="flex items-center gap-1 border-b border-gray-200 mb-5">
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={cn(
              'flex items-center gap-1.5 px-4 py-2.5 text-sm border-b-2 -mb-px transition-colors',
              tab === t.key
                ? 'border-blue-500 text-blue-600 font-medium'
                : 'border-transparent text-gray-500 hover:text-gray-800',
            )}
          >
            <t.icon className="w-3.5 h-3.5" />
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'overview' && <OverviewTab app={app} />}
      {tab === 'accounts' && <AccountsTab app={app} />}
      {tab === 'attribution' && <AttributionTab app={app} />}
      {tab === 'members' && <MembersTab app={app} />}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// 成员权限 tab（X5）
// ─────────────────────────────────────────────────────────────

const ROLE_LABEL: Record<ApplicationMember['role'], string> = {
  owner: 'Owner（拥有者）',
  admin: 'Admin（管理员）',
  editor: 'Editor（编辑）',
  viewer: 'Viewer（只读）',
}

const ROLE_COLOR: Record<ApplicationMember['role'], string> = {
  owner: 'bg-purple-100 text-purple-700',
  admin: 'bg-blue-100 text-blue-700',
  editor: 'bg-green-100 text-green-700',
  viewer: 'bg-gray-100 text-gray-600',
}

function MembersTab({ app }: { app: Application }) {
  const queryClient = useQueryClient()
  const [adding, setAdding] = useState(false)

  const members = useQuery({
    queryKey: ['application-members', app.id],
    queryFn: () => listMembers(app.id),
  })

  const addMut = useMutation({
    mutationFn: ({ userId, role }: { userId: number; role: ApplicationMember['role'] }) =>
      addMember(app.id, userId, role),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['application-members', app.id] })
      setAdding(false)
    },
    onError: (e: Error) => alert(e.message || '添加失败'),
  })

  const updateMut = useMutation({
    mutationFn: ({ userId, role }: { userId: number; role: ApplicationMember['role'] }) =>
      updateMemberRole(app.id, userId, role),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['application-members', app.id] }),
  })

  const removeMut = useMutation({
    mutationFn: (userId: number) => removeMember(app.id, userId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['application-members', app.id] }),
  })

  return (
    <div className="space-y-5">
      <SectionCard
        title={`应用成员（${members.data?.length ?? 0}）`}
        extra={
          <button
            onClick={() => setAdding(true)}
            className="flex items-center gap-1 px-2.5 py-1 text-xs bg-blue-600 text-white rounded hover:bg-blue-700"
          >
            <Plus className="w-3 h-3" />
            添加成员
          </button>
        }
        noPadding
      >
        {members.isLoading && (
          <div className="py-8 text-center text-sm text-gray-400">
            <Loader2 className="w-4 h-4 inline animate-spin mr-1" />
            加载中…
          </div>
        )}
        {!members.isLoading && (members.data ?? []).length === 0 && (
          <div className="py-10 text-center text-sm text-gray-400">
            尚未邀请任何成员。全局 admin / super_admin 始终可见此应用。
          </div>
        )}
        {!members.isLoading && (members.data ?? []).length > 0 && (
          <table className="w-full text-sm">
            <thead className="bg-gray-50/60">
              <tr className="text-left text-xs text-gray-500">
                <th className="px-5 py-2.5 font-medium">用户</th>
                <th className="px-3 py-2.5 font-medium">邮箱</th>
                <th className="px-3 py-2.5 font-medium">角色</th>
                <th className="px-3 py-2.5 font-medium">加入时间</th>
                <th className="px-3 py-2.5 font-medium text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {(members.data ?? []).map(m => (
                <tr key={m.user_id} className="border-t border-gray-100 hover:bg-blue-50/30">
                  <td className="px-5 py-2.5">
                    <div className="flex items-center gap-2">
                      <div className="w-7 h-7 rounded-full bg-gradient-to-br from-blue-400 to-purple-500 text-white text-xs font-medium flex items-center justify-center">
                        {(m.username || 'U')[0].toUpperCase()}
                      </div>
                      <span className="text-gray-800">{m.username || `#${m.user_id}`}</span>
                    </div>
                  </td>
                  <td className="px-3 py-2.5 text-gray-500 text-xs">{m.email || '—'}</td>
                  <td className="px-3 py-2.5">
                    <select
                      value={m.role}
                      onChange={e => updateMut.mutate({
                        userId: m.user_id,
                        role: e.target.value as ApplicationMember['role'],
                      })}
                      className={cn(
                        'text-xs px-2 py-0.5 rounded-full border-0 focus:ring-2 focus:ring-blue-100 focus:outline-none',
                        ROLE_COLOR[m.role],
                      )}
                    >
                      {(Object.keys(ROLE_LABEL) as ApplicationMember['role'][]).map(r => (
                        <option key={r} value={r}>{ROLE_LABEL[r]}</option>
                      ))}
                    </select>
                  </td>
                  <td className="px-3 py-2.5 text-gray-500 text-xs">{m.joined_at || '—'}</td>
                  <td className="px-3 py-2.5 text-right">
                    <button
                      onClick={() => {
                        if (confirm(`确定移除成员 ${m.username || `#${m.user_id}`} ?`)) {
                          removeMut.mutate(m.user_id)
                        }
                      }}
                      className="p-1.5 rounded text-gray-400 hover:bg-red-50 hover:text-red-600"
                      title="移除"
                    >
                      <Unlink className="w-3.5 h-3.5" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </SectionCard>

      {adding && (
        <MemberPicker
          existingUserIds={new Set((members.data ?? []).map(m => m.user_id))}
          onClose={() => setAdding(false)}
          onPick={(userId, role) => addMut.mutate({ userId, role })}
          pending={addMut.isPending}
        />
      )}
    </div>
  )
}

function MemberPicker({ existingUserIds, onClose, onPick, pending }: {
  existingUserIds: Set<number>;
  onClose: () => void;
  onPick: (userId: number, role: ApplicationMember['role']) => void;
  pending: boolean;
}) {
  const [role, setRole] = useState<ApplicationMember['role']>('editor')
  const users = useQuery({ queryKey: ['users-all'], queryFn: fetchUsers })

  const candidates = useMemo(() => {
    return (users.data ?? []).filter((u: UserInfo) => u.id && !existingUserIds.has(u.id))
  }, [users.data, existingUserIds])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={onClose}>
      <div
        className="bg-white rounded-xl shadow-xl w-full max-w-xl mx-4 overflow-hidden flex flex-col max-h-[80vh]"
        onClick={e => e.stopPropagation()}
      >
        <div className="px-6 py-4 border-b border-gray-100">
          <h3 className="text-lg font-semibold text-gray-800">添加应用成员</h3>
          <p className="text-xs text-gray-400 mt-1">从当前租户用户中选择一位加入应用，并设定角色。</p>
        </div>

        <div className="px-6 py-3 border-b border-gray-100 flex items-center gap-2">
          <span className="text-sm text-gray-600">默认角色</span>
          <select
            value={role}
            onChange={e => setRole(e.target.value as ApplicationMember['role'])}
            className="border border-gray-200 rounded px-2 py-1 text-sm focus:ring-2 focus:ring-blue-100 focus:outline-none"
          >
            {(Object.keys(ROLE_LABEL) as ApplicationMember['role'][]).map(r => (
              <option key={r} value={r}>{ROLE_LABEL[r]}</option>
            ))}
          </select>
        </div>

        <div className="flex-1 overflow-y-auto">
          {users.isLoading && (
            <div className="py-10 text-center text-sm text-gray-400">
              <Loader2 className="w-4 h-4 inline animate-spin mr-1" />
              加载中…
            </div>
          )}
          {!users.isLoading && candidates.length === 0 && (
            <div className="py-10 text-center text-sm text-gray-400">
              所有用户都已加入此应用。
            </div>
          )}
          {!users.isLoading && candidates.length > 0 && (
            <ul className="divide-y divide-gray-100">
              {candidates.map((u: UserInfo) => (
                <li key={u.id} className="px-6 py-2.5 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="w-7 h-7 rounded-full bg-slate-300 text-white text-xs font-medium flex items-center justify-center">
                      {u.username[0].toUpperCase()}
                    </div>
                    <div>
                      <div className="text-sm text-gray-800">{u.display_name || u.username}</div>
                      <div className="text-xs text-gray-400">{u.username} · 全局角色 {u.role}</div>
                    </div>
                  </div>
                  <button
                    onClick={() => u.id && onPick(u.id, role)}
                    disabled={pending}
                    className="px-2.5 py-1 text-xs bg-blue-600 text-white rounded hover:bg-blue-700 disabled:bg-gray-300"
                  >
                    添加
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="px-6 py-3 border-t border-gray-100 flex justify-end bg-gray-50">
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-md text-sm text-gray-600 hover:bg-gray-100"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// 归因 / 回传配置 tab（X4）
// ─────────────────────────────────────────────────────────────

interface AttributionSettings {
  provider?: 'metis' | 'appsflyer' | 'adjust' | 'custom'
  window_days?: number
  callback_url?: string
  sdk_key?: string
  events?: Array<{ platform_event: string; mapped_to: string }>
}

function AttributionTab({ app }: { app: Application }) {
  const queryClient = useQueryClient()
  const initialAttr = (app.settings?.attribution as AttributionSettings) || {}

  const [provider, setProvider] = useState<AttributionSettings['provider']>(
    initialAttr.provider ?? 'metis',
  )
  const [windowDays, setWindowDays] = useState<number>(initialAttr.window_days ?? 7)
  const [callbackUrl, setCallbackUrl] = useState(initialAttr.callback_url ?? '')
  const [sdkKey, setSdkKey] = useState(initialAttr.sdk_key ?? '')
  const [events, setEvents] = useState<NonNullable<AttributionSettings['events']>>(
    initialAttr.events ?? [{ platform_event: 'purchase', mapped_to: 'registration' }],
  )
  const [saved, setSaved] = useState(false)

  const mutation = useMutation({
    mutationFn: () => updateApplication(app.id, {
      settings: {
        ...(app.settings ?? {}),
        attribution: {
          provider,
          window_days: Number(windowDays),
          callback_url: callbackUrl.trim() || undefined,
          sdk_key: sdkKey.trim() || undefined,
          events: events.filter(e => e.platform_event && e.mapped_to),
        },
      },
    }),
    onSuccess: () => {
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
      queryClient.invalidateQueries({ queryKey: ['application', app.id] })
    },
  })

  function addEvent() {
    setEvents([...events, { platform_event: '', mapped_to: '' }])
  }
  function updateEvent(idx: number, key: 'platform_event' | 'mapped_to', val: string) {
    setEvents(events.map((e, i) => (i === idx ? { ...e, [key]: val } : e)))
  }
  function removeEvent(idx: number) {
    setEvents(events.filter((_, i) => i !== idx))
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
      <SectionCard title="归因服务">
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-600 mb-1">归因平台</label>
            <select
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-100 focus:outline-none"
              value={provider}
              onChange={e => setProvider(e.target.value as AttributionSettings['provider'])}
            >
              <option value="metis">Metis（自研）</option>
              <option value="appsflyer">AppsFlyer</option>
              <option value="adjust">Adjust</option>
              <option value="custom">自定义</option>
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-600 mb-1">归因窗口（天）</label>
            <input
              type="number"
              min={1}
              max={365}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-100 focus:outline-none"
              value={windowDays}
              onChange={e => setWindowDays(Number(e.target.value))}
            />
            <p className="text-xs text-gray-400 mt-1">广告点击后多少天内的安装/转化算归因。常见取值 1 / 7 / 30。</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-600 mb-1">SDK Key</label>
            <input
              type="text"
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-100 focus:outline-none"
              value={sdkKey}
              onChange={e => setSdkKey(e.target.value)}
              placeholder="客户端 SDK 初始化用的密钥"
            />
          </div>
        </div>
      </SectionCard>

      <SectionCard title="回传配置">
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-600 mb-1">服务端回传 URL</label>
            <input
              type="url"
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-100 focus:outline-none"
              value={callbackUrl}
              onChange={e => setCallbackUrl(e.target.value)}
              placeholder="https://your-attribution.com/callback"
            />
            <p className="text-xs text-gray-400 mt-1">转化事件会被 POST 到此 URL，用于回传到广告平台优化模型。</p>
          </div>
        </div>
      </SectionCard>

      <SectionCard title="转化事件映射" className="md:col-span-2"
        extra={
          <button onClick={addEvent} className="text-blue-600 hover:underline text-xs">
            + 添加一行
          </button>
        }
      >
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs text-gray-400 px-1">
            <div className="flex-1">广告平台事件</div>
            <div className="flex-1">映射到业务事件</div>
            <div className="w-7" />
          </div>
          {events.length === 0 && (
            <div className="text-sm text-gray-400 py-4 text-center">暂无事件映射</div>
          )}
          {events.map((ev, idx) => (
            <div key={idx} className="flex items-center gap-2">
              <input
                type="text"
                className="flex-1 border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:ring-2 focus:ring-blue-100 focus:outline-none"
                value={ev.platform_event}
                onChange={e => updateEvent(idx, 'platform_event', e.target.value)}
                placeholder="例如：tiktok.in_app_purchase"
              />
              <span className="text-gray-300">→</span>
              <input
                type="text"
                className="flex-1 border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:ring-2 focus:ring-blue-100 focus:outline-none"
                value={ev.mapped_to}
                onChange={e => updateEvent(idx, 'mapped_to', e.target.value)}
                placeholder="例如：purchase"
              />
              <button
                onClick={() => removeEvent(idx)}
                className="p-1.5 text-gray-400 hover:text-red-500"
                title="删除"
              >
                <Unlink className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      </SectionCard>

      <div className="md:col-span-2 flex items-center justify-end gap-3">
        {saved && <span className="text-sm text-green-600">配置已保存</span>}
        <button
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending}
          className="px-5 py-2 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700 disabled:bg-gray-300 flex items-center gap-1"
        >
          {mutation.isPending && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
          保存归因配置
        </button>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// 广告账号绑定 tab（X3）
// ─────────────────────────────────────────────────────────────

function AccountsTab({ app }: { app: Application }) {
  const queryClient = useQueryClient()
  const [picking, setPicking] = useState(false)
  const [oauthLoading, setOauthLoading] = useState<string | null>(null)

  async function connectPlatform(platform: 'tiktok' | 'meta') {
    setOauthLoading(platform)
    try {
      const start = await startOAuth(platform, app.id)
      await openOAuthWindow(start.authorize_url)
      queryClient.invalidateQueries({ queryKey: ['application-accounts'] })
      queryClient.invalidateQueries({ queryKey: ['quota', 'me'] })
      alert(start.mock_mode
        ? `${platform.toUpperCase()} 演示模式授权完成，已同步模拟账号到本应用`
        : `${platform.toUpperCase()} 授权完成，账号已同步`)
    } catch (e) {
      alert((e as Error).message || '授权失败')
    } finally {
      setOauthLoading(null)
    }
  }

  const bound = useQuery({
    queryKey: ['application-accounts', app.id],
    queryFn: () => listApplicationAdAccounts(app.id),
  })

  const bindMutation = useMutation({
    mutationFn: (rowId: number) => bindAdAccount(app.id, rowId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['application-accounts'] })
      queryClient.invalidateQueries({ queryKey: ['quota', 'me'] })
    },
    onError: (e: unknown) => {
      if (e instanceof QuotaExceededError) {
        alert(`${e.message}\n\n${e.upgradeHint ?? '请升级套餐解锁更多额度。'}`)
      } else {
        alert((e as Error)?.message || '绑定失败')
      }
    },
  })

  const unbindMutation = useMutation({
    mutationFn: (rowId: number) => unbindAdAccount(app.id, rowId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['application-accounts'] }),
  })

  return (
    <div className="space-y-5">
      <SectionCard title="平台授权（OAuth）">
        <p className="text-xs text-gray-500 mb-3">
          一键授权后自动同步广告账号到「{app.name}」。未配置真实平台凭证时将进入演示模式。
        </p>
        <div className="flex flex-wrap gap-2">
          {(['tiktok', 'meta'] as const).map(p => (
            <button
              key={p}
              type="button"
              disabled={!!oauthLoading}
              onClick={() => connectPlatform(p)}
              className="px-3 py-1.5 text-sm bg-gray-900 text-white rounded-md hover:bg-gray-800 disabled:opacity-50"
            >
              {oauthLoading === p ? '授权中…' : `授权 ${p.toUpperCase()}`}
            </button>
          ))}
        </div>
      </SectionCard>

      <SectionCard
        title={`已绑定账号（${bound.data?.length ?? 0}）`}
        extra={
          <button
            onClick={() => setPicking(true)}
            className="flex items-center gap-1 px-2.5 py-1 text-xs bg-blue-600 text-white rounded hover:bg-blue-700"
          >
            <Plus className="w-3 h-3" />
            绑定账号
          </button>
        }
        noPadding
      >
        {bound.isLoading && (
          <div className="py-8 text-center text-sm text-gray-400">
            <Loader2 className="w-4 h-4 inline animate-spin mr-1" />
            加载中…
          </div>
        )}
        {!bound.isLoading && (bound.data ?? []).length === 0 && (
          <div className="py-12 px-6 text-center">
            <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-blue-50 mb-3">
              <Plus className="w-6 h-6 text-blue-500" />
            </div>
            <h3 className="text-base font-semibold text-gray-800 mb-1.5">
              当前应用还没有任何广告账号
            </h3>
            <p className="text-xs text-gray-500 max-w-md mx-auto leading-relaxed">
              绑定账号后，所有数据看板会自动按当前应用过滤；切换到其它应用时互不影响。
              <br />
              点击下面按钮，从已接入该租户的账号中选择并绑定到「{app.name}」。
            </p>
            <button
              onClick={() => setPicking(true)}
              className="mt-5 inline-flex items-center gap-1.5 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition"
            >
              <Plus className="w-4 h-4" />
              立即绑定账号
            </button>
          </div>
        )}
        {!bound.isLoading && (bound.data ?? []).length > 0 && (
          <AccountTable
            rows={bound.data!}
            renderAction={row => (
              <button
                onClick={() => {
                  if (confirm(`确定解绑 ${row.platform.toUpperCase()} 账号 ${row.account_name || row.account_id} ?`)) {
                    unbindMutation.mutate(row.id)
                  }
                }}
                className="p-1.5 rounded text-gray-400 hover:bg-red-50 hover:text-red-600"
                title="解绑"
              >
                <Unlink className="w-3.5 h-3.5" />
              </button>
            )}
          />
        )}
      </SectionCard>

      {picking && (
        <AccountPicker
          appId={app.id}
          appName={app.name}
          onClose={() => setPicking(false)}
          onPick={rowId => bindMutation.mutate(rowId)}
          binding={bindMutation.isPending}
        />
      )}
    </div>
  )
}

function AccountTable({ rows, renderAction }: {
  rows: AdAccountRow[]; renderAction: (row: AdAccountRow) => React.ReactNode
}) {
  return (
    <table className="w-full text-sm">
      <thead className="bg-gray-50/60">
        <tr className="text-left text-xs text-gray-500">
          <th className="px-5 py-2.5 font-medium">平台</th>
          <th className="px-3 py-2.5 font-medium">账户名 / ID</th>
          <th className="px-3 py-2.5 font-medium">货币</th>
          <th className="px-3 py-2.5 font-medium">时区</th>
          <th className="px-3 py-2.5 font-medium">状态</th>
          <th className="px-3 py-2.5 font-medium text-right">操作</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(row => (
          <tr key={row.id} className="border-t border-gray-100 hover:bg-blue-50/30">
            <td className="px-5 py-2.5">
              <span className="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-700 uppercase">
                {row.platform}
              </span>
            </td>
            <td className="px-3 py-2.5">
              <div className="text-gray-800">{row.account_name || '—'}</div>
              <div className="text-xs text-gray-400 font-mono">{row.account_id}</div>
            </td>
            <td className="px-3 py-2.5 text-gray-600">{row.currency}</td>
            <td className="px-3 py-2.5 text-gray-600">{row.timezone}</td>
            <td className="px-3 py-2.5">
              <span className={cn(
                'text-xs px-2 py-0.5 rounded-full',
                row.status === 'ACTIVE'
                  ? 'bg-green-100 text-green-700'
                  : 'bg-gray-100 text-gray-500',
              )}>{row.status}</span>
            </td>
            <td className="px-3 py-2.5 text-right">{renderAction(row)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function AccountPicker({ appId, appName, onClose, onPick, binding }: {
  appId: number; appName: string; onClose: () => void;
  onPick: (rowId: number) => void; binding: boolean
}) {
  const available = useQuery({
    queryKey: ['available-accounts'],
    queryFn: listAvailableAdAccounts,
  })

  const rows = useMemo(() => {
    return (available.data ?? []).filter(r => r.application_id !== appId)
  }, [available.data, appId])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={onClose}>
      <div
        className="bg-white rounded-xl shadow-xl w-full max-w-3xl mx-4 overflow-hidden flex flex-col max-h-[80vh]"
        onClick={e => e.stopPropagation()}
      >
        <div className="px-6 py-4 border-b border-gray-100">
          <h3 className="text-lg font-semibold text-gray-800">绑定广告账号到 「{appName}」</h3>
          <p className="text-xs text-gray-400 mt-1">
            从当前租户已接入的账号中选择。已绑定到其它应用的账号会被标记，点击后会自动从原应用迁移过来。
          </p>
        </div>

        <div className="flex-1 overflow-y-auto">
          {available.isLoading && (
            <div className="py-10 text-center text-sm text-gray-400">
              <Loader2 className="w-4 h-4 inline animate-spin mr-1" />
              加载中…
            </div>
          )}
          {!available.isLoading && rows.length === 0 && (
            <div className="py-10 text-center text-sm text-gray-400">
              没有可用账号。请先到「数据源配置」中接入广告账号。
            </div>
          )}
          {!available.isLoading && rows.length > 0 && (
            <table className="w-full text-sm">
              <thead className="bg-gray-50/60 sticky top-0">
                <tr className="text-left text-xs text-gray-500">
                  <th className="px-5 py-2.5 font-medium">平台</th>
                  <th className="px-3 py-2.5 font-medium">账户名 / ID</th>
                  <th className="px-3 py-2.5 font-medium">归属</th>
                  <th className="px-3 py-2.5 font-medium text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(row => {
                  const elsewhere = row.application_id != null
                  return (
                    <tr key={row.id} className="border-t border-gray-100">
                      <td className="px-5 py-2.5">
                        <span className="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-700 uppercase">
                          {row.platform}
                        </span>
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="text-gray-800">{row.account_name || '—'}</div>
                        <div className="text-xs text-gray-400 font-mono">{row.account_id}</div>
                      </td>
                      <td className="px-3 py-2.5">
                        {elsewhere ? (
                          <span className="text-xs px-2 py-0.5 rounded bg-amber-50 text-amber-700">
                            已绑定到应用 #{row.application_id}
                          </span>
                        ) : (
                          <span className="text-xs px-2 py-0.5 rounded bg-gray-50 text-gray-500">
                            未绑定
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        <button
                          onClick={() => onPick(row.id)}
                          disabled={binding}
                          className="px-2.5 py-1 text-xs bg-blue-600 text-white rounded hover:bg-blue-700 disabled:bg-gray-300"
                        >
                          {elsewhere ? '迁移到此应用' : '绑定'}
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>

        <div className="px-6 py-3 border-t border-gray-100 flex justify-end bg-gray-50">
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-md text-sm text-gray-600 hover:bg-gray-100 flex items-center gap-1"
          >
            完成
            <ExternalLink className="w-3 h-3" />
          </button>
        </div>
      </div>
    </div>
  )
}

function OverviewTab({ app }: { app: Application }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
      <SectionCard title="基础信息">
        <dl className="space-y-3 text-sm">
          <Row label="slug" value={app.slug} mono />
          <Row label="平台类型" value={PLATFORM_LABEL[app.platform_type] ?? app.platform_type} />
          <Row label="所属行业" value={app.industry || '—'} />
          <Row label="Bundle ID" value={app.bundle_id || '—'} mono />
          <Row label="状态" value={app.status === 'active' ? '正常' : '已归档'} />
          <Row label="创建时间" value={app.created_at || '—'} />
        </dl>
      </SectionCard>

      <SectionCard title="商店链接">
        <dl className="space-y-3 text-sm">
          <Row
            label="App Store"
            value={app.store_url_ios
              ? <a href={app.store_url_ios} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline truncate inline-block max-w-[260px]">{app.store_url_ios}</a>
              : '—'}
          />
          <Row
            label="Google Play"
            value={app.store_url_android
              ? <a href={app.store_url_android} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline truncate inline-block max-w-[260px]">{app.store_url_android}</a>
              : '—'}
          />
        </dl>
      </SectionCard>

      <SectionCard title="高级配置（settings_json）" className="md:col-span-2">
        <pre className="text-xs font-mono bg-gray-50 rounded-md p-3 text-gray-700 overflow-x-auto max-h-72 whitespace-pre-wrap">
          {JSON.stringify(app.settings ?? {}, null, 2)}
        </pre>
        <p className="text-xs text-gray-400 mt-2">
          阶段 4 X4 起：归因 / 回传 / 默认目标地区等都会在这个 JSON 中持久化。
        </p>
      </SectionCard>
    </div>
  )
}

function Row({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-gray-500 shrink-0">{label}</dt>
      <dd className={cn('text-gray-800 text-right', mono && 'font-mono text-xs')}>{value}</dd>
    </div>
  )
}
