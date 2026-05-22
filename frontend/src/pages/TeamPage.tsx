/**
 * 阶段 7 团队页 — `/team`
 *
 * 当前租户的成员管理 + 邀请管理。
 * - 顶部 QuotaUsageCard（含 members 配额）
 * - 邀请列表（active / accepted / revoked / expired）
 * - 邀请新成员按钮 → 弹框 → 调 POST /api/tenant/invitations → 复制 URL
 */
import { useState, type FormEvent } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Users, Plus, Loader2, X, Check, Copy, AlertCircle, MailOpen, MailX, MailCheck, Clock,
} from 'lucide-react'
import { PageHeader } from '@/components/common/PageHeader'
import { SectionCard } from '@/components/common/SectionCard'
import { QuotaUsageCard } from '@/components/common/QuotaUsageCard'
import {
  createInvitation,
  listInvitations,
  listTenantMembers,
  removeTenantMember,
  revokeInvitation,
  updateMemberRole,
  type Invitation,
  type InvitationStatus,
  type TenantMember,
} from '@/services/invitations'
import { QuotaExceededError } from '@/services/api'
import { cn } from '@/utils/cn'

const ROLE_LABEL: Record<string, string> = {
  owner: '所有者', admin: '管理员', member: '成员',
}

const STATUS_META: Record<InvitationStatus, {
  label: string; cls: string; Icon: typeof MailOpen
}> = {
  active:   { label: '待接受', cls: 'bg-blue-100 text-blue-700', Icon: MailOpen },
  accepted: { label: '已加入', cls: 'bg-green-100 text-green-700', Icon: MailCheck },
  revoked:  { label: '已撤销', cls: 'bg-gray-100 text-gray-500', Icon: MailX },
  expired:  { label: '已过期', cls: 'bg-amber-100 text-amber-700', Icon: Clock },
}

export default function TeamPage() {
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<'members' | 'invites'>('members')
  const [creating, setCreating] = useState(false)
  const [copied, setCopied] = useState<number | null>(null)

  const members = useQuery({
    queryKey: ['tenant-members'],
    queryFn: listTenantMembers,
  })

  const list = useQuery({
    queryKey: ['invitations'],
    queryFn: listInvitations,
  })

  const createMutation = useMutation({
    mutationFn: createInvitation,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['invitations'] })
      queryClient.invalidateQueries({ queryKey: ['quota', 'me'] })
      setCreating(false)
    },
    onError: (err: unknown) => {
      if (err instanceof QuotaExceededError) {
        alert(`${err.message}\n\n${err.upgradeHint ?? '请升级套餐解锁更多额度。'}`)
        setCreating(false)
      } else if ((err as Error)?.message) {
        alert((err as Error).message)
      } else {
        alert('发起邀请失败')
      }
    },
  })

  const revokeMutation = useMutation({
    mutationFn: revokeInvitation,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['invitations'] })
      queryClient.invalidateQueries({ queryKey: ['quota', 'me'] })
    },
    onError: (e: Error) => alert(e.message || '撤销失败'),
  })

  function copyUrl(invite: Invitation) {
    if (!invite.invitation_url) return
    navigator.clipboard.writeText(invite.invitation_url).then(() => {
      setCopied(invite.id)
      setTimeout(() => setCopied(null), 2000)
    })
  }

  const rows = list.data ?? []

  return (
    <div className="p-6 max-w-6xl">
      <PageHeader
        title={<span className="flex items-center gap-2"><Users className="w-5 h-5 text-blue-500" />团队成员</span>}
        description="邀请同事加入当前租户，分配角色协作管理广告投放。"
        action={
          <button
            onClick={() => setCreating(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700"
          >
            <Plus className="w-4 h-4" />
            邀请成员
          </button>
        }
      />

      <div className="mb-4">
        <QuotaUsageCard />
      </div>

      <div className="flex gap-1 mb-4 border-b border-gray-200">
        {(['members', 'invites'] as const).map(t => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={cn(
              'px-4 py-2 text-sm border-b-2 -mb-px',
              tab === t ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500',
            )}
          >
            {t === 'members' ? `已加入（${members.data?.length ?? 0}）` : `邀请（${rows.length}）`}
          </button>
        ))}
      </div>

      {tab === 'members' && (
        <SectionCard title="成员列表" noPadding>
          <table className="w-full text-sm">
            <thead className="bg-gray-50/60">
              <tr className="text-left text-xs text-gray-500">
                <th className="px-5 py-3">用户</th>
                <th className="px-3 py-3">角色</th>
                <th className="px-3 py-3 text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {(members.data ?? []).map((m: TenantMember) => (
                <MemberRow key={m.user_id} m={m} onChanged={() => members.refetch()} />
              ))}
            </tbody>
          </table>
        </SectionCard>
      )}

      {tab === 'invites' && (
      <SectionCard title={`邀请记录（${rows.length}）`} noPadding>
        {list.isLoading && (
          <div className="flex items-center justify-center py-10 text-sm text-gray-400">
            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            加载中…
          </div>
        )}
        {list.isError && (
          <div className="flex items-center justify-center py-10 text-sm text-red-500">
            <AlertCircle className="w-4 h-4 mr-2" />
            加载失败
            <button onClick={() => list.refetch()} className="ml-2 underline">重试</button>
          </div>
        )}
        {!list.isLoading && !list.isError && rows.length === 0 && (
          <div className="text-center py-12 text-sm text-gray-400">
            还没有邀请记录。点击右上角"邀请成员"开始拉同事一起用。
          </div>
        )}
        {!list.isLoading && !list.isError && rows.length > 0 && (
          <table className="w-full text-sm">
            <thead className="bg-gray-50/60">
              <tr className="text-left text-xs text-gray-500">
                <th className="px-5 py-3 font-medium">受邀邮箱</th>
                <th className="px-3 py-3 font-medium">角色</th>
                <th className="px-3 py-3 font-medium">状态</th>
                <th className="px-3 py-3 font-medium">邀请人</th>
                <th className="px-3 py-3 font-medium">过期时间</th>
                <th className="px-3 py-3 font-medium text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(inv => {
                const meta = STATUS_META[inv.status]
                return (
                  <tr key={inv.id} className="border-t border-gray-100 hover:bg-blue-50/30">
                    <td className="px-5 py-3 text-gray-900 font-medium">{inv.email}</td>
                    <td className="px-3 py-3 text-gray-600">{ROLE_LABEL[inv.role] ?? inv.role}</td>
                    <td className="px-3 py-3">
                      <span className={cn('inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full', meta.cls)}>
                        <meta.Icon className="w-3 h-3" />
                        {meta.label}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-gray-600">
                      {inv.invited_by_display_name || inv.invited_by_username || '—'}
                    </td>
                    <td className="px-3 py-3 text-gray-500 text-xs">
                      {inv.expires_at?.replace('T', ' ').slice(0, 16) || '—'}
                    </td>
                    <td className="px-3 py-3 text-right whitespace-nowrap">
                      {inv.status === 'active' && (
                        <div className="inline-flex items-center gap-2">
                          <button
                            onClick={() => copyUrl(inv)}
                            className="inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700"
                            title="复制邀请链接"
                          >
                            {copied === inv.id ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
                            {copied === inv.id ? '已复制' : '复制链接'}
                          </button>
                          <button
                            onClick={() => {
                              if (confirm(`确定撤销发给 ${inv.email} 的邀请吗？`)) {
                                revokeMutation.mutate(inv.id)
                              }
                            }}
                            className="text-xs text-gray-500 hover:text-red-600"
                          >
                            撤销
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </SectionCard>
      )}

      {creating && (
        <InvitationFormDialog
          onClose={() => setCreating(false)}
          onSubmit={data => createMutation.mutate(data)}
          saving={createMutation.isPending}
        />
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// 弹框
// ─────────────────────────────────────────────────────────────

interface FormProps {
  onClose: () => void
  onSubmit: (data: { email: string; role: 'owner' | 'admin' | 'member'; ttl_days?: number }) => void
  saving: boolean
}

function MemberRow({ m, onChanged }: { m: TenantMember; onChanged: () => void }) {
  const me = localStorage.getItem('auth_user') ?? ''
  const isSelf = m.username === me
  const [role, setRole] = useState(m.role)

  const updateMut = useMutation({
    mutationFn: () => updateMemberRole(m.user_id, role),
    onSuccess: onChanged,
    onError: (e: Error) => alert(e.message || '更新失败'),
  })
  const removeMut = useMutation({
    mutationFn: () => removeTenantMember(m.user_id),
    onSuccess: onChanged,
    onError: (e: Error) => alert(e.message || '移除失败'),
  })

  return (
    <tr className="border-t border-gray-100">
      <td className="px-5 py-3">
        <div className="font-medium text-gray-900">{m.display_name || m.username}</div>
        <div className="text-xs text-gray-400">{m.username}</div>
      </td>
      <td className="px-3 py-3">
        <select
          value={role}
          disabled={isSelf}
          onChange={e => setRole(e.target.value as TenantMember['role'])}
          className="text-xs border border-gray-200 rounded px-2 py-1"
        >
          <option value="owner">所有者</option>
          <option value="admin">管理员</option>
          <option value="member">成员</option>
        </select>
      </td>
      <td className="px-3 py-3 text-xs text-gray-500">
        {m.joined_at?.replace('T', ' ').slice(0, 16) ?? '—'}
      </td>
      <td className="px-3 py-3 text-right">
        {!isSelf && (
          <div className="inline-flex gap-2">
            {role !== m.role && (
              <button
                type="button"
                onClick={() => updateMut.mutate()}
                className="text-xs text-blue-600 hover:underline"
              >
                保存角色
              </button>
            )}
            <button
              type="button"
              onClick={() => {
                if (confirm(`确定将 ${m.username} 移出团队？`)) removeMut.mutate()
              }}
              className="text-xs text-red-600 hover:underline"
            >
              移除
            </button>
          </div>
        )}
        {isSelf && <span className="text-xs text-gray-400">当前用户</span>}
      </td>
    </tr>
  )
}

function InvitationFormDialog({ onClose, onSubmit, saving }: FormProps) {
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<'owner' | 'admin' | 'member'>('member')
  const [ttl, setTtl] = useState(7)

  function submit(e: FormEvent) {
    e.preventDefault()
    if (!email.trim()) return
    onSubmit({ email: email.trim().toLowerCase(), role, ttl_days: ttl })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={onClose}>
      <div
        className="bg-white rounded-xl shadow-xl w-full max-w-md mx-4 overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-gray-800">邀请新成员</h3>
          <button onClick={onClose} className="p-1.5 rounded text-gray-400 hover:text-gray-700">
            <X className="w-4 h-4" />
          </button>
        </div>
        <form onSubmit={submit} className="px-6 py-5 space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-600 mb-1">受邀邮箱</label>
            <input
              type="email"
              required
              autoFocus
              value={email}
              onChange={e => setEmail(e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-100 focus:outline-none"
              placeholder="colleague@company.com"
            />
            <p className="text-xs text-gray-400 mt-1">系统会生成专属邀请链接，分享给同事即可。</p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-gray-600 mb-1">角色</label>
              <select
                value={role}
                onChange={e => setRole(e.target.value as 'owner' | 'admin' | 'member')}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-100 focus:outline-none"
              >
                <option value="member">成员（只读 / 操作）</option>
                <option value="admin">管理员（含成员管理）</option>
                <option value="owner">所有者（含计费）</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-600 mb-1">有效期</label>
              <select
                value={ttl}
                onChange={e => setTtl(parseInt(e.target.value, 10))}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-100 focus:outline-none"
              >
                <option value={1}>1 天</option>
                <option value={3}>3 天</option>
                <option value={7}>7 天</option>
                <option value={14}>14 天</option>
                <option value={30}>30 天</option>
              </select>
            </div>
          </div>
        </form>

        <div className="px-6 py-3 border-t border-gray-100 flex justify-end gap-2 bg-gray-50">
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="px-4 py-1.5 rounded-md text-sm text-gray-600 hover:bg-gray-100"
          >
            取消
          </button>
          <button
            type="submit"
            onClick={submit}
            disabled={saving || !email.trim()}
            className="px-4 py-1.5 rounded-md bg-blue-600 text-white text-sm hover:bg-blue-700 disabled:bg-gray-300 flex items-center gap-1"
          >
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            发送邀请
          </button>
        </div>
      </div>
    </div>
  )
}
