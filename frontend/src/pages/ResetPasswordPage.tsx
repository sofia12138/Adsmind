import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

export default function ResetPasswordPage() {
  const [token] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get('token') ?? '')
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    if (password !== confirmation) { setError('两次输入的密码不一致'); return }
    if (new TextEncoder().encode(password).length > 72) { setError('密码过长，请缩短后重试'); return }
    setBusy(true)
    try {
      const response = await fetch('/api/auth/reset-password', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, password }),
      })
      const data = await response.json()
      if (!response.ok) { setError(typeof data.detail === 'string' ? data.detail : '无法重置密码，请检查链接和密码'); return }
      setPassword(''); setConfirmation(''); setDone(true)
      window.history.replaceState(null, '', '/reset-password')
      for (const key of ['auth_token', 'auth_user', 'auth_role', 'auth_panels', 'auth_tenant', 'current_application_id']) localStorage.removeItem(key)
    } catch { setError('连接失败，请稍后重试') }
    finally { setBusy(false) }
  }

  return <div className="min-h-screen bg-slate-900 flex items-center justify-center p-6">
    <div className="w-full max-w-sm bg-white rounded-2xl p-7 shadow-xl">
      <h1 className="text-xl font-semibold mb-3">设置新密码</h1>
      {done ? <><p className="text-sm mb-5">密码已更新，请使用新密码登录。</p><a href="/login" className="text-blue-600">前往登录</a></> : <form onSubmit={submit}>
        <p className="text-sm text-gray-500 mb-5">重置链接有效期为 30 分钟，仅可使用一次。</p>
        <label className="block text-sm mb-2" htmlFor="new-password">新密码</label>
        <input id="new-password" type="password" autoComplete="new-password" minLength={8} maxLength={72} required value={password} onChange={e => setPassword(e.target.value)} className="w-full border rounded-lg p-2 mb-4" placeholder="至少 8 位" />
        <label className="block text-sm mb-2" htmlFor="confirm-password">确认新密码</label>
        <input id="confirm-password" type="password" autoComplete="new-password" required value={confirmation} onChange={e => setConfirmation(e.target.value)} className="w-full border rounded-lg p-2 mb-4" />
        {error && <p role="alert" className="text-sm text-red-600 mb-3">{error}</p>}
        {!token && <p className="text-sm text-red-600 mb-3">请使用完整的重置链接打开此页面。</p>}
        <button disabled={busy || !token} className="w-full bg-blue-600 text-white rounded-lg p-2 disabled:opacity-50">{busy ? '保存中…' : '保存新密码'}</button>
        <Link to="/login" className="block text-center text-sm text-gray-500 mt-4">返回登录</Link>
      </form>}
    </div>
  </div>
}
