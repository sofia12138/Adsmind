/**
 * 阶段 7 租户自助注册页 — `/register`
 *
 * 表单字段：邮箱、密码、公司名、套餐选择（视觉占位，目前实际全部存为 free）
 * 提交后调 POST /api/auth/register：后端在事务里创建 tenant + admin user + default app + member。
 * 成功后写 localStorage 并跳 /dashboard，进入 Onboarding 空状态引导。
 */
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Check, Loader2, Sparkles } from 'lucide-react'

type PlanId = 'free' | 'pro' | 'biz'

interface PlanOption {
  id: PlanId
  name: string
  subtitle: string
  features: string[]
  highlight?: boolean
  disabled?: boolean
}

const PLANS: PlanOption[] = [
  {
    id: 'free',
    name: '免费试用',
    subtitle: '$0 / 月',
    features: ['1 个应用', '1 个广告账号', '基础数据看板', '社区支持'],
    highlight: true,
  },
  {
    id: 'pro',
    name: 'Pro 专业版',
    subtitle: '$49 / 月',
    features: ['10 个应用', '20 个广告账号', '归因 + 素材分析', '邮件支持'],
    disabled: true,
  },
  {
    id: 'biz',
    name: 'Business',
    subtitle: '联系销售',
    features: ['无限应用', '专属客户成功', 'AI 优化建议', '可签 SLA'],
    disabled: true,
  },
]

export default function RegisterPage() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [companyName, setCompanyName] = useState('')
  const [planId] = useState<PlanId>('free')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    if (!email.trim() || !password || !companyName.trim()) {
      setError('请完整填写邮箱、密码与公司名')
      return
    }
    if (password.length < 8) {
      setError('密码长度需 ≥ 8 位')
      return
    }
    setLoading(true)
    try {
      const res = await fetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: email.trim().toLowerCase(),
          password,
          company_name: companyName.trim(),
          plan_id: planId,
        }),
      })
      const data = await res.json()
      if (!res.ok || data.ok === false) {
        setError(data.detail ?? data.message ?? '注册失败')
        return
      }
      const token: string = data.token ?? ''
      const role: string = data.user?.role ?? 'admin'
      const panels: string[] = data.allowed_panels ?? []

      localStorage.setItem('auth_token', token)
      localStorage.setItem('auth_user', data.user?.username ?? email.trim().toLowerCase())
      localStorage.setItem('auth_role', role)
      localStorage.setItem('auth_panels', JSON.stringify(panels))
      if (data.tenant) {
        localStorage.setItem('auth_tenant', JSON.stringify(data.tenant))
      }
      if (data.application?.id) {
        localStorage.setItem('current_application_id', String(data.application.id))
      }
      const vurl = data.email_verification?.verification_url
      if (vurl) {
        localStorage.removeItem('email_verified')
        const go = window.confirm(
          `注册成功！\n\n请验证邮箱（MVP 阶段请复制链接到浏览器打开）：\n${vurl}\n\n点击「确定」进入系统，顶部可再次获取验证链接。`,
        )
        if (!go) return
      }
      navigate('/dashboard', { replace: true })
    } catch {
      setError('网络错误，请稍后重试')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 flex items-center justify-center p-4">
      <div className="w-full max-w-5xl grid lg:grid-cols-5 gap-8 items-start">
        {/* ─────── 左：表单 ─────── */}
        <div className="lg:col-span-2">
          <div className="text-center lg:text-left mb-8">
            <div className="inline-flex items-center justify-center w-14 h-14 bg-gradient-to-br from-blue-500 to-purple-600 rounded-2xl shadow-lg shadow-blue-500/25 mb-4">
              <span className="text-white text-2xl font-bold">A</span>
            </div>
            <h1 className="text-2xl font-bold text-white tracking-tight">注册 AdsMind</h1>
            <p className="text-sm text-slate-400 mt-1">5 分钟开通你的广告投放管理系统</p>
          </div>

          <form onSubmit={handleSubmit} className="bg-white/5 backdrop-blur-sm rounded-2xl border border-white/10 p-7">
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5">联系邮箱</label>
                <input
                  type="email"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  placeholder="you@company.com"
                  autoComplete="email"
                  autoFocus
                  className="w-full px-4 py-2.5 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/40 transition"
                />
                <p className="text-[11px] text-slate-500 mt-1">将作为登录账号使用</p>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5">密码</label>
                <input
                  type="password"
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  placeholder="≥ 8 位字符"
                  autoComplete="new-password"
                  className="w-full px-4 py-2.5 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/40 transition"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5">公司 / 团队名</label>
                <input
                  type="text"
                  value={companyName}
                  onChange={e => setCompanyName(e.target.value)}
                  placeholder="例：星辰科技"
                  className="w-full px-4 py-2.5 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/40 transition"
                />
                <p className="text-[11px] text-slate-500 mt-1">作为你在 AdsMind 的"租户"名称，可后续修改</p>
              </div>
            </div>

            {error && (
              <div className="mt-4 px-3 py-2 bg-red-500/10 border border-red-500/20 rounded-lg">
                <p className="text-xs text-red-400">{error}</p>
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full mt-6 py-2.5 bg-gradient-to-r from-blue-500 to-blue-600 hover:from-blue-600 hover:to-blue-700 text-white text-sm font-medium rounded-xl shadow-lg shadow-blue-500/25 disabled:opacity-60 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2"
            >
              {loading ? (
                <><Loader2 className="w-4 h-4 animate-spin" />创建中...</>
              ) : (
                <><Sparkles className="w-4 h-4" />创建账号 & 进入系统</>
              )}
            </button>

            <p className="text-center text-xs text-slate-400 mt-5">
              已有账号？
              <Link to="/login" className="text-blue-400 hover:text-blue-300 ml-1 font-medium">
                返回登录
              </Link>
            </p>
          </form>
        </div>

        {/* ─────── 右：套餐 ─────── */}
        <div className="lg:col-span-3 space-y-3">
          <div className="px-1 mb-2">
            <h2 className="text-sm font-medium text-slate-300">套餐对比</h2>
            <p className="text-[11px] text-slate-500 mt-0.5">注册即免费开通 Free 试用，付费套餐稍后在控制台升级</p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {PLANS.map(plan => (
              <div
                key={plan.id}
                className={`relative rounded-xl p-5 border transition ${
                  plan.highlight
                    ? 'bg-gradient-to-br from-blue-500/15 to-purple-500/10 border-blue-400/40 shadow-lg shadow-blue-500/10'
                    : 'bg-white/5 border-white/10'
                } ${plan.disabled ? 'opacity-60' : ''}`}
              >
                {plan.highlight && (
                  <span className="absolute -top-2 right-3 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-blue-500 text-white">
                    当前选择
                  </span>
                )}
                <h3 className="text-white text-base font-semibold">{plan.name}</h3>
                <p className="text-slate-400 text-xs mt-0.5">{plan.subtitle}</p>
                <ul className="mt-4 space-y-2">
                  {plan.features.map(f => (
                    <li key={f} className="flex items-start gap-2 text-xs text-slate-300">
                      <Check className="w-3.5 h-3.5 text-blue-400 shrink-0 mt-0.5" />
                      <span>{f}</span>
                    </li>
                  ))}
                </ul>
                {plan.disabled && (
                  <p className="text-[11px] text-slate-500 mt-4 pt-3 border-t border-white/5">
                    试用阶段不可选；上线后开放
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
