import { useState, type FormEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2, X } from 'lucide-react'
import { createUpgradeRequest } from '@/services/billing'

const PLAN_OPTIONS = [
  { id: 'starter', name: 'Starter', desc: '3 应用 · 3 账号' },
  { id: 'pro', name: 'Pro', desc: '10 应用 · 10 账号' },
  { id: 'business', name: 'Business', desc: '30 应用 · 30 账号' },
  { id: 'enterprise', name: 'Enterprise', desc: '联系定制' },
]

export function UpgradePlanDialog({
  currentPlanId,
  defaultEmail,
  onClose,
}: {
  currentPlanId: string
  defaultEmail: string
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [toPlan, setToPlan] = useState('pro')
  const [email, setEmail] = useState(defaultEmail)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const mutation = useMutation({
    mutationFn: () =>
      createUpgradeRequest({
        to_plan_id: toPlan,
        contact_email: email.trim(),
        message: message.trim() || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['quota', 'me'] })
      qc.invalidateQueries({ queryKey: ['upgrade-requests'] })
      alert('升级申请已提交，平台管理员审核通过后会自动切换套餐。')
      onClose()
    },
    onError: (e: unknown) => {
      setError((e as Error)?.message || '提交失败')
    },
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    setError('')
    if (toPlan === currentPlanId) {
      setError('目标套餐与当前套餐相同')
      return
    }
    mutation.mutate()
  }

  return (
    <DialogShell onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-600 mb-1">目标套餐</label>
          <select
            value={toPlan}
            onChange={e => setToPlan(e.target.value)}
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
          >
            {PLAN_OPTIONS.filter(p => p.id !== currentPlanId).map(p => (
              <option key={p.id} value={p.id}>
                {p.name} — {p.desc}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-600 mb-1">联系邮箱</label>
          <input
            type="email"
            required
            value={email}
            onChange={e => setEmail(e.target.value)}
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-600 mb-1">备注（可选）</label>
          <textarea
            rows={2}
            value={message}
            onChange={e => setMessage(e.target.value)}
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
            placeholder="例如：预计每月广告 spend、需要的账号数…"
          />
        </div>
        {error && <p className="text-xs text-red-500">{error}</p>}
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="px-4 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded-md">
            取消
          </button>
          <button
            type="submit"
            disabled={mutation.isPending}
            className="px-4 py-1.5 text-sm bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-60 flex items-center gap-1"
          >
            {mutation.isPending && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            提交申请
          </button>
        </div>
      </form>
    </DialogShell>
  )
}

function DialogShell({
  onClose,
  children,
}: {
  onClose: () => void
  children: React.ReactNode
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={onClose}>
      <div
        className="bg-white rounded-xl shadow-xl w-full max-w-md mx-4 overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-gray-800">申请升级套餐</h3>
          <button type="button" onClick={onClose} className="p-1.5 rounded text-gray-400 hover:text-gray-700">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="px-6 py-5">{children}</div>
      </div>
    </div>
  )
}
