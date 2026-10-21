import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, Braces, Loader2, Pencil, Plus, Trash2, X } from 'lucide-react'
import { PageHeader } from '@/components/common/PageHeader'
import { SectionCard } from '@/components/common/SectionCard'
import {
  createNamingRule, deleteNamingRule, fetchApplicationSettingsAccess, fetchNamingRules,
  updateNamingRule, type NamingRule,
} from '@/services/application-settings'

const FIELDS = ['platform', 'account', 'product', 'country', 'language', 'campaign', 'adgroup', 'creative', 'date']
const SAMPLE: Record<string, string> = { platform: 'TT', account: 'US01', product: 'DramaX', country: 'US', language: 'EN', campaign: 'Launch', adgroup: 'Broad', creative: 'V03', date: '20261021' }

function preview(pattern: string) {
  return pattern.replace(/\{([^{}]+)\}/g, (_, key: string) => SAMPLE[key] ?? `{${key}}`)
}

function RuleDialog({ item, onClose }: { item: NamingRule | null; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState(item?.name ?? '')
  const [pattern, setPattern] = useState(item?.rule.pattern ?? '{platform}_{product}_{country}_{date}')
  const [description, setDescription] = useState(item?.rule.description ?? '')
  const mutation = useMutation({
    mutationFn: () => {
      const body = { name: name.trim(), rule: { pattern: pattern.trim(), description: description.trim() } }
      return item ? updateNamingRule(item.id, body) : createNamingRule(body)
    },
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['naming-rules'] }); onClose() },
  })
  const rendered = useMemo(() => preview(pattern), [pattern])

  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-950/30 p-4">
    <div className="w-full max-w-xl rounded-2xl bg-white shadow-xl">
      <div className="flex items-center justify-between border-b border-gray-100 px-6 py-4">
        <h2 className="font-semibold text-gray-900">{item ? '编辑命名规则' : '新建命名规则'}</h2>
        <button onClick={onClose} className="rounded-lg p-1 text-gray-400 hover:bg-gray-100"><X className="h-4 w-4" /></button>
      </div>
      <form className="space-y-5 p-6" onSubmit={event => { event.preventDefault(); mutation.mutate() }}>
        <div><label className="mb-1.5 block text-sm font-medium text-gray-700">规则名称</label><input autoFocus value={name} onChange={event => setName(event.target.value)} maxLength={160} className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-100" placeholder="例如：TikTok 广告系列命名" /></div>
        <div>
          <label className="mb-1.5 block text-sm font-medium text-gray-700">命名模板</label>
          <input value={pattern} onChange={event => setPattern(event.target.value)} maxLength={300} className="w-full rounded-lg border border-gray-200 px-3 py-2 font-mono text-sm outline-none focus:ring-2 focus:ring-blue-100" />
          <div className="mt-2 flex flex-wrap gap-1.5">{FIELDS.map(field => <button type="button" key={field} onClick={() => setPattern(value => `${value}{${field}}`)} className="rounded-md bg-gray-100 px-2 py-1 font-mono text-[11px] text-gray-600 hover:bg-blue-50 hover:text-blue-600">{`{${field}}`}</button>)}</div>
        </div>
        <div className="rounded-xl border border-blue-100 bg-blue-50/60 p-4"><div className="mb-1 text-xs font-medium text-blue-600">示例预览</div><div className="break-all font-mono text-sm text-gray-800">{rendered || '—'}</div></div>
        <div><label className="mb-1.5 block text-sm font-medium text-gray-700">规则说明</label><textarea value={description} onChange={event => setDescription(event.target.value)} maxLength={500} rows={3} className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-100" placeholder="说明适用范围或团队约定（可选）" /></div>
        {mutation.isError && <p className="text-sm text-red-500">{mutation.error instanceof Error ? mutation.error.message : '保存失败'}</p>}
        <div className="flex justify-end gap-3"><button type="button" onClick={onClose} className="rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-600">取消</button><button disabled={!name.trim() || !pattern.trim() || mutation.isPending} className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white disabled:opacity-50">{mutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}保存</button></div>
      </form>
    </div>
  </div>
}

export default function NamingRulesPage() {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<NamingRule | null | undefined>(undefined)
  const { data: rules = [], isLoading, isError } = useQuery({ queryKey: ['naming-rules'], queryFn: fetchNamingRules })
  const { data: access } = useQuery({ queryKey: ['application-settings-access'], queryFn: fetchApplicationSettingsAccess })
  const remove = useMutation({ mutationFn: deleteNamingRule, onSuccess: () => queryClient.invalidateQueries({ queryKey: ['naming-rules'] }) })
  const canWrite = access?.can_write ?? false

  return <div className="mx-auto max-w-7xl">
    <PageHeader title="命名规则" description="为当前应用维护可复用的广告资产命名模板；这里只保存规则，不会创建或推送广告。" action={canWrite && <button onClick={() => setEditing(null)} className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-2 text-sm text-white"><Plus className="h-4 w-4" />新建规则</button>} />
    {!canWrite && access && <div className="mb-4 rounded-xl border border-amber-100 bg-amber-50 px-4 py-3 text-sm text-amber-700">当前应用角色为只读，仅 owner、admin 或 editor 可修改命名规则。</div>}
    <SectionCard title={`命名规则（${rules.length}）`} noPadding>
      {isLoading && <div className="flex justify-center py-16 text-gray-400"><Loader2 className="h-5 w-5 animate-spin" /></div>}
      {isError && <div className="flex items-center justify-center gap-2 py-16 text-sm text-red-500"><AlertCircle className="h-5 w-5" />命名规则加载失败</div>}
      {!isLoading && !isError && rules.length === 0 && <div className="py-16 text-center text-sm text-gray-400">当前应用还没有命名规则</div>}
      {rules.map(rule => <div key={rule.id} className="flex items-center gap-4 border-b border-gray-100 px-5 py-4 last:border-0">
        <div className="rounded-xl bg-violet-50 p-2.5 text-violet-600"><Braces className="h-5 w-5" /></div>
        <div className="min-w-0 flex-1"><div className="font-medium text-gray-900">{rule.name}</div><div className="mt-1 truncate font-mono text-xs text-gray-500">{rule.rule.pattern}</div>{rule.rule.description && <div className="mt-1 truncate text-xs text-gray-400">{rule.rule.description}</div>}</div>
        <div className="hidden max-w-xs truncate rounded-lg bg-gray-50 px-3 py-1.5 font-mono text-xs text-gray-600 lg:block">{preview(rule.rule.pattern)}</div>
        {canWrite && <div className="flex gap-1"><button onClick={() => setEditing(rule)} className="rounded-lg p-2 text-gray-400 hover:bg-blue-50 hover:text-blue-600"><Pencil className="h-4 w-4" /></button><button onClick={() => confirm(`确认删除命名规则「${rule.name}」？`) && remove.mutate(rule.id)} className="rounded-lg p-2 text-gray-400 hover:bg-red-50 hover:text-red-500"><Trash2 className="h-4 w-4" /></button></div>}
      </div>)}
    </SectionCard>
    {editing !== undefined && <RuleDialog item={editing} onClose={() => setEditing(undefined)} />}
  </div>
}
