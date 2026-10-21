import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, FolderCog, Loader2, Pencil, Plus, Trash2, X } from 'lucide-react'
import { PageHeader } from '@/components/common/PageHeader'
import { SectionCard } from '@/components/common/SectionCard'
import { fetchAdAccounts } from '@/services/accounts-mgmt'
import {
  createAccountGroup, deleteAccountGroup, fetchAccountGroups,
  fetchApplicationSettingsAccess, updateAccountGroup,
  type AccountGroup, type AccountRef,
} from '@/services/application-settings'

function message(error: unknown) {
  return error instanceof Error ? error.message : '保存失败，请稍后重试'
}

function GroupDialog({ item, onClose }: { item: AccountGroup | null; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState(item?.name ?? '')
  const [selected, setSelected] = useState<Set<string>>(
    new Set((item?.account_refs ?? []).map(ref => `${ref.platform}:${ref.account_id}`)),
  )
  const { data: accountResult, isLoading } = useQuery({
    queryKey: ['ad-accounts', 'account-group-picker'], queryFn: () => fetchAdAccounts(),
  })
  const mutation = useMutation({
    mutationFn: () => {
      const refs: AccountRef[] = (accountResult?.data ?? [])
        .filter(account => selected.has(`${account.platform}:${account.account_id}`))
        .map(account => ({ platform: account.platform, account_id: account.account_id }))
      const body = { name: name.trim(), account_refs: refs }
      return item ? updateAccountGroup(item.id, body) : createAccountGroup(body)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['account-groups'] })
      onClose()
    },
  })
  const toggle = (key: string) => setSelected(current => {
    const next = new Set(current)
    if (next.has(key)) next.delete(key); else next.add(key)
    return next
  })

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-950/30 p-4">
      <div className="w-full max-w-xl rounded-2xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-gray-100 px-6 py-4">
          <h2 className="font-semibold text-gray-900">{item ? '编辑账户组' : '新建账户组'}</h2>
          <button onClick={onClose} className="rounded-lg p-1 text-gray-400 hover:bg-gray-100"><X className="h-4 w-4" /></button>
        </div>
        <form className="space-y-5 p-6" onSubmit={event => { event.preventDefault(); mutation.mutate() }}>
          <div>
            <label className="mb-1.5 block text-sm font-medium text-gray-700">账户组名称</label>
            <input autoFocus value={name} onChange={event => setName(event.target.value)} maxLength={160}
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-100" placeholder="例如：北美 TikTok 主账户" />
          </div>
          <div>
            <div className="mb-2 flex items-center justify-between">
              <label className="text-sm font-medium text-gray-700">选择当前应用的广告账户</label>
              <span className="text-xs text-gray-400">已选 {selected.size} 个</span>
            </div>
            <div className="max-h-64 overflow-y-auto rounded-xl border border-gray-200">
              {isLoading && <div className="p-8 text-center text-sm text-gray-400">加载账户中…</div>}
              {!isLoading && (accountResult?.data.length ?? 0) === 0 && (
                <div className="p-8 text-center text-sm text-gray-400">当前应用尚未绑定广告账户</div>
              )}
              {accountResult?.data.map(account => {
                const key = `${account.platform}:${account.account_id}`
                return <label key={key} className="flex cursor-pointer items-center gap-3 border-b border-gray-100 px-4 py-3 last:border-0 hover:bg-blue-50/40">
                  <input type="checkbox" checked={selected.has(key)} onChange={() => toggle(key)} className="h-4 w-4 rounded border-gray-300" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-gray-800">{account.account_name || account.account_id}</div>
                    <div className="text-xs text-gray-400">{account.platform.toUpperCase()} · {account.account_id}</div>
                  </div>
                </label>
              })}
            </div>
          </div>
          {mutation.isError && <p className="text-sm text-red-500">{message(mutation.error)}</p>}
          <div className="flex justify-end gap-3">
            <button type="button" onClick={onClose} className="rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-600">取消</button>
            <button disabled={!name.trim() || selected.size === 0 || mutation.isPending} className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white disabled:opacity-50">
              {mutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}保存
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function AccountGroupsPage() {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<AccountGroup | null | undefined>(undefined)
  const { data: groups = [], isLoading, isError } = useQuery({ queryKey: ['account-groups'], queryFn: fetchAccountGroups })
  const { data: access } = useQuery({ queryKey: ['application-settings-access'], queryFn: fetchApplicationSettingsAccess })
  const remove = useMutation({
    mutationFn: deleteAccountGroup,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['account-groups'] }),
  })
  const canWrite = access?.can_write ?? false

  return <div className="mx-auto max-w-7xl">
    <PageHeader title="账户组" description="按当前应用组织已绑定的广告账户；组内不能引用其他应用的账户。"
      action={canWrite && <button onClick={() => setEditing(null)} className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-2 text-sm text-white"><Plus className="h-4 w-4" />新建账户组</button>} />
    {!canWrite && access && <div className="mb-4 rounded-xl border border-amber-100 bg-amber-50 px-4 py-3 text-sm text-amber-700">当前应用角色为只读，仅 owner、admin 或 editor 可修改账户组。</div>}
    <SectionCard title={`账户组（${groups.length}）`} noPadding>
      {isLoading && <div className="flex justify-center py-16 text-gray-400"><Loader2 className="h-5 w-5 animate-spin" /></div>}
      {isError && <div className="flex items-center justify-center gap-2 py-16 text-sm text-red-500"><AlertCircle className="h-5 w-5" />账户组加载失败</div>}
      {!isLoading && !isError && groups.length === 0 && <div className="py-16 text-center text-sm text-gray-400">当前应用还没有账户组</div>}
      {groups.map(group => <div key={group.id} className="flex items-center gap-4 border-b border-gray-100 px-5 py-4 last:border-0">
        <div className="rounded-xl bg-blue-50 p-2.5 text-blue-600"><FolderCog className="h-5 w-5" /></div>
        <div className="min-w-0 flex-1">
          <div className="font-medium text-gray-900">{group.name}</div>
          <div className="mt-1 flex flex-wrap gap-1.5">{group.account_refs.map(ref => <span key={`${ref.platform}:${ref.account_id}`} className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600">{ref.platform.toUpperCase()} · {ref.account_id}</span>)}</div>
        </div>
        <div className="text-xs text-gray-400">{group.account_refs.length} 个账户</div>
        {canWrite && <div className="flex gap-1">
          <button onClick={() => setEditing(group)} className="rounded-lg p-2 text-gray-400 hover:bg-blue-50 hover:text-blue-600"><Pencil className="h-4 w-4" /></button>
          <button onClick={() => confirm(`确认删除账户组「${group.name}」？`) && remove.mutate(group.id)} className="rounded-lg p-2 text-gray-400 hover:bg-red-50 hover:text-red-500"><Trash2 className="h-4 w-4" /></button>
        </div>}
      </div>)}
    </SectionCard>
    {editing !== undefined && <GroupDialog item={editing} onClose={() => setEditing(undefined)} />}
  </div>
}
