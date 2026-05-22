import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { CheckCircle2, AlertTriangle, Loader2 } from 'lucide-react'

export default function VerifyEmailPage() {
  const { token = '' } = useParams<{ token: string }>()
  const [status, setStatus] = useState<'loading' | 'ok' | 'already' | 'error'>('loading')
  const [email, setEmail] = useState('')

  useEffect(() => {
    let cancelled = false
    fetch(`/api/auth/verify-email/${encodeURIComponent(token)}`, { method: 'GET' })
      .then(async res => {
        const j = await res.json().catch(() => ({}))
        if (cancelled) return
        if (!res.ok) {
          setStatus('error')
          setEmail(typeof j.detail === 'object' ? j.detail.message : String(j.detail ?? res.status))
          return
        }
        setEmail(j.email ?? '')
        setStatus(j.already_verified ? 'already' : 'ok')
        localStorage.setItem('email_verified', '1')
      })
      .catch(() => {
        if (!cancelled) setStatus('error')
      })
    return () => { cancelled = true }
  }, [token])

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-white/5 backdrop-blur border border-white/10 rounded-2xl p-8 text-center">
        {status === 'loading' && (
          <>
            <Loader2 className="w-8 h-8 animate-spin text-blue-400 mx-auto mb-4" />
            <p className="text-slate-300 text-sm">正在验证邮箱…</p>
          </>
        )}
        {status === 'ok' && (
          <>
            <CheckCircle2 className="w-10 h-10 text-green-400 mx-auto mb-3" />
            <h1 className="text-lg font-semibold text-white">邮箱验证成功</h1>
            <p className="text-sm text-slate-400 mt-2">{email}</p>
            <Link to="/dashboard" className="inline-block mt-6 text-blue-400 hover:text-blue-300 text-sm">
              进入控制台 →
            </Link>
          </>
        )}
        {status === 'already' && (
          <>
            <CheckCircle2 className="w-10 h-10 text-blue-400 mx-auto mb-3" />
            <h1 className="text-lg font-semibold text-white">邮箱已验证过</h1>
            <Link to="/dashboard" className="inline-block mt-6 text-blue-400 text-sm">进入控制台 →</Link>
          </>
        )}
        {status === 'error' && (
          <>
            <AlertTriangle className="w-10 h-10 text-amber-400 mx-auto mb-3" />
            <h1 className="text-lg font-semibold text-white">验证失败</h1>
            <p className="text-sm text-slate-400 mt-2">{email || '链接无效或已过期'}</p>
            <Link to="/login" className="inline-block mt-6 text-blue-400 text-sm">返回登录</Link>
          </>
        )}
      </div>
    </div>
  )
}
