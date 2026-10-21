import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, Archive, Check, FileBox, FilePlus2, Link2, Loader2, Pencil, Plus, Search, Unlink, X } from 'lucide-react'
import { PageHeader } from '@/components/common/PageHeader'
import {
  attachMaterial, createMaterial, detachMaterial, getMaterial, listMaterialReferences,
  listMaterials, registerVersion, updateMaterial, type MasterInput, type MaterialMaster,
  type VersionInput,
} from './api'

const blank: MasterInput = { name: '', material_type: 'video', drama_id: null, description: '', tags: [], status: 'active' }
const classes = 'mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100'
const splitTags = (value: string) => value.split(/[,，\n]/).map(v => v.trim()).filter(Boolean)
const bytes = (value: number) => value >= 1024 * 1024 ? `${(value / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(value / 1024))} KB`

function MasterDialog({ item, saving, onClose, onSave }: { item?: MaterialMaster | null; saving: boolean; onClose: () => void; onSave: (input: MasterInput) => void }) {
  const [form, setForm] = useState<MasterInput>(item ? { name: item.name, material_type: item.material_type, drama_id: item.drama_id, description: item.description || '', tags: item.tags, status: item.status } : blank)
  const [tags, setTags] = useState(form.tags.join('，'))
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 p-4" onClick={onClose}>
    <form className="w-full max-w-xl space-y-4 rounded-2xl bg-white p-6 shadow-2xl" onClick={e => e.stopPropagation()} onSubmit={e => { e.preventDefault(); onSave({ ...form, tags: splitTags(tags) }) }}>
      <div className="flex justify-between"><div><h2 className="font-semibold text-slate-900">{item ? '编辑素材主档' : '新建素材主档'}</h2><p className="mt-1 text-xs text-slate-400">主档与内部版本属于当前租户</p></div><button type="button" onClick={onClose}><X className="h-4 w-4" /></button></div>
      <label className="block text-sm text-slate-600">素材名称<input required value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} className={classes} /></label>
      <div className="grid gap-4 sm:grid-cols-2"><label className="block text-sm text-slate-600">素材类型<select value={form.material_type} onChange={e => setForm({ ...form, material_type: e.target.value as MasterInput['material_type'] })} className={classes}><option value="video">视频</option><option value="image">图片</option><option value="audio">音频</option><option value="other">其他</option></select></label><label className="block text-sm text-slate-600">关联剧目 ID（可选）<input type="number" min="1" value={form.drama_id ?? ''} onChange={e => setForm({ ...form, drama_id: e.target.value ? Number(e.target.value) : null })} className={classes} /></label></div>
      <label className="block text-sm text-slate-600">标签<input value={tags} onChange={e => setTags(e.target.value)} placeholder="竖版，开场，英文" className={classes} /></label>
      <label className="block text-sm text-slate-600">说明<textarea rows={3} value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} className={classes} /></label>
      <div className="flex justify-end gap-2"><button type="button" onClick={onClose} className="rounded-lg border px-4 py-2">取消</button><button disabled={saving} className="rounded-lg bg-blue-600 px-4 py-2 text-white disabled:opacity-50">保存</button></div>
    </form></div>
}

function VersionDialog({ material, saving, onClose, onSave }: { material: MaterialMaster; saving: boolean; onClose: () => void; onSave: (input: VersionInput) => void }) {
  const [form, setForm] = useState({ source_filename: '', mime_type: 'video/mp4', size_bytes: '', checksum_sha256: '', width: '', height: '', duration_ms: '', notes: '' })
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 p-4" onClick={onClose}><form className="w-full max-w-xl space-y-4 rounded-2xl bg-white p-6" onClick={e => e.stopPropagation()} onSubmit={e => { e.preventDefault(); onSave({ source_filename: form.source_filename, mime_type: form.mime_type, size_bytes: Number(form.size_bytes), checksum_sha256: form.checksum_sha256 || null, width: form.width ? Number(form.width) : null, height: form.height ? Number(form.height) : null, duration_ms: form.duration_ms ? Number(form.duration_ms) : null, notes: form.notes }) }}>
    <div><h2 className="font-semibold">登记新版本 · {material.name}</h2><p className="mt-1 text-xs text-amber-600">当前未连接文件存储。保存后状态会明确保持“待上传”，不会显示为上传成功。</p></div>
    <label className="block text-sm">原始文件名<input required value={form.source_filename} onChange={e => setForm({ ...form, source_filename: e.target.value })} className={classes} /></label>
    <div className="grid gap-4 sm:grid-cols-2"><label className="block text-sm">MIME 类型<input required value={form.mime_type} onChange={e => setForm({ ...form, mime_type: e.target.value })} className={classes} /></label><label className="block text-sm">文件大小（字节）<input required type="number" min="1" value={form.size_bytes} onChange={e => setForm({ ...form, size_bytes: e.target.value })} className={classes} /></label></div>
    <div className="grid gap-4 sm:grid-cols-3">{(['width', 'height', 'duration_ms'] as const).map((key, i) => <label key={key} className="block text-sm">{['宽度', '高度', '时长 ms'][i]}<input type="number" min="1" value={form[key]} onChange={e => setForm({ ...form, [key]: e.target.value })} className={classes} /></label>)}</div>
    <label className="block text-sm">SHA-256（可选）<input value={form.checksum_sha256} onChange={e => setForm({ ...form, checksum_sha256: e.target.value })} className={classes} /></label>
    <div className="flex justify-end gap-2"><button type="button" onClick={onClose} className="rounded-lg border px-4 py-2">取消</button><button disabled={saving} className="rounded-lg bg-blue-600 px-4 py-2 text-white">登记为待上传</button></div>
  </form></div>
}

export default function MaterialCatalogPage({ openUpload = false }: { openUpload?: boolean }) {
  const [keyword, setKeyword] = useState('')
  const [editing, setEditing] = useState<MaterialMaster | null | undefined>(undefined)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [uploading, setUploading] = useState<MaterialMaster | null>(null)
  const qc = useQueryClient()
  const materials = useQuery({ queryKey: ['materials', keyword], queryFn: () => listMaterials(keyword) })
  const refs = useQuery({ queryKey: ['material-references'], queryFn: listMaterialReferences })
  const detail = useQuery({ queryKey: ['material', selectedId], queryFn: () => getMaterial(selectedId!), enabled: selectedId != null })
  const selected = useMemo(() => new Set((refs.data?.items || []).map(row => row.material_id)), [refs.data])
  const refresh = () => { qc.invalidateQueries({ queryKey: ['materials'] }); qc.invalidateQueries({ queryKey: ['material'] }); qc.invalidateQueries({ queryKey: ['material-references'] }) }
  const create = useMutation({ mutationFn: createMaterial, onSuccess: row => { refresh(); setEditing(undefined); setSelectedId(row.id) } })
  const update = useMutation({ mutationFn: ({ item, input }: { item: MaterialMaster; input: MasterInput }) => updateMaterial(item, input), onSuccess: () => { refresh(); setEditing(undefined) } })
  const register = useMutation({ mutationFn: ({ id, input }: { id: number; input: VersionInput }) => registerVersion(id, input), onSuccess: () => { refresh(); setUploading(null) } })
  const attach = useMutation({ mutationFn: attachMaterial, onSuccess: refresh })
  const detach = useMutation({ mutationFn: detachMaterial, onSuccess: refresh })
  const error = [materials.error, refs.error, detail.error, create.error, update.error, register.error, attach.error, detach.error].find(Boolean) as Error | undefined
  return <div className="mx-auto max-w-7xl"><PageHeader title={openUpload ? '素材上传登记' : '素材库'} description="租户级素材主档与内部版本；应用仅保存选择引用，不包含平台推送或预审核" />
    <div className="mb-5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"><b>存储边界：</b>当前阶段仅登记可信文件元数据。未配置安全本地存储时，版本始终标记为“待上传”，不会写入云存储。</div>
    {error && <div className="mb-4 flex gap-2 rounded-lg bg-rose-50 p-3 text-sm text-rose-600"><AlertCircle className="h-4 w-4" />{error.message}</div>}
    <div className="mb-4 flex justify-between gap-3"><div className="relative"><Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" /><input value={keyword} onChange={e => setKeyword(e.target.value)} className="w-72 rounded-lg border py-2 pl-9 pr-3 text-sm" placeholder="搜索名称或标签" /></div><button onClick={() => setEditing(null)} className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white"><Plus className="h-4 w-4" />新建素材</button></div>
    <div className="grid gap-4 lg:grid-cols-[1fr_380px]"><div className="overflow-hidden rounded-xl border bg-white"><table className="w-full"><thead className="bg-slate-50 text-left text-xs text-slate-500"><tr><th className="px-4 py-3">素材</th><th>剧目</th><th>版本</th><th>状态</th><th className="pr-4 text-right">操作</th></tr></thead><tbody className="divide-y">{materials.isLoading ? <tr><td colSpan={5} className="py-20 text-center"><Loader2 className="mx-auto animate-spin" /></td></tr> : (materials.data?.items || []).map(item => <tr key={item.id} onClick={() => setSelectedId(item.id)} className={`cursor-pointer hover:bg-slate-50 ${selectedId === item.id ? 'bg-blue-50/50' : ''}`}><td className="px-4 py-4"><p className="font-medium text-slate-800">{item.name}</p><p className="text-xs text-slate-400">{item.material_type} · {item.tags.join(' / ') || '无标签'}</p></td><td className="text-sm text-slate-500">{item.drama_title || '未关联'}</td><td className="text-sm">v{item.latest_version_number || 0}</td><td><span className="rounded-full bg-emerald-50 px-2 py-1 text-xs text-emerald-700">{item.status === 'active' ? '有效' : '已归档'}</span></td><td className="pr-4"><div className="flex justify-end gap-1"><button title="编辑" onClick={e => { e.stopPropagation(); setEditing(item) }} className="p-2"><Pencil className="h-4 w-4" /></button><button title="登记版本" onClick={e => { e.stopPropagation(); setUploading(item) }} className="p-2 text-blue-600"><FilePlus2 className="h-4 w-4" /></button>{selected.has(item.id) ? <button title="从当前应用移除" onClick={e => { e.stopPropagation(); detach.mutate(item.id) }} className="p-2 text-amber-600"><Unlink className="h-4 w-4" /></button> : <button title="加入当前应用" onClick={e => { e.stopPropagation(); attach.mutate(item.id) }} className="p-2 text-emerald-600"><Link2 className="h-4 w-4" /></button>}</div></td></tr>)}</tbody></table></div>
      <aside className="rounded-xl border bg-white p-5">{!selectedId ? <div className="py-20 text-center text-sm text-slate-400"><FileBox className="mx-auto mb-3 h-8 w-8" />选择素材查看详情和版本</div> : detail.isLoading ? <Loader2 className="mx-auto mt-20 animate-spin" /> : detail.data && <><div className="flex items-start justify-between"><div><h2 className="font-semibold text-slate-900">{detail.data.name}</h2><p className="mt-1 text-xs text-slate-400">主档 #{detail.data.id} · 修订 {detail.data.revision}</p></div>{detail.data.status === 'archived' && <Archive className="h-4 w-4" />}</div><p className="mt-4 text-sm text-slate-600">{detail.data.description || '暂无说明'}</p><h3 className="mt-6 text-xs font-semibold uppercase tracking-wide text-slate-400">内部版本</h3><div className="mt-2 space-y-2">{(detail.data.versions || []).length === 0 ? <p className="rounded-lg bg-slate-50 p-3 text-xs text-slate-400">尚未登记版本</p> : detail.data.versions?.map(v => <div key={v.id} className="rounded-lg border p-3"><div className="flex justify-between"><span className="text-sm font-medium">v{v.version_number} · {v.source_filename}</span><span className="rounded bg-amber-50 px-2 py-0.5 text-xs text-amber-700">{v.upload_status === 'pending_upload' ? '待上传' : v.upload_status}</span></div><p className="mt-1 text-xs text-slate-400">{v.mime_type} · {bytes(v.size_bytes)} · {v.storage_backend}</p></div>)}</div><div className="mt-6 rounded-lg bg-blue-50 p-3 text-xs text-blue-700"><Check className="mr-1 inline h-3 w-3" />应用引用只记录选择关系；不会触发平台映射、推送或预审核。</div></>}</aside></div>
    {editing !== undefined && <MasterDialog item={editing} saving={create.isPending || update.isPending} onClose={() => setEditing(undefined)} onSave={input => editing ? update.mutate({ item: editing, input }) : create.mutate(input)} />}
    {uploading && <VersionDialog material={uploading} saving={register.isPending} onClose={() => setUploading(null)} onSave={input => register.mutate({ id: uploading.id, input })} />}
  </div>
}
