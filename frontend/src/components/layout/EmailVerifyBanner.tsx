import { useEffect, useState } from 'react'
import { Mail, X } from 'lucide-react'
import { apiFetch } from '@/services/api'

export function EmailVerifyBanner() {
  const [show, setShow] = useState(false)
  const [email, setEmail] = useState('')
  const [verifyUrl, setVerifyUrl] = useState<string | null>(null)
  const [dismissed, setDismissed] = useState(
    () => sessionStorage.getItem('email_verify_banner_dismiss') === '1',
  )

  useEffect(() => {
    if (dismissed || localStorage.getItem('email_verified') === '1') return
    apiFetch<{ email_verified?: boolean; username?: string }>('/api/users/me')
      .then(me => {
        if (me.email_verified !== false) {
          localStorage.setItem('email_verified', '1')
          return
        }
        setEmail(me.username ?? '')
        setShow(true)
      })
      .catch(() => {})
  }, [dismissed])

  async function resend() {
    try {
      const r = await fetch('/api/auth/resend-verification', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem('auth_token') ?? ''}`,
        },
        body: JSON.stringify({ email }),
      })
      const j = await r.json()
      if (j.verification_url) {
        setVerifyUrl(j.verification_url)
        alert(`验证链接（MVP 无邮件服务，请复制打开）：\n${j.verification_url}`)
      } else if (j.already_verified) {
        localStorage.setItem('email_verified', '1')
        setShow(false)
      }
    } catch {
      alert('发送失败')
    }
  }

  if (!show || dismissed) return null

  return (
    <div className="bg-sky-500/10 border-b border-sky-500/30 px-6 py-2.5 flex items-center justify-between text-[13px] text-sky-100">
      <div className="flex items-center gap-2 min-w-0">
        <Mail className="w-4 h-4 shrink-0 text-sky-300" />
        <span className="truncate">
          请验证邮箱 <b>{email}</b> 以保障账号安全（MVP：点击下方获取验证链接）
        </span>
        {verifyUrl && (
          <a href={verifyUrl} className="ml-2 underline text-sky-200 shrink-0" target="_blank" rel="noreferrer">
            打开验证链接
          </a>
        )}
      </div>
      <div className="flex items-center gap-2 shrink-0 ml-4">
        <button
          type="button"
          onClick={resend}
          className="text-sky-200 hover:text-white underline underline-offset-2 text-xs"
        >
          获取验证链接
        </button>
        <button
          type="button"
          onClick={() => {
            sessionStorage.setItem('email_verify_banner_dismiss', '1')
            setDismissed(true)
          }}
          aria-label="关闭"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  )
}
