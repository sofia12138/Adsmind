import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, CheckCircle2, Layers3, Loader2, Pencil, Plus, Trash2, XCircle } from 'lucide-react'
import { PageHeader } from '@/components/common/PageHeader'
import { SectionCard } from '@/components/common/SectionCard'
import { fetchApplicationSettingsAccess } from '@/services/application-settings'
import {
  createCreativeGroup, deleteCreativeGroup, fetchCreativeGroups, updateCreativeGroup,
  type CreativeGroup, type CreativeGroupMaterialInput,
} from '@/services/creative-groups'
import { getMaterial, listMaterialReferences, type MaterialMaster } from '@/features/material-catalog/api'

const fieldClass = 'w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100'
const errorMessage = (error: unknown) => error instanceof Error ? error.message : '操作失败，请稍后重试'

function GroupDialog({ item, onClose }: { item: CreativeGroup | null; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState(item?.name ?? '')
  const [selections, setSelections] = useState<Map<number, CreativeGroupMaterialInput>>(
    new Map((item?.materials ?? []).map(row => [row.material_id, {
      material_id: row.material_id,
      selection_mode: row.selection_mode,
      selected_version_id: row.selected_version_id,
    }])),
  )
  const references = useQuery({ queryKey: ['material-references'], queryFn: listMaterialReferences })
  const details = useQuery({
    queryKey: ['creative-group-material-details', (references.data?.items ?? []).map(row => row.material_id).join(',')],
    enabled: Boolean(references.data),
    queryFn: async () => {
      const rows = await Promise.all((references.data?.items ?? []).map(row => getMaterial(row.material_id)))
      return new Map(rows.map(row => [row.id, row]))
    },
  })
  const mutation = useMutation({
    mutationFn: () => {
      const body = { name: name.trim(), materials: Array.from(selections.values()) }
      return item ? updateCreativeGroup(item.id, body) : createCreativeGroup(body)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['creative-groups'] })
      onClose()
    },
  })
  const toggle = (materialId: number) => setSelections(current => {
    const next = new Map(current)
    if (next.has(materialId)) next.delete(materialId)
    else next.set(materialId, { material_id: materialId, selection_mode: 'latest', selected_version_id: null })
    return next
  })
  const changeMode = (material: MaterialMaster, mode: 'latest' | 'pinned') => setSelections(current => {
    const next = new Map(current)
    const newest = material.versions?.[0]?.id ?? null
    next.set(material.id, { material_id: material.id, selection_mode: mode, selected_version_id: mode === 'pinned' ? newest : null })
    return next
  })
  const pin = (materialId: number, versionId: number) => setSelections(current => {
    const next = new Map(current)
    next.set(materialId, { material_id: materialId, selection_mode: 'pinned', selected_version_id: versionId })
    return next
  })
  const refs = (references.data?.items ?? []).filter(ref => ref.reference_status === 'selected' && ref.material_status === 'active')

  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-950/35 p-4" onClick={onClose}>
    <form className="flex max-h-[88vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl bg-white shadow-xl" onClick={event => event.stopPropagation()} onSubmit={event => { event.preventDefault(); mutation.mutate() }}>
      <div className="border-b border-gray-100 px-6 py-4"><h2 className="font-semibold text-gray-900">{item ? '编辑创意组' : '新建创意组'}</h2><p className="mt-1 text-xs text-gray-500">只引用当前应用已选择的素材；此处不会创建广告或推送到平台。</p></div>
      <div className="space-y-5 overflow-y-auto p-6">
        <label className="block text-sm font-medium text-gray-700">创意组名称<input autoFocus required maxLength={160} value={name} onChange={event => setName(event.target.value)} className={`mt-1.5 ${fieldClass}`} /></label>
        <div><div className="mb-2 flex items-center justify-between"><span className="text-sm font-medium text-gray-700">素材与版本策略</span><span className="text-xs text-gray-400">已选 {selections.size} 条</span></div>
          <div className="divide-y rounded-xl border border-gray-200">
            {(references.isLoading || details.isLoading) && <div className="p-10 text-center text-sm text-gray-400"><Loader2 className="mr-2 inline h-4 w-4 animate-spin" />加载素材…</div>}
            {!references.isLoading && refs.length === 0 && <div className="p-10 text-center text-sm text-gray-400">请先在素材库把素材加入当前应用</div>}
            {refs.map(ref => {
              const selected = selections.get(ref.material_id)
              const material = details.data?.get(ref.material_id)
              return <div key={ref.material_id} className="p-4">
                <label className="flex cursor-pointer items-start gap-3"><input type="checkbox" checked={Boolean(selected)} onChange={() => toggle(ref.material_id)} className="mt-1 h-4 w-4" /><span className="min-w-0 flex-1"><span className="block text-sm font-medium text-gray-800">{ref.name}</span><span className="text-xs text-gray-400">{ref.material_type} · 当前应用状态 {ref.reference_status === 'selected' ? '已选择' : '已暂停'} · 最新 v{ref.latest_version_number || 0}</span></span></label>
                {selected && material && <div className="mt-3 grid gap-3 pl-7 sm:grid-cols-2"><label className="text-xs text-gray-500">版本策略<select value={selected.selection_mode} onChange={event => changeMode(material, event.target.value as 'latest' | 'pinned')} className={`mt-1 ${fieldClass}`}><option value="latest">跟随最新版本</option><option value="pinned" disabled={!material.versions?.length}>固定版本</option></select></label>{selected.selection_mode === 'pinned' && <label className="text-xs text-gray-500">固定到<select value={selected.selected_version_id ?? ''} onChange={event => pin(material.id, Number(event.target.value))} className={`mt-1 ${fieldClass}`}>{material.versions?.map(version => <option key={version.id} value={version.id}>v{version.version_number} · {version.source_filename} · {version.upload_status === 'uploaded' ? '已上传' : version.upload_status === 'failed' ? '上传失败' : '待上传'}</option>)}</select></label>}</div>}
              </div>
            })}
          </div>
        </div>
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-800">非 uploaded 版本仍可保存为创意组草稿，但会明确显示阻断原因，不能被后续广告创建阶段标记为可投放。</div>
        {mutation.isError && <p className="text-sm text-red-500">{errorMessage(mutation.error)}</p>}
      </div>
      <div className="flex justify-end gap-3 border-t border-gray-100 px-6 py-4"><button type="button" onClick={onClose} className="rounded-lg border px-4 py-2 text-sm text-gray-600">取消</button><button disabled={!name.trim() || selections.size === 0 || mutation.isPending || Array.from(selections.values()).some(row => row.selection_mode === 'pinned' && row.selected_version_id == null)} className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white disabled:opacity-50">保存草稿</button></div>
    </form>
  </div>
}

export default function CreativeGroupsPage() {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<CreativeGroup | null | undefined>(undefined)
  const groups = useQuery({ queryKey: ['creative-groups'], queryFn: fetchCreativeGroups })
  const access = useQuery({ queryKey: ['application-settings-access'], queryFn: fetchApplicationSettingsAccess })
  const remove = useMutation({ mutationFn: deleteCreativeGroup, onSuccess: () => queryClient.invalidateQueries({ queryKey: ['creative-groups'] }) })
  const error = useMemo(() => groups.error || remove.error, [groups.error, remove.error])
  const canWrite = access.data?.can_write ?? false
  return <div className="mx-auto max-w-7xl">
    <PageHeader title="创意组" description="为当前应用组合素材与版本策略；仅 uploaded 版本可供后续投放阶段使用。" action={canWrite && <button onClick={() => setEditing(null)} className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-2 text-sm text-white"><Plus className="h-4 w-4" />新建创意组</button>} />
    {!canWrite && access.data && <div className="mb-4 rounded-xl border border-amber-100 bg-amber-50 px-4 py-3 text-sm text-amber-700">当前应用角色为只读，仅 owner、admin 或 editor 可修改创意组。</div>}
    {error && <div className="mb-4 flex gap-2 rounded-lg bg-red-50 p-3 text-sm text-red-600"><AlertCircle className="h-4 w-4" />{errorMessage(error)}</div>}
    <SectionCard title={`创意组（${groups.data?.length ?? 0}）`} noPadding>
      {groups.isLoading && <div className="py-16 text-center text-gray-400"><Loader2 className="mx-auto h-5 w-5 animate-spin" /></div>}
      {!groups.isLoading && !groups.data?.length && <div className="py-16 text-center text-sm text-gray-400">当前应用还没有创意组</div>}
      {groups.data?.map(group => <div key={group.id} className="flex items-start gap-4 border-b border-gray-100 px-5 py-4 last:border-0">
        <div className={`rounded-xl p-2.5 ${group.can_deliver ? 'bg-emerald-50 text-emerald-600' : 'bg-amber-50 text-amber-600'}`}><Layers3 className="h-5 w-5" /></div>
        <div className="min-w-0 flex-1"><div className="flex items-center gap-2"><span className="font-medium text-gray-900">{group.name}</span>{group.can_deliver ? <span className="flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700"><CheckCircle2 className="h-3 w-3" />可投放</span> : <span className="flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-xs text-amber-700"><XCircle className="h-3 w-3" />草稿阻断</span>}</div>
          <div className="mt-2 flex flex-wrap gap-1.5">{group.materials.map(material => <span key={material.material_id} title={material.blocking_reasons.join('；')} className={`rounded px-2 py-1 text-xs ${material.can_deliver ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-600'}`}>{material.material_name} · {material.selection_mode === 'latest' ? '跟随最新' : `固定 v${material.selected_version_number ?? '?'}`}</span>)}</div>
          {!group.can_deliver && <p className="mt-2 text-xs text-amber-700">阻断原因：{group.blocking_reasons.join('；')}</p>}
        </div>
        <div className="text-xs text-gray-400">{group.materials.length} 条素材</div>
        {canWrite && <div className="flex gap-1"><button title="编辑" onClick={() => setEditing(group)} className="rounded-lg p-2 text-gray-400 hover:bg-blue-50 hover:text-blue-600"><Pencil className="h-4 w-4" /></button><button title="删除" onClick={() => confirm(`确认删除创意组「${group.name}」？`) && remove.mutate(group.id)} className="rounded-lg p-2 text-gray-400 hover:bg-red-50 hover:text-red-500"><Trash2 className="h-4 w-4" /></button></div>}
      </div>)}
    </SectionCard>
    {editing !== undefined && <GroupDialog key={editing?.id ?? 'new'} item={editing} onClose={() => setEditing(undefined)} />}
  </div>
}
