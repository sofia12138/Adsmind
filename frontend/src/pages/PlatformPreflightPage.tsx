import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, FileSearch, Loader2, ShieldX } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { PageHeader } from '@/components/common/PageHeader'
import { SectionCard } from '@/components/common/SectionCard'
import { listPreflightRuns, runPlatformPreflight } from '@/services/platform-preflight'

export default function PlatformPreflightPage() {
  const [params] = useSearchParams()
  const draftId = params.get('draft_id') || ''
  const queryClient = useQueryClient()
  const runs = useQuery({
    queryKey: ['platform-preflight-runs', draftId],
    queryFn: () => listPreflightRuns(draftId || undefined),
  })
  const run = useMutation({
    mutationFn: () => runPlatformPreflight(draftId, crypto.randomUUID()),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['platform-preflight-runs', draftId] }),
  })

  return <div className="mx-auto max-w-6xl">
    <PageHeader
      title="平台执行预检"
      description="只读取 READY 草稿的冻结快照，生成不可执行的 dry-run 计划；不会调用平台、上传素材、创建广告、修改预算或提交预审核。"
      action={draftId ? <button onClick={() => run.mutate()} disabled={run.isPending} className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-2 text-sm text-white disabled:opacity-40"><FileSearch className="h-4 w-4" />{run.isPending ? '预检中…' : '运行 dry-run 预检'}</button> : undefined}
    />
    <div className="mb-5 flex items-start gap-2 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
      <ShieldX className="mt-0.5 h-5 w-5 shrink-0" />
      <div><div className="font-medium">外部写入被代码与数据约束双重关闭</div><div className="mt-1 text-xs text-slate-500">所有计划固定 dry_run=true、executable=false、external_write_authorized=false，无法从此页面转为真实执行。</div></div>
    </div>
    {!draftId && <div className="mb-5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">请从一个 READY 的<Link to="/ads/app-drafts" className="mx-1 underline">应用广告草稿</Link>进入预检。</div>}
    {run.error && <p className="mb-4 text-sm text-red-600">{run.error instanceof Error ? run.error.message : '预检失败'}</p>}
    {runs.isLoading ? <Loader2 className="mx-auto mt-20 h-6 w-6 animate-spin text-gray-400" /> : <div className="space-y-5">
      {runs.data?.map(item => <SectionCard key={item.id} title={`${item.status === 'PASSED' ? '通过' : '阻断'} · ${item.created_at}`} extra={item.plan_hash}>
        <div className={`mb-4 flex gap-2 rounded-lg p-3 text-sm ${item.status === 'PASSED' ? 'bg-emerald-50 text-emerald-800' : 'bg-amber-50 text-amber-800'}`}>
          {item.status === 'PASSED' ? <CheckCircle2 className="h-5 w-5" /> : <AlertTriangle className="h-5 w-5" />}
          {item.status === 'PASSED' ? `快照、归属、凭证、素材映射和命名约束通过；生成 ${item.dry_run_plan.operations.length} 个账户级 dry-run 操作。` : `发现 ${item.blocking_reasons.length} 个结构化阻断原因，计划不包含任何候选操作。`}
        </div>
        {item.blocking_reasons.length > 0 && <ul className="mb-4 list-disc space-y-1 pl-5 text-sm text-gray-700">{item.blocking_reasons.map((reason, index) => <li key={`${reason.code}-${index}`}><span className="font-mono text-xs text-gray-500">{reason.code}</span> · {reason.message}</li>)}</ul>}
        <dl className="grid gap-2 text-xs text-gray-500 md:grid-cols-2"><div><dt>execution_key</dt><dd className="break-all font-mono">{item.execution_key}</dd></div><div><dt>snapshot_hash</dt><dd className="break-all font-mono">{item.snapshot_hash}</dd></div></dl>
        <details className="mt-4"><summary className="cursor-pointer text-sm text-blue-600">查看 dry-run 计划</summary><pre className="mt-2 max-h-96 overflow-auto rounded-lg bg-gray-950 p-4 text-xs text-gray-100">{JSON.stringify(item.dry_run_plan, null, 2)}</pre></details>
      </SectionCard>)}
      {!runs.data?.length && <div className="rounded-xl border border-dashed p-10 text-center text-sm text-gray-500">暂无预检记录。</div>}
    </div>}
  </div>
}
