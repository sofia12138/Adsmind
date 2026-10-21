import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle, BookOpen, Check, Film, Link2, Loader2, Pencil, Plus,
  Search, Trash2, Unlink, X,
} from 'lucide-react'
import { PageHeader } from '@/components/common/PageHeader'
import { fetchApplicationSettingsAccess } from '@/services/application-settings'
import {
  attachDrama, createMaster, deleteMaster, detachDrama, listMasters, listReferences,
  updateMaster, updateReference, type ApplicationDrama, type DramaMaster, type MasterInput,
} from './api'

const blank: MasterInput = {
  title: '', aliases: [], original_language: '', region: '', genres: [], synopsis: '', cover_url: '',
}

function splitTags(value: string) {
  return value.split(/[,，\n]/).map(item => item.trim()).filter(Boolean)
}

function Dialog({ item, onClose, onSave, saving }: {
  item?: DramaMaster | null
  onClose: () => void
  onSave: (input: MasterInput) => void
  saving: boolean
}) {
  const [form, setForm] = useState<MasterInput>(item ? {
    title: item.title, aliases: item.aliases, original_language: item.original_language,
    region: item.region, genres: item.genres, synopsis: item.synopsis, cover_url: item.cover_url,
  } : blank)
  const [aliases, setAliases] = useState(form.aliases.join('，'))
  const [genres, setGenres] = useState(form.genres.join('，'))

  const field = (key: keyof MasterInput) => (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm(current => ({ ...current, [key]: event.target.value }))

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 p-4" onClick={onClose}>
      <div className="w-full max-w-2xl overflow-hidden rounded-2xl bg-white shadow-2xl" onClick={event => event.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
          <div>
            <h2 className="text-base font-semibold text-slate-900">{item ? '编辑剧目主档' : '新建剧目主档'}</h2>
            <p className="mt-0.5 text-xs text-slate-400">主档属于当前租户，可被租户内不同应用引用</p>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100"><X className="h-4 w-4" /></button>
        </div>
        <form className="max-h-[76vh] space-y-4 overflow-y-auto px-6 py-5" onSubmit={event => {
          event.preventDefault()
          onSave({ ...form, aliases: splitTags(aliases), genres: splitTags(genres) })
        }}>
          <label className="block text-sm font-medium text-slate-600">剧名 <span className="text-rose-500">*</span>
            <input required value={form.title} onChange={field('title')} placeholder="例如：The Billionaire's Secret"
              className="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100" />
          </label>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block text-sm font-medium text-slate-600">别名
              <input value={aliases} onChange={event => setAliases(event.target.value)} placeholder="中文名，平台译名"
                className="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100" />
            </label>
            <label className="block text-sm font-medium text-slate-600">类型
              <input value={genres} onChange={event => setGenres(event.target.value)} placeholder="爱情，逆袭"
                className="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100" />
            </label>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block text-sm font-medium text-slate-600">原始语言
              <input value={form.original_language} onChange={field('original_language')} placeholder="zh-CN"
                className="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100" />
            </label>
            <label className="block text-sm font-medium text-slate-600">地区
              <input value={form.region} onChange={field('region')} placeholder="中国大陆"
                className="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100" />
            </label>
          </div>
          <label className="block text-sm font-medium text-slate-600">封面 URL
            <input type="url" value={form.cover_url} onChange={field('cover_url')} placeholder="https://..."
              className="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100" />
          </label>
          <label className="block text-sm font-medium text-slate-600">简介
            <textarea rows={4} value={form.synopsis} onChange={field('synopsis')} placeholder="剧目简介与核心卖点"
              className="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100" />
          </label>
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="rounded-lg border border-slate-200 px-4 py-2 text-slate-600 hover:bg-slate-50">取消</button>
            <button disabled={saving} className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-white hover:bg-blue-700 disabled:opacity-50">
              {saving && <Loader2 className="h-4 w-4 animate-spin" />}{item ? '保存修改' : '创建主档'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function ReferenceDialog({ item, onClose, onSave, saving }: {
  item: ApplicationDrama
  onClose: () => void
  onSave: (value: { display_title: string; status: 'active' | 'paused'; notes: string }) => void
  saving: boolean
}) {
  const [displayTitle, setDisplayTitle] = useState(item.display_title)
  const [status, setStatus] = useState<'active' | 'paused'>(item.reference_status)
  const [notes, setNotes] = useState(item.notes || '')
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 p-4" onClick={onClose}>
      <form className="w-full max-w-lg space-y-4 rounded-2xl bg-white p-6 shadow-2xl" onClick={e => e.stopPropagation()} onSubmit={e => { e.preventDefault(); onSave({ display_title: displayTitle, status, notes }) }}>
        <div><h2 className="text-base font-semibold text-slate-900">应用引用设置</h2><p className="mt-1 text-xs text-slate-400">{item.title} · 仅影响当前应用</p></div>
        <label className="block text-sm font-medium text-slate-600">应用内展示名
          <input value={displayTitle} onChange={e => setDisplayTitle(e.target.value)} placeholder="留空则使用主档剧名" className="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2" />
        </label>
        <label className="block text-sm font-medium text-slate-600">引用状态
          <select value={status} onChange={e => setStatus(e.target.value as 'active' | 'paused')} className="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2">
            <option value="active">使用中</option><option value="paused">已暂停</option>
          </select>
        </label>
        <label className="block text-sm font-medium text-slate-600">应用备注
          <textarea rows={3} value={notes} onChange={e => setNotes(e.target.value)} className="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2" />
        </label>
        <div className="flex justify-end gap-3"><button type="button" onClick={onClose} className="rounded-lg border border-slate-200 px-4 py-2">取消</button><button disabled={saving} className="rounded-lg bg-blue-600 px-4 py-2 text-white disabled:opacity-50">保存设置</button></div>
      </form>
    </div>
  )
}

function Empty({ references }: { references: boolean }) {
  return <div className="flex flex-col items-center py-20 text-center"><div className="rounded-2xl bg-slate-50 p-4"><Film className="h-7 w-7 text-slate-300" /></div><p className="mt-4 text-sm font-medium text-slate-500">{references ? '当前应用还没有引用剧目' : '当前租户还没有剧目主档'}</p><p className="mt-1 text-xs text-slate-400">{references ? '在租户主档中点击“加入应用”' : '创建第一条剧目主档开始管理'}</p></div>
}

export default function DramaCatalogPage() {
  const [tab, setTab] = useState<'masters' | 'references'>('masters')
  const [keyword, setKeyword] = useState('')
  const [editing, setEditing] = useState<DramaMaster | null | undefined>(undefined)
  const [referenceEditing, setReferenceEditing] = useState<ApplicationDrama | null>(null)
  const qc = useQueryClient()
  const access = useQuery({ queryKey: ['application-settings-access'], queryFn: fetchApplicationSettingsAccess })
  const canWrite = access.data?.can_write === true
  const masters = useQuery({ queryKey: ['drama-masters', keyword], queryFn: () => listMasters(keyword), enabled: tab === 'masters' })
  const referenceIndex = useQuery({ queryKey: ['application-dramas', 'index'], queryFn: () => listReferences('') })
  const references = useQuery({ queryKey: ['application-dramas', keyword], queryFn: () => listReferences(keyword), enabled: tab === 'references' })
  const attached = useMemo(() => new Set((referenceIndex.data?.items || []).map(row => row.drama_id)), [referenceIndex.data])
  const refresh = () => { qc.invalidateQueries({ queryKey: ['drama-masters'] }); qc.invalidateQueries({ queryKey: ['application-dramas'] }) }
  const create = useMutation({ mutationFn: createMaster, onSuccess: () => { refresh(); setEditing(undefined) } })
  const update = useMutation({ mutationFn: ({ item, input }: { item: DramaMaster; input: MasterInput }) => updateMaster(item, input), onSuccess: () => { refresh(); setEditing(undefined) } })
  const remove = useMutation({ mutationFn: deleteMaster, onSuccess: refresh })
  const attach = useMutation({ mutationFn: attachDrama, onSuccess: refresh })
  const detach = useMutation({ mutationFn: detachDrama, onSuccess: refresh })
  const updateRef = useMutation({ mutationFn: ({ id, value }: { id: number; value: Parameters<typeof updateReference>[1] }) => updateReference(id, value), onSuccess: () => { refresh(); setReferenceEditing(null) } })
  const result = tab === 'masters' ? masters : references
  const error = [create.error, update.error, remove.error, attach.error, detach.error, updateRef.error, result.error].find(Boolean) as Error | undefined

  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader title="剧目库" description="统一维护租户剧目主档，并为当前应用选择可用剧目；切换应用后引用列表随之切换" />
      <div className="mb-5 rounded-xl border border-blue-100 bg-gradient-to-r from-blue-50 to-indigo-50 px-4 py-3 text-xs text-blue-700">
        <span className="font-semibold">隔离说明：</span> 主档在当前租户内共享；“应用剧目”只属于当前应用。移除应用引用不会删除租户主档。
      </div>
      {!canWrite && access.data && <div className="mb-4 rounded-xl border border-amber-100 bg-amber-50 px-4 py-3 text-sm text-amber-700">当前应用角色为只读，仅 owner、admin 或 editor 可创建、编辑、引用或删除剧目。</div>}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex rounded-lg bg-slate-100 p-1">
          {([['masters', '租户主档'], ['references', '应用剧目']] as const).map(([key, label]) => <button key={key} onClick={() => { setTab(key); setKeyword('') }} className={`rounded-md px-4 py-1.5 text-sm transition ${tab === key ? 'bg-white font-medium text-slate-900 shadow-sm' : 'text-slate-500'}`}>{label}</button>)}
        </div>
        <div className="flex gap-2">
          <div className="relative"><Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" /><input value={keyword} onChange={e => setKeyword(e.target.value)} placeholder="搜索剧名或别名" className="w-64 rounded-lg border border-slate-200 bg-white py-2 pl-9 pr-3 text-sm outline-none focus:border-blue-400" /></div>
          {tab === 'masters' && canWrite && <button onClick={() => setEditing(null)} className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-3.5 py-2 text-sm text-white hover:bg-blue-700"><Plus className="h-4 w-4" />新建剧目</button>}
        </div>
      </div>
      {error && <div className="mb-4 flex items-center gap-2 rounded-lg border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-600"><AlertCircle className="h-4 w-4" />{error.message}</div>}
      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        {result.isLoading ? <div className="flex justify-center py-24 text-slate-400"><Loader2 className="mr-2 h-5 w-5 animate-spin" />加载中</div> :
          result.isError ? <div className="py-20 text-center text-sm text-slate-400">剧目数据加载失败，请稍后重试</div> :
          (result.data?.items.length || 0) === 0 ? <Empty references={tab === 'references'} /> :
          <div className="overflow-x-auto"><table className="w-full"><thead className="border-b border-slate-100 bg-slate-50/70"><tr><th className="px-5 py-3 text-left">剧目</th><th className="px-5 py-3 text-left">语言 / 地区</th><th className="px-5 py-3 text-left">类型</th>{tab === 'references' && <th className="px-5 py-3 text-left">应用状态</th>}{canWrite && <th className="px-5 py-3 text-right">操作</th>}</tr></thead>
            <tbody className="divide-y divide-slate-100">{(result.data?.items || []).map(raw => {
              const item = raw as DramaMaster & Partial<ApplicationDrama>; const id = item.drama_id || item.id
              return <tr key={id} className="hover:bg-slate-50/60"><td className="px-5 py-4"><div className="flex items-center gap-3">{item.cover_url ? <img src={item.cover_url} alt="" className="h-12 w-9 rounded object-cover" /> : <div className="flex h-12 w-9 items-center justify-center rounded bg-slate-100"><BookOpen className="h-4 w-4 text-slate-300" /></div>}<div><p className="font-medium text-slate-800">{item.display_title || item.title}</p>{item.display_title && <p className="text-xs text-slate-400">主档：{item.title}</p>}<p className="mt-0.5 max-w-xs truncate text-xs text-slate-400">{item.aliases?.join(' / ') || '暂无别名'}</p></div></div></td><td className="px-5 py-4 text-xs text-slate-500">{[item.original_language, item.region].filter(Boolean).join(' · ') || '-'}</td><td className="px-5 py-4"><div className="flex flex-wrap gap-1">{item.genres?.length ? item.genres.map(tag => <span key={tag} className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">{tag}</span>) : <span className="text-xs text-slate-400">-</span>}</div></td>{tab === 'references' && <td className="px-5 py-4"><span className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs ${item.reference_status === 'active' ? 'bg-emerald-50 text-emerald-600' : 'bg-amber-50 text-amber-600'}`}><Check className="h-3 w-3" />{item.reference_status === 'active' ? '使用中' : '已暂停'}</span></td>}{canWrite && <td className="px-5 py-4"><div className="flex justify-end gap-1">{tab === 'masters' ? <><button title="编辑主档" onClick={() => setEditing(item)} className="rounded-lg p-2 text-slate-400 hover:bg-blue-50 hover:text-blue-600"><Pencil className="h-4 w-4" /></button><button disabled={attached.has(id) || attach.isPending} title={attached.has(id) ? '当前应用已引用' : '加入当前应用'} onClick={() => attach.mutate(id)} className="rounded-lg p-2 text-slate-400 hover:bg-emerald-50 hover:text-emerald-600 disabled:opacity-30"><Link2 className="h-4 w-4" /></button><button title="删除主档" onClick={() => confirm(`确认删除剧目主档「${item.title}」？`) && remove.mutate(id)} className="rounded-lg p-2 text-slate-400 hover:bg-rose-50 hover:text-rose-600"><Trash2 className="h-4 w-4" /></button></> : <><button title="引用设置" onClick={() => setReferenceEditing(item as ApplicationDrama)} className="rounded-lg p-2 text-slate-400 hover:bg-blue-50 hover:text-blue-600"><Pencil className="h-4 w-4" /></button><button title="从当前应用移除" onClick={() => confirm(`仅从当前应用移除「${item.title}」？租户主档会保留。`) && detach.mutate(id)} className="rounded-lg p-2 text-slate-400 hover:bg-amber-50 hover:text-amber-600"><Unlink className="h-4 w-4" /></button></>}</div></td>}</tr>
            })}</tbody></table></div>}
      </div>
      {canWrite && editing !== undefined && <Dialog item={editing} onClose={() => setEditing(undefined)} saving={create.isPending || update.isPending} onSave={input => editing ? update.mutate({ item: editing, input }) : create.mutate(input)} />}
      {canWrite && referenceEditing && <ReferenceDialog item={referenceEditing} onClose={() => setReferenceEditing(null)} saving={updateRef.isPending} onSave={value => updateRef.mutate({ id: referenceEditing.drama_id, value })} />}
    </div>
  )
}
