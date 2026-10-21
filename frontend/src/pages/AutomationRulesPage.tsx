import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, FlaskConical, Plus, Save, ShieldX, Trash2 } from 'lucide-react'
import { PageHeader } from '@/components/common/PageHeader'
import { SectionCard } from '@/components/common/SectionCard'
import {
  createAutomationRule, listAutomationRules, listRuleEvaluations, runRuleEvaluation,
  updateAutomationRule, type RuleCondition, type RuleSource,
} from '@/services/automation-rules'

const SOURCE_FIELDS: Record<RuleSource, string[]> = {
  material: ['material_id', 'name', 'material_type', 'material_status', 'reference_status', 'selection_mode', 'selected_version_id', 'selected_version_number', 'selected_version_upload_status'],
  creative_group: ['id', 'name', 'can_deliver', 'blocking_reason_count', 'material_count'],
  ad_draft: ['id', 'title', 'status', 'revision', 'blocking_reason_count', 'has_execution_snapshot'],
  platform_preflight: ['id', 'draft_id', 'status', 'blocking_reason_count', 'dry_run', 'external_write_authorized', 'preflight_passed'],
}

const emptyCondition = (): RuleCondition => ({
  source: 'ad_draft', field: 'status', operator: 'equals', value: 'READY', quantifier: 'any',
  outcome: 'review_required', code: 'ready_draft_review', message: '存在 READY 草稿，需要人工复核。',
})

const parseList = (value: string) => value.split(',').map(item => item.trim()).filter(Boolean)
const parseNumbers = (value: string) => parseList(value).map(Number).filter(Number.isInteger)

function normalizeValue(value: string): unknown {
  const text = value.trim()
  if (text === 'true') return true
  if (text === 'false') return false
  if (text === 'null') return null
  if (/^-?\d+(\.\d+)?$/.test(text)) return Number(text)
  if (text.startsWith('[')) {
    try { return JSON.parse(text) } catch { return text }
  }
  return value
}

export default function AutomationRulesPage() {
  const client = useQueryClient()
  const rules = useQuery({ queryKey: ['automation-rules'], queryFn: listAutomationRules })
  const [selectedId, setSelectedId] = useState('')
  const selected = rules.data?.find(item => item.id === selectedId)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [status, setStatus] = useState<'ACTIVE' | 'DISABLED'>('ACTIVE')
  const [conditions, setConditions] = useState<RuleCondition[]>([emptyCondition()])
  const [inputs, setInputs] = useState({ materials: '', groups: '', drafts: '', preflights: '' })

  const evaluations = useQuery({
    queryKey: ['automation-rule-evaluations', selectedId],
    queryFn: () => listRuleEvaluations(selectedId), enabled: Boolean(selectedId),
  })
  const payload = useMemo(() => ({ name: name.trim(), description: description.trim(), status, definition: { conditions } }), [name, description, status, conditions])
  const save = useMutation({
    mutationFn: () => selected
      ? updateAutomationRule(selected.id, payload, selected.current_version)
      : createAutomationRule(payload),
    onSuccess: async row => {
      await client.invalidateQueries({ queryKey: ['automation-rules'] })
      setSelectedId(row.id)
    },
  })
  const run = useMutation({
    mutationFn: () => runRuleEvaluation(selectedId, {
      material_ids: parseNumbers(inputs.materials), creative_group_ids: parseNumbers(inputs.groups),
      ad_draft_ids: parseList(inputs.drafts), platform_preflight_run_ids: parseList(inputs.preflights),
    }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['automation-rule-evaluations', selectedId] }),
  })

  const setCondition = (index: number, patch: Partial<RuleCondition>) => setConditions(current => current.map((item, i) => {
    if (i !== index) return item
    const next = { ...item, ...patch }
    if (patch.source) next.field = SOURCE_FIELDS[patch.source][0]
    return next
  }))
  const newRule = () => { setSelectedId(''); setName(''); setDescription(''); setStatus('ACTIVE'); setConditions([emptyCondition()]) }
  const selectRule = (rule: NonNullable<typeof rules.data>[number]) => {
    setSelectedId(rule.id); setName(rule.name); setDescription(rule.description); setStatus(rule.status)
    setConditions(rule.definition.conditions)
  }

  return <div className="mx-auto max-w-7xl">
    <PageHeader title="自动化规则" description="基于当前应用的内部状态生成 review_required 建议或阻断原因。所有试跑固定为 dry-run，不调度任务，也不修改草稿或调用广告平台。" action={<button onClick={newRule} className="flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm"><Plus className="h-4 w-4" />新建规则</button>} />
    <div className="mb-5 flex gap-2 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700"><ShieldX className="h-5 w-5 shrink-0" /><div><div className="font-medium">评估结果只能进入人工复核</div><div className="mt-1 text-xs text-slate-500">dry_run=true · external_write_authorized=false · 不自动标记 READY · 不上传素材、不创建广告、不改预算、不发送通知。</div></div></div>
    <div className="grid gap-5 lg:grid-cols-[280px_1fr]">
      <SectionCard title="规则列表" extra={`${rules.data?.length ?? 0} 条`}>
        <div className="space-y-2"><button onClick={newRule} className={`w-full rounded-lg border p-3 text-left text-sm ${!selectedId ? 'border-blue-500 bg-blue-50' : ''}`}>＋ 新规则草稿</button>{rules.data?.map(rule => <button key={rule.id} onClick={() => selectRule(rule)} className={`w-full rounded-lg border p-3 text-left ${selectedId === rule.id ? 'border-blue-500 bg-blue-50' : ''}`}><div className="flex justify-between gap-2 text-sm font-medium"><span>{rule.name}</span><span className="text-xs text-gray-500">v{rule.current_version}</span></div><div className="mt-1 text-xs text-gray-500">{rule.status === 'ACTIVE' ? '启用' : '停用'} · {rule.definition.conditions.length} 个条件</div></button>)}</div>
      </SectionCard>
      <div className="space-y-5">
        <SectionCard title={selected ? `编辑规则 · v${selected.current_version}` : '新建规则'}>
          <div className="grid gap-3 md:grid-cols-2"><label className="text-sm">名称<input value={name} onChange={e => setName(e.target.value)} className="mt-1 w-full rounded-lg border px-3 py-2" /></label><label className="text-sm">状态<select value={status} onChange={e => setStatus(e.target.value as typeof status)} className="mt-1 w-full rounded-lg border px-3 py-2"><option value="ACTIVE">启用</option><option value="DISABLED">停用</option></select></label></div>
          <label className="mt-3 block text-sm">说明<textarea value={description} onChange={e => setDescription(e.target.value)} className="mt-1 w-full rounded-lg border px-3 py-2" rows={2} /></label>
          <div className="mt-5 flex items-center justify-between"><h3 className="text-sm font-medium">明确条件</h3><button onClick={() => setConditions(items => [...items, emptyCondition()])} className="text-sm text-blue-600">＋ 添加条件</button></div>
          <div className="mt-2 space-y-3">{conditions.map((condition, index) => <div key={index} className="rounded-xl border bg-gray-50 p-3">
            <div className="grid gap-2 md:grid-cols-3"><select value={condition.source} onChange={e => setCondition(index, { source: e.target.value as RuleSource })} className="rounded-lg border px-2 py-2 text-sm"><option value="material">素材</option><option value="creative_group">创意组</option><option value="ad_draft">广告草稿</option><option value="platform_preflight">平台预检</option></select><select value={condition.field} onChange={e => setCondition(index, { field: e.target.value })} className="rounded-lg border px-2 py-2 text-sm">{SOURCE_FIELDS[condition.source].map(field => <option key={field}>{field}</option>)}</select><select value={condition.operator} onChange={e => setCondition(index, { operator: e.target.value as RuleCondition['operator'] })} className="rounded-lg border px-2 py-2 text-sm"><option value="equals">等于</option><option value="not_equals">不等于</option><option value="in">属于列表</option><option value="not_in">不属于列表</option><option value="contains">包含</option><option value="exists">存在状态</option></select></div>
            <div className="mt-2 grid gap-2 md:grid-cols-3"><input value={typeof condition.value === 'string' ? condition.value : JSON.stringify(condition.value)} onChange={e => setCondition(index, { value: normalizeValue(e.target.value) })} placeholder='值；列表如 ["A","B"]' className="rounded-lg border px-2 py-2 text-sm" /><select value={condition.quantifier} onChange={e => setCondition(index, { quantifier: e.target.value as RuleCondition['quantifier'] })} className="rounded-lg border px-2 py-2 text-sm"><option value="any">任一输入匹配</option><option value="all">全部输入匹配</option></select><select value={condition.outcome} onChange={e => setCondition(index, { outcome: e.target.value as RuleCondition['outcome'] })} className="rounded-lg border px-2 py-2 text-sm"><option value="review_required">建议人工复核</option><option value="blocking_reason">产生阻断原因</option></select></div>
            <div className="mt-2 grid gap-2 md:grid-cols-[1fr_2fr_auto]"><input value={condition.code} onChange={e => setCondition(index, { code: e.target.value })} placeholder="reason_code" className="rounded-lg border px-2 py-2 text-sm" /><input value={condition.message} onChange={e => setCondition(index, { message: e.target.value })} placeholder="给审核人的说明" className="rounded-lg border px-2 py-2 text-sm" /><button onClick={() => setConditions(items => items.filter((_, i) => i !== index))} disabled={conditions.length === 1} className="rounded-lg border p-2 text-red-600 disabled:opacity-30"><Trash2 className="h-4 w-4" /></button></div>
          </div>)}</div>
          {save.error && <p className="mt-3 text-sm text-red-600">{save.error instanceof Error ? save.error.message : '保存失败'}</p>}
          <button onClick={() => save.mutate()} disabled={save.isPending || !name.trim()} className="mt-4 flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white disabled:opacity-40"><Save className="h-4 w-4" />{selected ? '保存为新版本' : '创建规则'}</button>
        </SectionCard>
        {selected && <SectionCard title="试跑" extra="只读快照">
          <div className="grid gap-3 md:grid-cols-2"><label className="text-sm">素材 ID（逗号分隔）<input value={inputs.materials} onChange={e => setInputs(v => ({ ...v, materials: e.target.value }))} className="mt-1 w-full rounded-lg border px-3 py-2" /></label><label className="text-sm">创意组 ID（逗号分隔）<input value={inputs.groups} onChange={e => setInputs(v => ({ ...v, groups: e.target.value }))} className="mt-1 w-full rounded-lg border px-3 py-2" /></label><label className="text-sm">广告草稿 ID（逗号分隔）<input value={inputs.drafts} onChange={e => setInputs(v => ({ ...v, drafts: e.target.value }))} className="mt-1 w-full rounded-lg border px-3 py-2" /></label><label className="text-sm">平台预检记录 ID（逗号分隔）<input value={inputs.preflights} onChange={e => setInputs(v => ({ ...v, preflights: e.target.value }))} className="mt-1 w-full rounded-lg border px-3 py-2" /></label></div>
          {run.error && <p className="mt-3 text-sm text-red-600">{run.error instanceof Error ? run.error.message : '试跑失败'}</p>}
          <button onClick={() => run.mutate()} disabled={run.isPending || !Object.values(inputs).some(Boolean)} className="mt-4 flex items-center gap-1.5 rounded-lg bg-slate-900 px-4 py-2 text-sm text-white disabled:opacity-40"><FlaskConical className="h-4 w-4" />运行 dry-run</button>
        </SectionCard>}
        {selected && <SectionCard title="试跑结果" extra={`${evaluations.data?.length ?? 0} 条`}><div className="space-y-3">{evaluations.data?.map(item => <details key={item.id} className="rounded-xl border p-4"><summary className="flex cursor-pointer list-none items-center justify-between gap-3"><span className="flex items-center gap-2 text-sm font-medium">{item.status === 'CLEAR' ? <CheckCircle2 className="h-5 w-5 text-emerald-600" /> : <AlertTriangle className="h-5 w-5 text-amber-600" />}{item.status === 'CLEAR' ? '无建议' : item.status === 'REVIEW_REQUIRED' ? '需要人工复核' : '存在阻断原因'}</span><span className="text-xs text-gray-500">{item.created_at}</span></summary><div className="mt-3 space-y-2 text-sm">{item.recommendations.map(r => <div key={r.id} className="rounded-lg bg-blue-50 p-3 text-blue-800"><code>{r.reason_code}</code> · {r.reason_message}</div>)}{item.blocking_reasons.map((r, i) => <div key={`${r.code}-${i}`} className="rounded-lg bg-amber-50 p-3 text-amber-800"><code>{r.code}</code> · {r.message}</div>)}<div className="break-all text-xs text-gray-500">snapshot {item.input_snapshot_hash}</div><pre className="max-h-72 overflow-auto rounded-lg bg-gray-950 p-3 text-xs text-gray-100">{JSON.stringify(item.input_snapshot, null, 2)}</pre></div></details>)}{!evaluations.data?.length && <p className="py-8 text-center text-sm text-gray-500">暂无试跑结果。</p>}</div></SectionCard>}
      </div>
    </div>
  </div>
}
