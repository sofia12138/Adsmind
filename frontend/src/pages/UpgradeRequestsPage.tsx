import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Crown, Loader2, Check, X } from 'lucide-react'
import { PageHeader } from '@/components/common/PageHeader'
import { SectionCard } from '@/components/common/SectionCard'
import {
  adminApproveUpgrade,
  adminListUpgradeRequests,
  adminRejectUpgrade,
  type UpgradeRequest,
} from '@/services/billing'
import { cn } from '@/utils/cn'

const STATUS: Record<string, { label: string; cls: string }> = {
  pending: { label: '待审核', cls: 'bg-amber-100 text-amber-800' },
  approved: { label: '已批准', cls: 'bg-green-100 text-green-700' },
  rejected: { label: '已驳回', cls: 'bg-red-100 text-red-700' },
  canceled: { label: '已撤回', cls: 'bg-gray-100 text-gray-500' },
}

export default function UpgradeRequestsPage() {
  const qc = useQueryClient()
  const [filter, setFilter] = useState<string>('pending')
  const [note, setNote] = useState<Record<number, string>>({})

  const list = useQuery({
    queryKey: ['upgrade-requests', 'admin', filter],
    queryFn: () => adminListUpgradeRequests(filter || undefined),
  })

  const approveMut = useMutation({
    mutationFn: ({ id, n }: { id: number; n?: string }) => adminApproveUpgrade(id, n),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['upgrade-requests'] }),
  })
  const rejectMut = useMutation({
    mutationFn: ({ id, n }: { id: number; n?: string }) => adminRejectUpgrade(id, n),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['upgrade-requests'] }),
  })

  const rows = list.data ?? []

  return (
    <div className="p-6 max-w-6xl">
      <PageHeader
        title={<span className="flex items-center gap-2"><Crown className="w-5 h-5 text-amber-500" />套餐升级审批</span>}
        description="审核租户提交的套餐升级申请，批准后自动切换 plan_id。"
        action={
          <select
            value={filter}
            onChange={e => setFilter(e.target.value)}
            className="text-sm border border-gray-200 rounded-md px-2 py-1"
          >
            <option value="">全部</option>
            <option value="pending">待审核</option>
            <option value="approved">已批准</option>
            <option value="rejected">已驳回</option>
          </select>
        }
      />

      <SectionCard title={`申请列表（${rows.length}）`} noPadding>
        {list.isLoading && (
          <div className="py-10 text-center text-sm text-gray-400">
            <Loader2 className="w-4 h-4 inline animate-spin mr-1" />加载中…
          </div>
        )}
        {!list.isLoading && rows.length === 0 && (
          <div className="py-12 text-center text-sm text-gray-400">暂无记录</div>
        )}
        {!list.isLoading && rows.length > 0 && (
          <table className="w-full text-sm">
            <thead className="bg-gray-50/60">
              <tr className="text-left text-xs text-gray-500">
                <th className="px-5 py-3">租户</th>
                <th className="px-3 py-3">升级路径</th>
                <th className="px-3 py-3">联系邮箱</th>
                <th className="px-3 py-3">状态</th>
                <th className="px-3 py-3 text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r: UpgradeRequest) => {
                const st = STATUS[r.status] ?? STATUS.pending
                return (
                  <tr key={r.id} className="border-t border-gray-100">
                    <td className="px-5 py-3">
                      <div className="font-medium text-gray-900">{r.tenant_name}</div>
                      <div className="text-xs text-gray-400">{r.requested_by_username}</div>
                    </td>
                    <td className="px-3 py-3 text-gray-600">
                      {r.from_plan_id} → <b>{r.to_plan_id}</b>
                    </td>
                    <td className="px-3 py-3 text-gray-600">{r.contact_email}</td>
                    <td className="px-3 py-3">
                      <span className={cn('text-xs px-2 py-0.5 rounded-full', st.cls)}>{st.label}</span>
                    </td>
                    <td className="px-3 py-3 text-right">
                      {r.status === 'pending' && (
                        <div className="flex flex-col items-end gap-2">
                          <input
                            type="text"
                            placeholder="审批备注"
                            value={note[r.id] ?? ''}
                            onChange={e => setNote(n => ({ ...n, [r.id]: e.target.value }))}
                            className="text-xs border border-gray-200 rounded px-2 py-1 w-40"
                          />
                          <div className="flex gap-1">
                            <button
                              onClick={() => approveMut.mutate({ id: r.id, n: note[r.id] })}
                              disabled={approveMut.isPending}
                              className="inline-flex items-center gap-0.5 px-2 py-1 text-xs bg-green-600 text-white rounded hover:bg-green-700"
                            >
                              <Check className="w-3 h-3" />批准
                            </button>
                            <button
                              onClick={() => rejectMut.mutate({ id: r.id, n: note[r.id] })}
                              disabled={rejectMut.isPending}
                              className="inline-flex items-center gap-0.5 px-2 py-1 text-xs bg-gray-200 text-gray-700 rounded hover:bg-gray-300"
                            >
                              <X className="w-3 h-3" />驳回
                            </button>
                          </div>
                        </div>
                      )}
                      {r.admin_note && r.status !== 'pending' && (
                        <span className="text-xs text-gray-400">{r.admin_note}</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </SectionCard>
    </div>
  )
}
