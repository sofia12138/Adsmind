import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Loader2 } from 'lucide-react'

export default function LoginPage() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!username.trim() || !password.trim()) {
      setError('请输入账号和密码')
      return
    }
    setError('')
    setLoading(true)
    try {
      const res = await fetch('/api/users/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username.trim(), password }),
      })
      if (res.status === 502 || res.status === 503) {
        try {
          const err = await res.json()
          if (err.error === 'database_unavailable' || err.message?.includes('数据库')) {
            setError('数据库连接失败：请确认能访问远程 MySQL（47.238.108.255）或已启动 SSH 隧道')
            return
          }
        } catch {
          /* fall through */
        }
        setError('后端服务未启动或数据库不可用，请确认 backend 已在 8000 端口运行且 MySQL 可连接')
        return
      }
      const data = await res.json()
      if (!res.ok || data.ok === false) {
        const detail = data.detail
        const msg =
          typeof detail === 'string'
            ? detail
            : typeof detail === 'object' && detail?.message
              ? detail.message
              : data.message
        setError(msg ?? '登录失败')
        return
      }
      const token = data.token ?? data.access_token ?? ''
      const role = data.user?.role ?? data.role ?? 'viewer'
      const panels: string[] = data.allowed_panels ?? []

      localStorage.setItem('auth_token', token)
      localStorage.setItem('auth_user', username.trim())
      localStorage.setItem('auth_role', role)
      localStorage.setItem('auth_panels', JSON.stringify(panels))
      // 阶段 1：保存后端返回的 tenant 上下文；缺省时由 AuthContext 兜底为 internal。
      if (data.tenant) {
        localStorage.setItem('auth_tenant', JSON.stringify(data.tenant))
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
      <div className="w-full max-w-sm">
        <div className="text-center mb-10">
          <div className="inline-flex items-center justify-center w-14 h-14 bg-gradient-to-br from-blue-500 to-purple-600 rounded-2xl shadow-lg shadow-blue-500/25 mb-4">
            <span className="text-white text-2xl font-bold">A</span>
          </div>
          <h1 className="text-2xl font-bold text-white tracking-tight">AdsMind</h1>
          <p className="text-sm text-slate-400 mt-1">广告智能投放管理系统</p>
        </div>

        <form onSubmit={handleSubmit} className="bg-white/5 backdrop-blur-sm rounded-2xl border border-white/10 p-8">
          <div className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1.5">账号</label>
              <input type="text" value={username} onChange={e => setUsername(e.target.value)} placeholder="请输入账号" autoFocus
                className="w-full px-4 py-2.5 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/40 transition" />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1.5">密码</label>
              <input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="请输入密码"
                className="w-full px-4 py-2.5 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/40 transition" />
            </div>
          </div>

          {error && (
            <div className="mt-4 px-3 py-2 bg-red-500/10 border border-red-500/20 rounded-lg">
              <p className="text-xs text-red-400">{error}</p>
            </div>
          )}

          <button type="submit" disabled={loading}
            className="w-full mt-6 py-2.5 bg-gradient-to-r from-blue-500 to-blue-600 hover:from-blue-600 hover:to-blue-700 text-white text-sm font-medium rounded-xl shadow-lg shadow-blue-500/25 disabled:opacity-60 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2">
            {loading ? (<><Loader2 className="w-4 h-4 animate-spin" />登录中...</>) : '登 录'}
          </button>

          <p className="text-center text-xs text-slate-400 mt-5">
            还没有账号？
            <Link to="/register" className="text-blue-400 hover:text-blue-300 ml-1 font-medium">
              立即注册试用
            </Link>
          </p>
        </form>

        <p className="text-center text-xs text-slate-500 mt-6">AdsMind &copy; 2026</p>
      </div>
    </div>
  )
}
