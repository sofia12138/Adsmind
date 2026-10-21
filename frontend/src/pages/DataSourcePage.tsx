import { useState } from 'react'
import { Link } from 'react-router-dom'
import { PageHeader } from '@/components/common/PageHeader'
import { SectionCard } from '@/components/common/SectionCard'
import { FilterBar } from '@/components/common/FilterBar'
import {
  Database, Plus, Trash2, Star, RefreshCw, CheckCircle2, XCircle,
} from 'lucide-react'
import type { AdAccount } from '@/services/accounts-mgmt'
import { fetchAdAccounts, deleteAdAccount, setDefaultAccount } from '@/services/accounts-mgmt'
import AddAccountModal from '@/components/account/AddAccountModal'
import { GlobalSyncBar } from '@/components/common/GlobalSyncBar'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '@/contexts/AuthContext'

const PLATFORM_LABEL: Record<string, string> = { tiktok: 'TikTok', meta: 'Meta' }
const STATUS_STYLE: Record<string, string> = {
  ACTIVE: 'bg-green-50 text-green-700',
  DISABLED: 'bg-red-50 text-red-600',
  PAUSED: 'bg-yellow-50 text-yellow-700',
}

export default function DataSourcePage() {
  const queryClient = useQueryClient()
  const { currentApplication } = useAuth()
  const [error, setError] = useState('')
  const [filter, setFilter] = useState<string>('')
  const [showAdd, setShowAdd] = useState(false)
  const [deleting, setDeleting] = useState<number | null>(null)

  const accountQuery = useQuery({
    queryKey: ['ad-accounts', currentApplication?.id, filter],
    queryFn: () => fetchAdAccounts(filter || undefined),
    enabled: !!currentApplication,
  })
  const accounts: AdAccount[] = accountQuery.data?.data ?? []
  const loading = accountQuery.isPending || accountQuery.isFetching
  const load = async () => {
    setError('')
    await accountQuery.refetch()
  }

  const handleDelete = async (id: number) => {
    if (!confirm('确定删除此账户？删除后不可恢复。')) return
    setDeleting(id)
    try {
      await deleteAdAccount(id)
      await load()
    } catch (e: unknown) { setError(e instanceof Error ? e.message : '删除失败') }
    setDeleting(null)
  }

  const handleSetDefault = async (id: number) => {
    try {
      await setDefaultAccount(id)
      await load()
    } catch (e: unknown) { setError(e instanceof Error ? e.message : '设置默认账号失败') }
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <PageHeader
        title="数据源配置"
        description="管理 TikTok / Meta 广告账户连接，添加新账户后可同步投放数据"
        action={<div className="flex items-center gap-3"><Link to="/settings/integrations" className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm">授权连接</Link>
          <button
            onClick={() => setShowAdd(true)}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium bg-blue-600 text-white hover:bg-blue-700 transition"
          >
            <Plus className="w-4 h-4" /> 手动连接
          </button>
        </div>}
      />

      <p className="text-sm text-gray-500">当前应用：{currentApplication?.name ?? '加载中…'}。完成连接后，点击「立即同步」读取投放数据。</p>
      {(error || accountQuery.error) && <p role="alert" className="text-sm text-red-600 bg-red-50 p-3 rounded-lg">{error || accountQuery.error?.message}</p>}
      {accounts.length > 0 && <GlobalSyncBar defaultExpanded />}

      <FilterBar>
        <Database className="w-3.5 h-3.5 text-gray-400" />
        <span className="text-xs text-gray-500">平台筛选</span>
        <div className="flex rounded-lg border border-gray-200 overflow-hidden text-xs">
          {[
            { id: '', label: '全部' },
            { id: 'tiktok', label: 'TikTok' },
            { id: 'meta', label: 'Meta' },
          ].map(p => (
            <button
              key={p.id}
              onClick={() => setFilter(p.id)}
              className={`px-3 py-1.5 transition ${
                filter === p.id
                  ? 'bg-blue-500 text-white font-medium'
                  : 'bg-white text-gray-600 hover:bg-gray-50'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
        <div className="flex-1" />
        <button
          onClick={load}
          className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-blue-600 transition"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> 刷新
        </button>
      </FilterBar>

      <SectionCard title={`账户列表（共 ${accounts.length} 个）`} noPadding>
        {loading ? (
          <div className="flex items-center justify-center py-16 text-gray-400 text-sm">加载中...</div>
        ) : accounts.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-gray-400">
            <Database className="w-10 h-10 mb-3 text-gray-300" strokeWidth={1.2} />
            <p className="text-sm">暂无广告账户</p>
            <p className="text-xs mt-1 text-gray-300">点击"添加账户"开始配置</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/60">
                  <th className="text-left px-4 py-2.5 font-medium text-gray-500 text-xs">平台</th>
                  <th className="text-left px-4 py-2.5 font-medium text-gray-500 text-xs">账户 ID</th>
                  <th className="text-left px-4 py-2.5 font-medium text-gray-500 text-xs">名称</th>
                  <th className="text-left px-4 py-2.5 font-medium text-gray-500 text-xs">Token</th>
                  <th className="text-left px-4 py-2.5 font-medium text-gray-500 text-xs">货币</th>
                  <th className="text-left px-4 py-2.5 font-medium text-gray-500 text-xs">状态</th>
                  <th className="text-left px-4 py-2.5 font-medium text-gray-500 text-xs">默认</th>
                  <th className="text-left px-4 py-2.5 font-medium text-gray-500 text-xs">上次同步</th>
                  <th className="text-left px-4 py-2.5 font-medium text-gray-500 text-xs">操作</th>
                </tr>
              </thead>
              <tbody>
                {accounts.map(a => (
                  <tr key={a.id} className="border-b border-gray-50 hover:bg-gray-50/40 transition">
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-semibold ${
                        a.platform === 'tiktok' ? 'bg-gray-900 text-white' : 'bg-blue-600 text-white'
                      }`}>
                        {PLATFORM_LABEL[a.platform] || a.platform}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-600">{a.account_id}</td>
                    <td className="px-4 py-3 text-gray-800">{a.account_name || '-'}</td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-400">{a.access_token_masked || '-'}</td>
                    <td className="px-4 py-3 text-gray-600">{a.currency}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium ${STATUS_STYLE[a.status] || 'bg-gray-100 text-gray-600'}`}>
                        {a.status === 'ACTIVE' ? <CheckCircle2 className="w-3 h-3" /> : <XCircle className="w-3 h-3" />}
                        {a.status}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {a.is_default ? (
                        <Star className="w-4 h-4 text-yellow-500 fill-yellow-400" />
                      ) : (
                        <button
                          onClick={() => handleSetDefault(a.id)}
                          className="text-gray-300 hover:text-yellow-500 transition"
                          title="设为默认"
                        >
                          <Star className="w-4 h-4" />
                        </button>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-400">
                      {a.last_synced_at || '从未同步'}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => handleDelete(a.id)}
                          disabled={deleting === a.id}
                          className="text-gray-400 hover:text-red-500 transition disabled:opacity-50"
                          title="删除"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>

      {showAdd && (
        <AddAccountModal
          onClose={() => { setShowAdd(false); load() }}
          onSuccess={() => {
            setShowAdd(false); load()
            queryClient.invalidateQueries({ queryKey: ['biz'] })
            queryClient.invalidateQueries({ queryKey: ['ad-accounts'] })
          }}
        />
      )}
    </div>
  )
}
