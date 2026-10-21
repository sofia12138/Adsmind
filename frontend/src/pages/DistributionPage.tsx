import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Video, Plus, Film, ClipboardCheck, ExternalLink, X } from 'lucide-react'
import { PageHeader } from '@/components/common/PageHeader'
import { useAuth } from '@/contexts/AuthContext'
import { addDistributionChannel, checkDistributionDraft, emptyDistribution, listDistributionChannels, listDistributionDrafts, saveDistributionDraft } from '@/services/distribution'
import type { DistributionDraft, DistributionPayload, DistributionCheck } from '@/services/distribution'

const input = 'w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-200'
const button = 'inline-flex items-center justify-center gap-2 rounded-lg border px-4 py-2 text-sm disabled:opacity-40'
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block space-y-1.5"><span className="text-sm text-gray-600">{label}</span>{children}</label>
}

type Section = 'tasks' | 'records' | 'channels'
export default function DistributionPage({ section }: { section: Section }) {
  const { currentApplication, username } = useAuth()
  return <DistributionWorkspace key={`${currentApplication?.id}:${username}:${section}`} section={section} />
}
function DistributionWorkspace({ section }: { section: Section }) {
  const { currentApplication, username, role } = useAuth()
  const canEdit = ['admin', 'super_admin', 'optimizer', 'designer'].includes(role)
  const [params, setParams] = useSearchParams()
  const client = useQueryClient()
  const scope = [username, currentApplication?.id]
  const [page, setPage] = useState(1)
  const [editing, setEditing] = useState<DistributionDraft>()
  const [form, setForm] = useState<DistributionPayload>(() => ({ ...emptyDistribution, material_id: params.get('material_id') || '', file_name: params.get('file_name') || '' }))
  const [showForm, setShowForm] = useState(section === 'tasks' && canEdit && params.has('material_id'))
  const [channelForm, setChannelForm] = useState({ name: '', channel_id: '', language: '', timezone: 'Asia/Shanghai' })
  const [showChannelForm, setShowChannelForm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [report, setReport] = useState<DistributionCheck>()
  const channels = useQuery({ queryKey: ['distribution-channels', ...scope], queryFn: listDistributionChannels })
  const drafts = useQuery({ queryKey: ['distribution-drafts', ...scope, page], queryFn: () => listDistributionDrafts(page), enabled: section === 'tasks' })
  const set = <K extends keyof DistributionPayload>(key: K, value: DistributionPayload[K]) => { setForm(f => ({ ...f, [key]: value })); setReport(undefined) }
  async function save(check = false) {
    setBusy(true); setError(''); setMessage(''); setReport(undefined)
    try {
      const saved = await saveDistributionDraft(form, editing)
      setEditing(saved)
      await client.invalidateQueries({ queryKey: ['distribution-drafts', ...scope] })
      setMessage('发行草稿已保存。尚未上传或安排自动发布。')
      if (check) setReport(await checkDistributionDraft(saved.id))
      else { setShowForm(false); if (params.has('material_id')) setParams({}, { replace: true }) }
    } catch (e) { setError(e instanceof Error ? e.message : '保存失败，请重试') }
    finally { setBusy(false) }
  }
  const fields: { key: 'drama_name' | 'version' | 'language' | 'material_id' | 'file_name' | 'title' | 'thumbnail_url' | 'subtitle_note'; label: string; max: number }[] = [
    { key: 'drama_name', label: '剧名 *', max: 200 }, { key: 'version', label: '成片版本', max: 100 },
    { key: 'language', label: '成片语言', max: 40 }, { key: 'material_id', label: '成片素材 ID', max: 200 },
    { key: 'file_name', label: '成片文件名', max: 255 }, { key: 'title', label: '发布标题', max: 100 },
    { key: 'thumbnail_url', label: '封面图片地址', max: 2000 }, { key: 'subtitle_note', label: '字幕版本备注', max: 500 },
  ]
  return <div className="max-w-6xl mx-auto space-y-5">
    <PageHeader title={section === 'channels' ? '频道管理' : section === 'records' ? '发行记录' : 'YouTube 发行'} description="完整短剧成片的发行准备与管理" action={canEdit && section !== 'records' && <button disabled={busy} className={`${button} bg-blue-600 text-white border-blue-600`} onClick={() => {
      setError(''); setMessage(''); setReport(undefined)
      if (section === 'channels') setShowChannelForm(true)
      else { setEditing(undefined); setForm({ ...emptyDistribution }); setShowForm(true) }
    }}><Plus size={16} />{section === 'channels' ? '登记频道' : '新建发行'}</button>} />
    <div className="rounded-xl border border-blue-100 bg-blue-50 px-5 py-4 text-sm text-blue-800 flex items-start gap-3"><Video className="shrink-0 mt-0.5" size={20} /><div><p className="font-medium">先准备成片，再安排发行</p><p className="mt-1 text-blue-700">当前支持保存发行草稿和登记目标频道。YouTube 授权与上传尚未接入，填写计划时间不会自动发布。</p></div></div>
    <nav className="flex gap-5 border-b text-sm" aria-label="发行中心导航">{[['tasks', '/distribution/youtube', '发行任务'], ['records', '/distribution/records', '发行记录'], ['channels', '/distribution/channels', '频道管理']].map(([id, url, label]) => <Link key={id} to={url} className={`pb-3 border-b-2 ${section === id ? 'border-blue-600 text-blue-600 font-medium' : 'border-transparent text-gray-500'}`}>{label}</Link>)}</nav>
    {message && <p role="status" className="rounded-lg bg-green-50 p-3 text-sm text-green-800">{message}</p>}
    {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    {channels.error && <p role="alert" className="text-red-600 text-sm">频道加载失败：{channels.error.message}<button className="ml-2 underline" onClick={() => void channels.refetch()}>重试</button></p>}
    {section === 'tasks' && !showForm && <>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">{[
        { label: '发行草稿', value: drafts.data?.total ?? '—' }, { label: '已登记频道', value: channels.data?.length ?? '—' }, { label: '发行方式', value: '整剧成片' },
      ].map(c => <div key={c.label} className="bg-white rounded-xl border border-gray-100 p-5"><p className="text-xs text-gray-500">{c.label}</p><p className="text-xl font-semibold mt-2">{c.value}</p></div>)}</div>
      {drafts.isLoading && <p className="text-sm text-gray-500">正在加载发行任务…</p>}
      {drafts.error && <p role="alert" className="text-red-600 text-sm">{drafts.error.message}<button className="ml-2 underline" onClick={() => void drafts.refetch()}>重试</button></p>}
      {drafts.data?.total === 0 && <div className="bg-white rounded-xl border p-12 text-center"><Film className="mx-auto text-gray-300 mb-3" size={36} /><p className="font-medium">还没有发行任务</p><p className="text-sm text-gray-500 mt-2">创建一部完整短剧的发行草稿，准备成片版本、频道和发布资料。</p></div>}
      {drafts.data?.list.map(draft => <article className="bg-white border rounded-xl p-5" key={draft.id}><div className="flex justify-between gap-4"><div><h2 className="font-semibold">{draft.payload.drama_name}</h2><p className="mt-2 text-sm text-gray-500">{draft.payload.language || '语言待填写'} · {draft.payload.version || '版本待填写'} · {channels.data?.find(c => c.id === draft.payload.channel_id)?.name || '频道待选择'}</p></div><span className="text-xs bg-gray-100 text-gray-600 h-fit rounded-full px-3 py-1">草稿</span></div><div className="flex justify-between items-center mt-4 gap-4"><p className="text-xs text-gray-400">{draft.payload.publish_mode === 'scheduled' && draft.payload.scheduled_at ? `计划时间：${new Date(draft.payload.scheduled_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}（北京时间）` : '计划立即发布'} · 尚未上传</p>{canEdit && <button className={`${button} text-blue-600 shrink-0`} onClick={() => { setEditing(draft); setForm(draft.payload); setShowForm(true); setReport(undefined); setError(''); setMessage('') }}>编辑资料</button>}</div></article>)}
      {drafts.data && drafts.data.total > 20 && <div className="flex justify-end items-center gap-4 text-sm"><button disabled={page === 1} onClick={() => setPage(p => p-1)}>上一页</button><span>第 {page} 页</span><button disabled={page * 20 >= drafts.data.total} onClick={() => setPage(p => p+1)}>下一页</button></div>}
    </>}
    {section === 'records' && <div className="bg-white rounded-xl border p-14 text-center"><ClipboardCheck className="mx-auto text-gray-300 mb-3" size={36} /><p className="font-medium">尚无实际发行记录</p><p className="text-sm text-gray-500 mt-2">接入 YouTube 上传后，这里将展示视频链接、处理结果和实际公开时间。</p><Link to="/distribution/youtube" className="inline-block text-sm text-blue-600 mt-5">去准备发行资料 →</Link></div>}
    {section === 'channels' && !showChannelForm && <>
      {channels.isLoading && <p className="text-sm text-gray-500">正在加载频道…</p>}
      {channels.data?.length === 0 && <div className="bg-white rounded-xl border p-12 text-center"><Video className="mx-auto text-gray-300 mb-3" size={36} /><p className="font-medium">还没有登记频道</p><p className="text-sm text-gray-500 mt-2">登记频道名称、ID、语言和时区，作为发行准备资料；登记不代表完成授权。</p></div>}
      {channels.data?.map(channel => <article key={channel.id} className="bg-white border rounded-xl p-5 flex justify-between gap-4"><div><h2 className="font-semibold">{channel.name}</h2><p className="text-sm text-gray-500 mt-2">{channel.language} · {channel.timezone}</p><a href={`https://www.youtube.com/channel/${channel.channel_id}`} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-blue-600 text-xs mt-3">查看频道 <ExternalLink size={12} /></a></div><span className="text-xs rounded-full bg-amber-50 text-amber-700 px-3 py-1 h-fit">待授权</span></article>)}
    </>}
    {showChannelForm && <form className="bg-white border rounded-xl p-6 space-y-4" onSubmit={async e => {
      e.preventDefault(); setBusy(true); setError('')
      try { await addDistributionChannel(channelForm); await client.invalidateQueries({ queryKey: ['distribution-channels', ...scope] }); setShowChannelForm(false); setChannelForm({ name: '', channel_id: '', language: '', timezone: 'Asia/Shanghai' }); setMessage('频道已登记，仍需完成 YouTube 授权。') }
      catch (e) { setError(e instanceof Error ? e.message : '登记失败') } finally { setBusy(false) }
    }}><h2 className="font-semibold">登记目标频道</h2><div className="grid sm:grid-cols-2 gap-4">{[['name', '频道名称'], ['channel_id', '频道 ID（UC 开头的 24 位 ID）'], ['language', '频道主要语言'], ['timezone', '时区（例如 Asia/Shanghai）']].map(([key, label]) => <Field key={key} label={label}><input required maxLength={key === 'name' ? 120 : key === 'channel_id' ? 24 : key === 'language' ? 40 : 80} className={input} value={channelForm[key as keyof typeof channelForm]} onChange={e => setChannelForm({ ...channelForm, [key]: e.target.value })} /></Field>)}</div><div className="flex gap-3"><button disabled={busy} className={`${button} bg-blue-600 text-white`}>{busy ? '保存中…' : '保存频道资料'}</button><button type="button" disabled={busy} className={button} onClick={() => setShowChannelForm(false)}>取消</button></div></form>}
    {showForm && <form className="bg-white border rounded-xl p-6 space-y-5" onSubmit={e => { e.preventDefault(); void save() }}>
      <div className="flex justify-between items-center"><h2 className="font-semibold">{editing ? '编辑发行草稿' : '新建整剧发行'}</h2><button type="button" aria-label="关闭编辑" disabled={busy} onClick={() => setShowForm(false)}><X size={20} /></button></div>
      <fieldset disabled={busy} className="space-y-5"><div className="grid sm:grid-cols-2 gap-4">{fields.map(f => <Field key={f.key} label={f.label}><input required={f.key === 'drama_name'} type={f.key === 'thumbnail_url' ? 'url' : 'text'} maxLength={f.max} className={input} value={form[f.key]} onChange={e => set(f.key, e.target.value)} /></Field>)}
        <Field label="目标频道"><select className={input} value={form.channel_id} onChange={e => set('channel_id', e.target.value)}><option value="">请选择已登记频道</option>{channels.data?.map(c => <option key={c.id} value={c.id}>{c.name}（待授权）</option>)}</select></Field>
        <Field label="受众"><select className={input} value={form.audience} onChange={e => set('audience', e.target.value as DistributionPayload['audience'])}><option value="unset">待确认</option><option value="general">非儿童专属内容</option><option value="kids">儿童专属内容</option></select></Field>
      </div>
      <p className="text-xs text-gray-500">此处保存成片引用。广告素材不一定是完整剧集，请核对版本；当前不上传或保存视频文件。</p>
      <Field label="视频简介 / 章节时间点"><textarea rows={5} maxLength={5000} className={input} value={form.description} onChange={e => set('description', e.target.value)} /></Field>
      <div className="grid sm:grid-cols-2 gap-4"><Field label="发布计划"><select className={input} value={form.publish_mode} onChange={e => set('publish_mode', e.target.value as DistributionPayload['publish_mode'])}><option value="immediate">立即发布（接入后执行）</option><option value="scheduled">定时发布（仅保存计划）</option></select></Field>
        {form.publish_mode === 'scheduled' && <Field label="计划时间（北京时间 UTC+8）"><input type="datetime-local" required className={input} value={form.scheduled_at ? new Date(new Date(form.scheduled_at).getTime() + 8*3600000).toISOString().slice(0, 16) : ''} onChange={e => set('scheduled_at', e.target.value ? new Date(`${e.target.value}:00+08:00`).toISOString() : null)} /></Field>}
      </div>
      <div className="space-y-3 text-sm text-gray-600"><label className="flex gap-2"><input type="checkbox" checked={form.full_drama_confirmed} onChange={e => set('full_drama_confirmed', e.target.checked)} />我已确认所选版本是一部完整短剧成片</label><label className="flex gap-2"><input type="checkbox" checked={form.rights_confirmed} onChange={e => set('rights_confirmed', e.target.checked)} />我已确认成片及音乐等素材允许发行到 YouTube</label></div>
      {report && <div className="rounded-lg bg-gray-50 p-4 space-y-2"><h3 className="font-medium text-sm">发行准备检查</h3>{report.checks.map(c => <p key={c.label} className={`text-sm ${c.ok ? 'text-green-700' : 'text-amber-700'}`}>{c.ok ? '✓' : '○'} {c.label}</p>)}<p className="text-xs text-gray-500 pt-2">{report.notice}</p></div>}
      <div className="flex flex-wrap gap-3"><button disabled={busy} className={`${button} bg-blue-600 text-white`}>{busy ? '处理中…' : '保存草稿'}</button><button type="button" disabled={busy || !form.drama_name.trim()} className={button} onClick={e => { if (e.currentTarget.form?.reportValidity()) void save(true) }}>保存并检查</button><button type="button" disabled title="需要先接入 YouTube 授权与上传" className={button}>发布到 YouTube</button></div></fieldset>
    </form>}
  </div>
}
