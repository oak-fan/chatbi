import {
  fetchBenchmarkCases,
  fetchBenchmarkDatasetDatasources,
  fetchBenchmarkRunDetail,
  parseBenchmarkStreamEvents,
  type BenchmarkCaseResultRecord,
  type BenchmarkMetricSummaryRecord,
  type BenchmarkRunRecord,
} from '../api/chatbiApi'

const CASE_FETCH_PAGE_SIZE = 100

const escapeCsvCell = (value: string | number | null | undefined): string => {
  if (value == null) return ''
  const text = String(value)
  if (/[",\n\r]/.test(text)) return `"${text.replace(/"/g, '""')}"`
  return text
}

const formatMetricCell = (value?: number | null) => value == null ? '' : String(value)

const buildSummaryRows = (run: BenchmarkRunRecord, metrics: BenchmarkMetricSummaryRecord[]): string[] => {
  const rows: string[] = ['section,field,value,sample_count',
    `run,id,${escapeCsvCell(run.id)},`,
    `run,dataset_code,${escapeCsvCell(run.datasetCode)},`,
    `run,dataset_version,${escapeCsvCell(run.datasetVersion)},`,
    `run,method_type,${escapeCsvCell(run.methodType)},`,
    `run,status,${escapeCsvCell(run.status)},`,
    `run,total_count,${escapeCsvCell(run.totalCount)},`,
    `run,processed_count,${escapeCsvCell(run.processedCount)},`,
    `run,success_count,${escapeCsvCell(run.successCount)},`,
    `run,failed_count,${escapeCsvCell(run.failedCount)},`,
    `run,concurrency,${escapeCsvCell(run.concurrency)},`,
    `run,timeout_seconds,${escapeCsvCell(run.timeoutSeconds)},`,
    `run,sample_limit,${escapeCsvCell(run.sampleLimit ?? '')},`,
    `run,source_group,${escapeCsvCell(run.sourceGroup ?? '')},`,
    `run,created_at,${escapeCsvCell(run.createdAt ?? '')},`,
    `run,started_at,${escapeCsvCell(run.startedAt ?? '')},`,
    `run,finished_at,${escapeCsvCell(run.finishedAt ?? '')},`,
    `run,last_error,${escapeCsvCell(run.lastError ?? '')},`,
  ]
  for (const metric of metrics) {
    rows.push(['metric', escapeCsvCell(metric.metricName), escapeCsvCell(metric.metricValue), escapeCsvCell(metric.sampleCount)].join(','))
  }
  return rows
}

const buildCaseRows = (cases: BenchmarkCaseResultRecord[]): string[] => {
  const header = 'sample_code,question,status,execution_accuracy,table_f1,column_f1,join_f1,domain_knowledge_f1,generated_sql,gold_sql'
  return [header, ...cases.map((item) =>
    [escapeCsvCell(item.sampleCode), escapeCsvCell(item.questionSnapshot), escapeCsvCell(item.status),
      escapeCsvCell(formatMetricCell(item.executionAccuracy)), escapeCsvCell(formatMetricCell(item.tableF1)),
      escapeCsvCell(formatMetricCell(item.columnF1)), escapeCsvCell(formatMetricCell(item.joinF1)),
      escapeCsvCell(formatMetricCell(item.domainKnowledgeF1)), escapeCsvCell(item.generatedSql ?? ''),
      escapeCsvCell(item.goldSqlSnapshot)].join(','))]
}

const buildSseEventRows = (cases: BenchmarkCaseResultRecord[]): string[] => {
  const header = 'sample_code,case_id,event_index,event,event_detail'
  const rows: string[] = []
  for (const item of cases) {
    const events = parseBenchmarkStreamEvents(item.detailJson)
    events.forEach((event, index) => {
      rows.push([escapeCsvCell(item.sampleCode), escapeCsvCell(item.id), escapeCsvCell(index + 1), escapeCsvCell(event.event), escapeCsvCell(JSON.stringify(event))].join(','))
    })
  }
  return [header, ...rows]
}

export const buildBenchmarkReportCsv = (run: BenchmarkRunRecord, metrics: BenchmarkMetricSummaryRecord[], cases: BenchmarkCaseResultRecord[]): string => {
  return `\uFEFF${['# summary', ...buildSummaryRows(run, metrics), '', '# cases', ...buildCaseRows(cases), '', '# sse_events', ...buildSseEventRows(cases)].join('\n')}`
}

export const buildBenchmarkReportFilename = (run: BenchmarkRunRecord) => {
  const timestamp = new Date().toISOString().slice(0, 19).replaceAll(':', '-')
  return `chatbi-benchmark-${run.id}-${run.datasetCode.replace(/[^\w.-]+/g, '_')}-${timestamp}.csv`
}

export const fetchAllBenchmarkCases = async (runId: string, status?: string): Promise<BenchmarkCaseResultRecord[]> => {
  const records: BenchmarkCaseResultRecord[] = []
  let page = 1
  let total = 0
  do {
    const result = await fetchBenchmarkCases(runId, { page, pageSize: CASE_FETCH_PAGE_SIZE, status })
    total = result.total ?? 0
    records.push(...(result.records ?? []))
    if ((result.records ?? []).length === 0) break
    page += 1
  } while (records.length < total)
  return records
}

export const downloadBenchmarkReport = async (runId: string) => {
  const detail = await fetchBenchmarkRunDetail(runId)
  const cases = await fetchAllBenchmarkCases(runId)
  const csv = buildBenchmarkReportCsv(detail.run, detail.metrics ?? [], cases)
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = buildBenchmarkReportFilename(detail.run)
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export const downloadErrorSampleCodes = async (runId: string) => {
  const allCases = await fetchAllBenchmarkCases(runId)
  const failedCodes = allCases.filter(c => c.status !== 'SUCCESS').map(c => c.sampleCode)
  const successExZeroCodes = allCases.filter(c => c.status === 'SUCCESS' && c.executionAccuracy === 0).map(c => c.sampleCode)
  const lines = [failedCodes.join(','), successExZeroCodes.join(',')]
  const content = lines.join('\n')
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `chatbi-benchmark-${runId}-error-codes.txt`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

const formatF1Cell = (value?: number | null) => value == null ? '' : value.toFixed(4)

export const downloadExZeroReport = async (runId: string) => {
  const detail = await fetchBenchmarkRunDetail(runId)
  const allCases = await fetchAllBenchmarkCases(runId)
  const exZeroCases = allCases.filter(c => (c.status === 'SUCCESS' && c.executionAccuracy === 0) || c.status === 'EXEC_ERROR')
  const dsResponse = await fetchBenchmarkDatasetDatasources(detail.run.datasetId)
  const dsMap = new Map(dsResponse.records.map(d => [d.datasourceId, d.displayName]))
  const header = '数据库名称,问题,gold_sql,generate_sql,execution_accuracy,table_f1,column_f1,join_f1,domain_knowledge_f1'
  const rows = [header, ...exZeroCases.map(item =>
    [escapeCsvCell(dsMap.get(item.datasourceId) ?? item.datasourceId),
      escapeCsvCell(item.questionSnapshot),
      escapeCsvCell(item.goldSqlSnapshot),
      escapeCsvCell(item.generatedSql ?? ''),
      escapeCsvCell(formatMetricCell(item.executionAccuracy)),
      escapeCsvCell(formatF1Cell(item.tableF1)),
      escapeCsvCell(formatF1Cell(item.columnF1)),
      escapeCsvCell(formatF1Cell(item.joinF1)),
      escapeCsvCell(formatF1Cell(item.domainKnowledgeF1))].join(','))]
  const csv = `\uFEFF${rows.join('\n')}`
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `chatbi-benchmark-${runId}-ex-zero.csv`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
