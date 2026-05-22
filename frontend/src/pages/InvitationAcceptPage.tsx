/**
 * 阶段 7 团队邀请接受页 — `/invitation/:token`
 *
 * 匿名可访问。流程：
 *   1) 加载时调 GET /api/auth/invitation/:token 拿 tenant 名 / 邀请人 / 角色
 *   2) 根据 email_registered + 当前是否已登录展示不同 UI：
 *      a) email 已注册 + 当前未登录 → 提示去登录后回来接受
 *      b) email 已注册 + 当前已登录 + 匹配 → "接受邀请"按钮直接加入
 *      c) email 未注册 + 当前未登录 → 表单：设置密码 + display_name + 接受
 *   3) 接受成功后写 localStorage + 跳 /dashboard
 */
import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { CheckCircle2, AlertTriangle, Loader2, Users, Mail, Sparkles } from 'lucide-react'
import {
  acceptInvitation,
  previewInvitation,
  type InvitationPreview,
} from '@/services/invitations'

export default function InvitationAcceptPage() {
  const { token = '' } = useParams<{ token: string }>()
  const navigate = useNavigate()

  const [preview, setPreview] = useState<InvitationPreview | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadErr, setLoadErr] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')

  const isLoggedIn = !!localStorage.getItem('auth_token')
  const currentUser = localStorage.getItem('auth_user') || ''

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    previewInvitation(token)
      .then(p => {
        if (cancelled) return
        setPreview(p)
        setDisplayName(p.email.split('@')[0] || '')
      })
      .catch((e: Error) => {
        if (cancelled) return
        setLoadErr(e.message || '加载邀请信息失败')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [token])

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError('')
    if (!preview) return
    const needPassword = !isLoggedIn && !preview.email_registered
    if (needPassword) {
      if (!password || password.length < 8) {
        setError('密码至少 8 位')
        return
      }
    }
    setSubmitting(true)
    try {
      const res = await acceptInvitation(token, needPassword ? { password, display_name: displayName } : {})
      localStorage.setItem('auth_token', res.token)
      localStorage.setItem('auth_user', res.user.username)
      localStorage.setItem('auth_role', res.user.role)
      localStorage.setItem('auth_panels', JSON.stringify(res.allowed_panels ?? []))
      if (res.tenant) localStorage.setItem('auth_tenant', JSON.stringify(res.tenant))
      if (res.application?.id) localStorage.setItem('current_application_id', String(res.application.id))
      navigate('/dashboard', { replace: true })
    } catch (e) {
      const err = e as Error & { code?: string }
      setError(err.message || '接受邀请失败')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <Shell>
        <div className="flex flex-col items-center justify-center py-10 text-slate-400 text-sm">
          <Loader2 className="w-5 h-5 animate-spin mb-3" />
          加载邀请信息…
        </div>
      </Shell>
    )
  }

  if (loadErr || !preview) {
    return (
      <Shell>
        <div className="flex flex-col items-center text-center py-8">
          <AlertTriangle className="w-10 h-10 text-amber-400 mb-3" />
          <h2 className="text-lg font-semibold text-white">无法打开邀请</h2>
          <p className="text-sm text-slate-400 mt-2 max-w-sm">{loadErr || '邀请链接无效，请联系邀请人重新发送。'}</p>
          <Link to="/login" className="mt-5 text-blue-400 hover:text-blue-300 text-sm">返回登录 →</Link>
        </div>
      </Shell>
    )
  }

  // 不可用状态
  if (preview.status !== 'active') {
    const map = {
      accepted: { title: '邀请已被接受', tip: '该邀请之前已成功接受。如有疑问请联系邀请人。' },
      revoked:  { title: '邀请已被撤销', tip: '邀请人撤销了该邀请。请联系邀请人重新发送。' },
      expired:  { title: '邀请已过期',   tip: '邀请最长 30 天有效。请联系邀请人重新发送。' },
    }[preview.status] ?? { title: '邀请状态异常', tip: '请联系邀请人' }
    return (
      <Shell>
        <div className="flex flex-col items-center text-center py-8">
          <AlertTriangle className="w-10 h-10 text-amber-400 mb-3" />
          <h2 className="text-lg font-semibold text-white">{map.title}</h2>
          <p className="text-sm text-slate-400 mt-2 max-w-sm">{map.tip}</p>
          <Link to="/login" className="mt-5 text-blue-400 hover:text-blue-300 text-sm">返回登录 →</Link>
        </div>
      </Shell>
    )
  }

  // 已登录但邮箱不匹配
  const emailMismatch = isLoggedIn && currentUser && currentUser.toLowerCase() !== preview.email.toLowerCase()
  if (emailMismatch) {
    return (
      <Shell>
        <Header tenantName={preview.tenant_name} inviterName={preview.inviter_name} role={preview.role} />
        <div className="mt-6 px-4 py-3 bg-amber-500/10 border border-amber-500/30 rounded-lg text-sm text-amber-200">
          当前已登录账号 <b>{currentUser}</b>，但本邀请发给 <b>{preview.email}</b>。
          <br />请退出当前账号后重新打开本邀请链接。
        </div>
        <button
          onClick={() => {
            localStorage.removeItem('auth_token')
            localStorage.removeItem('auth_user')
            localStorage.removeItem('auth_role')
            localStorage.removeItem('auth_panels')
            localStorage.removeItem('auth_tenant')
            localStorage.removeItem('current_application_id')
            window.location.reload()
          }}
          className="w-full mt-5 py-2.5 bg-amber-500/20 hover:bg-amber-500/30 text-amber-100 text-sm font-medium rounded-lg transition"
        >
          退出当前账号并刷新
        </button>
      </Shell>
    )
  }

  // 邮箱已注册但未登录 → 引导登录
  const needLogin = !isLoggedIn && preview.email_registered
  if (needLogin) {
    return (
      <Shell>
        <Header tenantName={preview.tenant_name} inviterName={preview.inviter_name} role={preview.role} />
        <div className="mt-6 px-4 py-3 bg-blue-500/10 border border-blue-500/30 rounded-lg text-sm text-blue-100">
          邮箱 <b>{preview.email}</b> 已注册 AdsMind 账号。请先登录后再回到本页面接受邀请。
        </div>
        <Link
          to={`/login?next=${encodeURIComponent(window.location.pathname)}`}
          className="w-full mt-5 py-2.5 bg-gradient-to-r from-blue-500 to-blue-600 hover:from-blue-600 hover:to-blue-700 text-white text-sm font-medium rounded-xl shadow-lg shadow-blue-500/25 inline-flex items-center justify-center"
        >
          去登录
        </Link>
      </Shell>
    )
  }

  // 主流程：已登录 + 匹配 → 一键接受；未登录 + 新用户 → 设密码后接受
  const needPassword = !isLoggedIn && !preview.email_registered

  return (
    <Shell>
      <Header tenantName={preview.tenant_name} inviterName={preview.inviter_name} role={preview.role} />

      <form onSubmit={submit} className="mt-6 space-y-4">
        <div className="px-4 py-3 bg-white/5 border border-white/10 rounded-lg text-sm text-slate-300 flex items-center gap-2">
          <Mail className="w-4 h-4 text-slate-400 shrink-0" />
          受邀邮箱：<b className="text-white ml-1">{preview.email}</b>
        </div>

        {needPassword && (
          <>
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1.5">设置登录密码</label>
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="≥ 8 位"
                autoComplete="new-password"
                autoFocus
                className="w-full px-4 py-2.5 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/40 transition"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1.5">显示名</label>
              <input
                type="text"
                value={displayName}
                onChange={e => setDisplayName(e.target.value)}
                placeholder="给同事看的名字"
                className="w-full px-4 py-2.5 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/40 transition"
              />
            </div>
          </>
        )}

        {error && (
          <div className="px-3 py-2 bg-red-500/10 border border-red-500/20 rounded-lg">
            <p className="text-xs text-red-400">{error}</p>
          </div>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="w-full py-2.5 bg-gradient-to-r from-blue-500 to-blue-600 hover:from-blue-600 hover:to-blue-700 text-white text-sm font-medium rounded-xl shadow-lg shadow-blue-500/25 disabled:opacity-60 transition-all flex items-center justify-center gap-2"
        >
          {submitting ? (
            <><Loader2 className="w-4 h-4 animate-spin" />接受中…</>
          ) : (
            <><CheckCircle2 className="w-4 h-4" />接受邀请并进入系统</>
          )}
        </button>
      </form>
    </Shell>
  )
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 bg-gradient-to-br from-blue-500 to-purple-600 rounded-2xl shadow-lg shadow-blue-500/25 mb-4">
            <Users className="w-6 h-6 text-white" />
          </div>
          <h1 className="text-2xl font-bold text-white tracking-tight">团队邀请</h1>
          <p className="text-sm text-slate-400 mt-1">AdsMind · 多人协作</p>
        </div>
        <div className="bg-white/5 backdrop-blur-sm rounded-2xl border border-white/10 p-7">
          {children}
        </div>
        <p className="text-center text-xs text-slate-500 mt-6">AdsMind &copy; 2026</p>
      </div>
    </div>
  )
}

function Header({ tenantName, inviterName, role }: {
  tenantName?: string | null; inviterName?: string | null; role: string
}) {
  return (
    <div className="text-center">
      <div className="inline-flex items-center gap-1 px-2.5 py-0.5 bg-blue-500/15 border border-blue-400/30 rounded-full text-[11px] text-blue-300 mb-3">
        <Sparkles className="w-3 h-3" />
        团队邀请
      </div>
      <p className="text-sm text-slate-300">
        <b className="text-white">{inviterName || '管理员'}</b>
        {' '}邀请你加入团队
      </p>
      <p className="text-lg font-semibold text-white mt-1">{tenantName || '（未命名团队）'}</p>
      <p className="text-xs text-slate-500 mt-1">将以「<span className="text-slate-300">{roleLabel(role)}</span>」身份加入</p>
    </div>
  )
}

function roleLabel(r: string): string {
  return { owner: '所有者', admin: '管理员', member: '成员' }[r] ?? r
}
