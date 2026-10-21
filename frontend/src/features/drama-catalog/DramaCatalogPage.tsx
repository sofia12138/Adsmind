import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, CalendarDays, Film, Languages, Loader2, Pencil, Plus, Search, Trash2, X } from 'lucide-react'
import { PageHeader } from '@/components/common/PageHeader'
import { createMaster, deleteMaster, listMasters, updateMaster, type CatalogType, type DramaMaster, type MasterInput } from './api'

const labels: Record<CatalogType, string> = { self_operated: '自营剧单', distribution: '分销剧单' }

function emptyForm(catalogType: CatalogType): MasterInput {
  return { catalog_type: catalogType, title: '', chinese_title: '', language: '', launched_at: null }
}

function DramaDialog({ item, defaultType, saving, onClose, onSave }: {
  item?: DramaMaster | null
  defaultType: CatalogType
  saving: boolean
  onClose: () => void
  onSave: (value: MasterInput) => void
}) {
  const [form, setForm] = useState<MasterInput>(item ? {
    catalog_type: item.catalog_type,
    title: item.title,
    chinese_title: item.chinese_title,
    language: item.language,
    launched_at: item.launched_at,
  } : emptyForm(defaultType))
  const field = (key: keyof MasterInput) => (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm(current => ({ ...current, [key]: event.target.value || (key === 'launched_at' ? null : '') }))

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 p-4" onClick={onClose}>
      <form className="w-full max-w-lg overflow-hidden rounded-2xl bg-white shadow-2xl" onClick={event => event.stopPropagation()} onSubmit={event => { event.preventDefault(); onSave(form) }}>
        <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
          <div><h2 className="text-base font-semibold text-slate-900">{item ? '编辑剧目' : '新增剧目'}</h2><p className="mt-0.5 text-xs text-slate-400">仅维护剧单展示所需信息</p></div>
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100"><X className="h-4 w-4" /></button>
        </div>
        <div className="space-y-4 px-6 py-5">
          <label className="block text-sm font-medium text-slate-600">剧单类型
            <select required value={form.catalog_type} onChange={field('catalog_type')} className="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100"><option value="self_operated">自营剧单</option><option value="distribution">分销剧单</option></select>
          </label>
          <label className="block text-sm font-medium text-slate-600">剧名 <span className="text-rose-500">*</span>
            <input required value={form.title} onChange={field('title')} placeholder="例如：The Billionaire's Secret" className="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100" />
          </label>
          <label className="block text-sm font-medium text-slate-600">中文剧名 <span className="text-rose-500">*</span>
            <input required value={form.chinese_title} onChange={field('chinese_title')} placeholder="例如：亿万富翁的秘密" className="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100" />
          </label>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block text-sm font-medium text-slate-600">语种 <span className="text-rose-500">*</span>
              <input required value={form.language} onChange={field('language')} placeholder="英语" className="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100" />
            </label>
            <label className="block text-sm font-medium text-slate-600">上线时间
              <input type="date" value={form.launched_at || ''} onChange={field('launched_at')} className="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100" />
            </label>
          </div>
        </div>
        <div className="flex justify-end gap-3 border-t border-slate-100 bg-slate-50/60 px-6 py-4">
          <button type="button" onClick={onClose} className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-slate-600 hover:bg-slate-50">取消</button>
          <button disabled={saving} className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-white hover:bg-blue-700 disabled:opacity-50">{saving && <Loader2 className="h-4 w-4 animate-spin" />}{item ? '保存' : '新增'}</button>
        </div>
      </form>
    </div>
  )
}

function Empty({ catalogType }: { catalogType: CatalogType }) {
  return <div className="flex flex-col items-center py-20 text-center"><div className="rounded-2xl bg-slate-50 p-4"><Film className="h-7 w-7 text-slate-300" /></div><p className="mt-4 text-sm font-medium text-slate-500">暂无{labels[catalogType]}</p><p className="mt-1 text-xs text-slate-400">点击右上角新增第一部剧目</p></div>
}

export default function DramaCatalogPage() {
  const [catalogType, setCatalogType] = useState<CatalogType>('self_operated')
  const [keyword, setKeyword] = useState('')
  const [editing, setEditing] = useState<DramaMaster | null | undefined>(undefined)
  const queryClient = useQueryClient()
  const list = useQuery({ queryKey: ['drama-catalog', catalogType, keyword], queryFn: () => listMasters(catalogType, keyword) })
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['drama-catalog'] })
  const create = useMutation({ mutationFn: createMaster, onSuccess: () => { refresh(); setEditing(undefined) } })
  const update = useMutation({ mutationFn: ({ item, input }: { item: DramaMaster; input: MasterInput }) => updateMaster(item, input), onSuccess: () => { refresh(); setEditing(undefined) } })
  const remove = useMutation({ mutationFn: deleteMaster, onSuccess: refresh })
  const error = [create.error, update.error, remove.error, list.error].find(Boolean) as Error | undefined

  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader title="剧目库" description="集中展示自营与分销剧单的基础上线信息" />
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex rounded-lg bg-slate-100 p-1">{(Object.keys(labels) as CatalogType[]).map(type => <button key={type} onClick={() => { setCatalogType(type); setKeyword('') }} className={`rounded-md px-5 py-1.5 text-sm transition ${catalogType === type ? 'bg-white font-medium text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}>{labels[type]}</button>)}</div>
        <div className="flex gap-2"><div className="relative"><Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" /><input value={keyword} onChange={event => setKeyword(event.target.value)} placeholder="搜索剧名或中文剧名" className="w-64 rounded-lg border border-slate-200 bg-white py-2 pl-9 pr-3 text-sm outline-none focus:border-blue-400" /></div><button onClick={() => setEditing(null)} className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-3.5 py-2 text-sm text-white hover:bg-blue-700"><Plus className="h-4 w-4" />新增剧目</button></div>
      </div>
      {error && <div className="mb-4 flex items-center gap-2 rounded-lg border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-600"><AlertCircle className="h-4 w-4" />{error.message}</div>}
      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        {list.isLoading ? <div className="flex justify-center py-24 text-slate-400"><Loader2 className="mr-2 h-5 w-5 animate-spin" />加载中</div> : (list.data?.items.length || 0) === 0 ? <Empty catalogType={catalogType} /> : <div className="overflow-x-auto"><table className="w-full"><thead className="border-b border-slate-100 bg-slate-50/70"><tr><th className="px-5 py-3 text-left">剧名</th><th className="px-5 py-3 text-left">中文剧名</th><th className="px-5 py-3 text-left">语种</th><th className="px-5 py-3 text-left">上线时间</th><th className="px-5 py-3 text-right">操作</th></tr></thead><tbody className="divide-y divide-slate-100">{list.data?.items.map(item => <tr key={item.id} className="hover:bg-slate-50/60"><td className="px-5 py-4 font-medium text-slate-800">{item.title}</td><td className="px-5 py-4 text-slate-600">{item.chinese_title}</td><td className="px-5 py-4"><span className="inline-flex items-center gap-1.5 rounded-md bg-indigo-50 px-2 py-1 text-xs text-indigo-600"><Languages className="h-3 w-3" />{item.language}</span></td><td className="px-5 py-4 text-slate-500"><span className="inline-flex items-center gap-1.5"><CalendarDays className="h-3.5 w-3.5 text-slate-300" />{item.launched_at || '待定'}</span></td><td className="px-5 py-4"><div className="flex justify-end gap-1"><button title="编辑" onClick={() => setEditing(item)} className="rounded-lg p-2 text-slate-400 hover:bg-blue-50 hover:text-blue-600"><Pencil className="h-4 w-4" /></button><button title="删除" onClick={() => confirm(`确认删除剧目「${item.chinese_title}」？`) && remove.mutate(item.id)} className="rounded-lg p-2 text-slate-400 hover:bg-rose-50 hover:text-rose-600"><Trash2 className="h-4 w-4" /></button></div></td></tr>)}</tbody></table></div>}
      </div>
      {editing !== undefined && <DramaDialog item={editing} defaultType={catalogType} saving={create.isPending || update.isPending} onClose={() => setEditing(undefined)} onSave={input => editing ? update.mutate({ item: editing, input }) : create.mutate(input)} />}
    </div>
  )
}
