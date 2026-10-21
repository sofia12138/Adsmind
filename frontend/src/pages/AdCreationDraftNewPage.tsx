import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ChevronLeft, ChevronRight, Loader2, ShieldCheck } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { PageHeader } from '@/components/common/PageHeader'
import { SectionCard } from '@/components/common/SectionCard'
import { fetchAccountGroups, fetchNamingRules } from '@/services/application-settings'
import { fetchCreativeGroups } from '@/services/creative-groups'
import { createAdCreationDraft } from '@/services/ad-creation-drafts'

const inputClass = 'w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100'
const steps = ['账户组', '命名规则', '创意组', '确认保存']

export default function AdCreationDraftNewPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [step, setStep] = useState(0)
  const [title, setTitle] = useState('')
  const [accountGroupId, setAccountGroupId] = useState(0)
  const [namingRuleId, setNamingRuleId] = useState(0)
  const [creativeGroupId, setCreativeGroupId] = useState(0)
  const [values, setValues] = useState<Record<string, string>>({})
  const accounts = useQuery({ queryKey: ['account-groups'], queryFn: fetchAccountGroups })
  const rules = useQuery({ queryKey: ['naming-rules'], queryFn: fetchNamingRules })
  const creatives = useQuery({ queryKey: ['creative-groups'], queryFn: fetchCreativeGroups })
  const selectedRule = rules.data?.find(item => item.id === namingRuleId)
  const fields = useMemo(() => (selectedRule?.rule.fields ?? []).filter(field => !['platform', 'account', 'date'].includes(field)), [selectedRule])
  const save = useMutation({
    mutationFn: () => createAdCreationDraft({
      request_key: crypto.randomUUID(), title: title.trim(), account_group_id: accountGroupId,
      naming_rule_id: namingRuleId, creative_group_id: creativeGroupId, naming_values: values,
    }),
    onSuccess: draft => { queryClient.invalidateQueries({ queryKey: ['ad-creation-drafts'] }); navigate(`/ads/app-drafts/${draft.id}`) },
  })
  const canNext = [accountGroupId > 0, namingRuleId > 0 && fields.every(field => ['campaign', 'adgroup', 'creative'].includes(field) || Boolean(values[field]?.trim())), creativeGroupId > 0, Boolean(title.trim())][step]
  return <div className="mx-auto max-w-4xl">
    <PageHeader title="新建应用广告草稿" description="四步组合应用资源。保存仅写入 AdsMind 内部数据库，不会向 Meta、TikTok、YouTube 或其他平台发送请求。" />
    <div className="mb-5 grid grid-cols-4 gap-2">{steps.map((label, index) => <div key={label} className={`rounded-lg px-3 py-2 text-center text-xs ${index === step ? 'bg-blue-600 text-white' : index < step ? 'bg-blue-50 text-blue-700' : 'bg-gray-100 text-gray-400'}`}>{index < step && <Check className="mr-1 inline h-3 w-3" />}{index + 1}. {label}</div>)}</div>
    <SectionCard title={steps[step]}>
      {step === 0 && <div className="space-y-3">{accounts.data?.map(group => <button key={group.id} onClick={() => setAccountGroupId(group.id)} className={`w-full rounded-xl border p-4 text-left ${accountGroupId === group.id ? 'border-blue-500 bg-blue-50' : 'border-gray-200'}`}><span className="font-medium text-gray-900">{group.name}</span><span className="ml-2 text-xs text-gray-400">{group.account_refs.length} 个账户</span><p className="mt-1 text-xs text-gray-500">{group.account_refs.map(ref => `${ref.platform}:${ref.account_id}`).join(' · ')}</p></button>)}</div>}
      {step === 1 && <div className="space-y-4"><select value={namingRuleId || ''} onChange={event => { setNamingRuleId(Number(event.target.value)); setValues({}) }} className={inputClass}><option value="">选择命名规则</option>{rules.data?.map(rule => <option key={rule.id} value={rule.id}>{rule.name} · {rule.rule.pattern}</option>)}</select>{fields.map(field => <label key={field} className="block text-sm text-gray-600">{field}<input value={values[field] ?? ''} onChange={event => setValues(current => ({ ...current, [field]: event.target.value }))} placeholder={['campaign', 'adgroup', 'creative'].includes(field) ? `可选，默认 ${field}` : `填写 ${field}`} className={`mt-1 ${inputClass}`} /></label>)}</div>}
      {step === 2 && <div className="space-y-3">{creatives.data?.map(group => <button key={group.id} onClick={() => setCreativeGroupId(group.id)} className={`w-full rounded-xl border p-4 text-left ${creativeGroupId === group.id ? 'border-blue-500 bg-blue-50' : 'border-gray-200'}`}><div className="flex items-center justify-between"><span className="font-medium text-gray-900">{group.name}</span><span className={`text-xs ${group.can_deliver ? 'text-emerald-600' : 'text-amber-600'}`}>{group.can_deliver ? '当前可投放' : '当前有阻断'}</span></div><p className="mt-1 text-xs text-gray-500">{group.materials.length} 条素材{group.blocking_reasons.length ? ` · ${group.blocking_reasons.join('；')}` : ''}</p></button>)}</div>}
      {step === 3 && <div className="space-y-5"><label className="block text-sm text-gray-600">草稿名称<input autoFocus value={title} onChange={event => setTitle(event.target.value)} maxLength={160} className={`mt-1 ${inputClass}`} /></label><div className="rounded-xl border border-blue-100 bg-blue-50 p-4 text-sm text-blue-800"><ShieldCheck className="mr-2 inline h-4 w-4" />保存后系统会记录账户解析、名称预览、创意组和 effective_version_id；准备就绪时会再次验证并冻结执行快照。</div>{save.isError && <p className="text-sm text-red-600">{save.error instanceof Error ? save.error.message : '保存失败'}</p>}</div>}
      {(accounts.isLoading || rules.isLoading || creatives.isLoading) && <Loader2 className="mx-auto h-5 w-5 animate-spin text-gray-400" />}
      <div className="mt-6 flex justify-between"><button type="button" onClick={() => step === 0 ? navigate('/ads/app-drafts') : setStep(step - 1)} className="flex items-center gap-1 rounded-lg border px-4 py-2 text-sm text-gray-600"><ChevronLeft className="h-4 w-4" />{step === 0 ? '取消' : '上一步'}</button>{step < 3 ? <button disabled={!canNext} onClick={() => setStep(step + 1)} className="flex items-center gap-1 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white disabled:opacity-40">下一步<ChevronRight className="h-4 w-4" /></button> : <button disabled={!canNext || save.isPending} onClick={() => save.mutate()} className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white disabled:opacity-40">{save.isPending ? '保存中…' : '保存内部草稿'}</button>}</div>
    </SectionCard>
  </div>
}
