import {
  fetchBenchmarkRunDetail,
  type BenchmarkRunRecord,
  type BenchmarkMetricSummaryRecord,
} from '../api/chatbiApi'

const escapeCsvCell = (value: string | number | null | undefined): string => {
  if (value == null) return ''
  const text = String(value)
  if (/[",\n\r]/.test(text)) return `"${text.replace(/"/g, '""')}"`
  return text
}

const readSnapField = (snap: Record<string, unknown>, camel: string, snake: string) =>
  (camel in snap ? snap[camel] : snap[snake])

const readSnapStr = (snap: Record<string, unknown>, camel: string, snake: string) => {
  const v = readSnapField(snap, camel, snake)
  return typeof v === 'string' ? v : undefined
}

const readSnapBool = (snap: Record<string, unknown>, camel: string, snake: string) => {
  const v = readSnapField(snap, camel, snake)
  return typeof v === 'boolean' ? (v ? '是' : '否') : undefined
}

const readSnapNum = (snap: Record<string, unknown>, camel: string, snake: string) => {
  const v = readSnapField(snap, camel, snake)
  return typeof v === 'number' ? String(v) : undefined
}

const CONFIG_FIELDS: { key: string; label: string; read: (snap: Record<string, unknown>) => string | undefined }[] = [
  { key: 'model', label: 'Model', read: (s) => readSnapStr(s, 'model', 'model') },
  { key: 'promptVersion', label: 'Prompt Version', read: (s) => readSnapStr(s, 'promptVersion', 'prompt_version') },
  { key: 'schemaSelectionEnabled', label: 'Schema Linking', read: (s) => readSnapBool(s, 'schemaSelectionEnabled', 'schema_selection_enabled') },
  { key: 'qsqlRecallEnabled', label: 'QSQL Recall', read: (s) => readSnapBool(s, 'qsqlRecallEnabled', 'qsql_recall_enabled') },
  { key: 'businessKnowledgeRecallEnabled', label: 'Biz Knowledge Recall', read: (s) => readSnapBool(s, 'businessKnowledgeRecallEnabled', 'business_knowledge_recall_enabled') },
  { key: 'sqlFixEnabled', label: 'SQL Fix', read: (s) => readSnapBool(s, 'sqlFixEnabled', 'sql_fix_enabled') },
  { key: 'evidenceEnabled', label: 'Evidence', read: (s) => readSnapBool(s, 'evidenceEnabled', 'evidence_enabled') },
  { key: 'rewriteEnabled', label: 'Rewrite', read: (s) => readSnapBool(s, 'rewriteEnabled', 'rewrite_enabled') },
  { key: 'summaryEnabled', label: 'Summary', read: (s) => readSnapBool(s, 'summaryEnabled', 'summary_enabled') },
  { key: 'sqlSelectionEnabled', label: 'SQL Selection', read: (s) => readSnapBool(s, 'sqlSelectionEnabled', 'sql_selection_enabled') },
  { key: 'sqlValidateEnabled', label: 'SQL Validate', read: (s) => readSnapBool(s, 'sqlValidateEnabled', 'sql_validate_enabled') },
  { key: 'schemaTopK', label: 'Schema Hint TopK', read: (s) => readSnapNum(s, 'schemaTopK', 'schema_top_k') },
  { key: 'schemaFullIfSmall', label: 'Small Schema Guard', read: (s) => readSnapBool(s, 'schemaFullIfSmall', 'schema_full_if_small') },
  { key: 'schemaSmallTableThreshold', label: 'Small Schema Threshold', read: (s) => readSnapNum(s, 'schemaSmallTableThreshold', 'schema_small_table_threshold') },
  { key: 'sqlFixMaxAttempts', label: 'SQL Fix Max Attempts', read: (s) => readSnapNum(s, 'sqlFixMaxAttempts', 'sql_fix_max_attempts') },
  { key: 'valueFoundingEnabled', label: 'Value Finding', read: (s) => readSnapBool(s, 'valueFoundingEnabled', 'value_founding_enabled') },
  { key: 'valueSearchEnabled', label: 'Value Search', read: (s) => readSnapBool(s, 'valueSearchEnabled', 'value_search_enabled') },
  { key: 'groupByAuditEnabled', label: 'GROUP BY Audit', read: (s) => readSnapBool(s, 'groupByAuditEnabled', 'group_by_audit_enabled') },
]

const buildHeader = (metricNames: string[]): string[] => [
  'id', 'dataset_code', 'dataset_version', 'method_type', 'status',
  'created_at', 'started_at', 'finished_at',
  'sample_limit', 'source_group', 'concurrency', 'timeout_seconds',
  'total_count', 'processed_count', 'success_count', 'failed_count',
  ...CONFIG_FIELDS.map(f => f.label),
  ...metricNames,
]

const buildRunRow = (
  run: BenchmarkRunRecord,
  snap: Record<string, unknown>,
  metricNames: string[],
  metricsMap: Record<string, BenchmarkMetricSummaryRecord[]>,
): string[] => [
  run.id, run.datasetCode, run.datasetVersion, run.methodType, run.status,
  run.createdAt ?? '', run.startedAt ?? '', run.finishedAt ?? '',
  String(run.sampleLimit ?? ''), run.sourceGroup ?? '', String(run.concurrency), String(run.timeoutSeconds),
  String(run.totalCount), String(run.processedCount), String(run.successCount), String(run.failedCount),
  ...CONFIG_FIELDS.map(f => f.read(snap) ?? ''),
  ...metricNames.map(name => {
    const m = metricsMap[run.id]?.find(mm => mm.metricName === name)
    return m ? String(m.metricValue) : ''
  }),
]

const buildComparisonCsv = (
  runs: BenchmarkRunRecord[],
  metricsMap: Record<string, BenchmarkMetricSummaryRecord[]>,
): string => {
  const allMetricNames = new Set<string>()
  for (const metrics of Object.values(metricsMap)) {
    for (const m of metrics) allMetricNames.add(m.metricName)
  }
  const metricNames = [...allMetricNames].sort()

  const header = buildHeader(metricNames)
  const rows = runs.map(run => {
    const snap = run.methodConfigSnapshot ?? {}
    return buildRunRow(run, snap, metricNames, metricsMap).map(v => escapeCsvCell(v)).join(',')
  })

  return '\uFEFF' + [header.join(','), ...rows].join('\n')
}

export const downloadBenchmarkComparisonReport = async (runIds: string[]) => {
  const details = await Promise.all(runIds.map(id => fetchBenchmarkRunDetail(id)))
  const runs = details.map(d => d.run)
  const metricsMap: Record<string, BenchmarkMetricSummaryRecord[]> = {}
  for (const d of details) {
    metricsMap[d.run.id] = d.metrics ?? []
  }

  const csv = buildComparisonCsv(runs, metricsMap)
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `chatbi-benchmark-comparison-${new Date().toISOString().slice(0, 10)}.csv`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
