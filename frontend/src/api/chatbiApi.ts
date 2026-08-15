import { apiRequest, apiRequestStream } from './client'
import { readSseStream } from './sse'

const REST_ENDPOINTS = {
  datasource: '/chatbi/datasource',
  qsql: '/chatbi/qsql',
  businessKnowledge: '/chatbi/business-knowledge',
  queryStream: '/chatbi/query/stream',
  queryMessage: (messageId: string) => `/chatbi/messages/${messageId}`,
  benchmarkDatasets: '/chatbi/benchmarks/datasets',
  benchmarkDatasetDatasources: (datasetId: string) => `/chatbi/benchmarks/datasets/${datasetId}/datasources`,
  benchmarkRuns: '/chatbi/benchmarks/runs',
  benchmarkRun: (runId: string) => `/chatbi/benchmarks/runs/${runId}`,
  benchmarkRunCases: (runId: string) => `/chatbi/benchmarks/runs/${runId}/cases`,
  benchmarkRunCase: (runId: string, resultId: string) => `/chatbi/benchmarks/runs/${runId}/cases/${resultId}`,
  benchmarkRerunCase: (runId: string, resultId: string) => `/chatbi/benchmarks/runs/${runId}/cases/${resultId}/rerun`,
  benchmarkRerunNonSuccess: (runId: string) => `/chatbi/benchmarks/runs/${runId}/cases/rerun-non-success`,
  benchmarkCancelRun: (runId: string) => `/chatbi/benchmarks/runs/${runId}/cancel`,
  benchmarkRecoverRun: (runId: string) => `/chatbi/benchmarks/runs/${runId}/recover`,
  benchmarkResumeRun: (runId: string) => `/chatbi/benchmarks/runs/${runId}/resume`,
} as const

type ListQuery = { page?: number; pageSize?: number }

const buildPageQuery = (params?: ListQuery & Record<string, string | number | undefined>) => {
  const sp = new URLSearchParams()
  if (typeof params?.page === 'number') sp.set('page', String(params.page))
  if (typeof params?.pageSize === 'number') sp.set('pageSize', String(params.pageSize))
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (key === 'page' || key === 'pageSize') return
      if (value === undefined || value === null || value === '') return
      sp.set(key, String(value))
    })
  }
  const q = sp.toString()
  return q ? `?${q}` : ''
}

// --- Datasource ---

export type ChatbiDatasourceRecord = {
  id: string
  origin: string
  name: string
  connectorType: string
  host: string
  port: number
  database: string
  schemaName?: string | null
  username: string
  importFileIds?: string[] | null
  dbSchema?: Record<string, unknown> | null
  dbSchemaUpdatedAt?: string | null
  extraParams?: Record<string, unknown> | null
  remark?: string | null
  createdAt?: string | null
  updatedAt?: string | null
}

export type ChatbiDatasourceListResponse = { total: number; current: number; pageSize: number; records: ChatbiDatasourceRecord[] }

export type ChatbiDatasourceCreatePayload = {
  name: string
  connectorType: string
  host: string
  port: number
  database: string
  schemaName?: string
  username: string
  password: string
  remark?: string
}

export type ChatbiExecuteSqlResult = { columns: string[]; rows: Record<string, unknown>[]; truncated: boolean }

export const fetchDatasources = (params?: ListQuery & { name?: string; connectorType?: string }) =>
  apiRequest<ChatbiDatasourceListResponse>(`${REST_ENDPOINTS.datasource}${buildPageQuery({ page: params?.page ?? 1, pageSize: params?.pageSize ?? 50, name: params?.name, connectorType: params?.connectorType })}`, { method: 'GET' })

export const createDatasource = (payload: ChatbiDatasourceCreatePayload) =>
  apiRequest<ChatbiDatasourceRecord>(REST_ENDPOINTS.datasource, { method: 'POST', body: payload })

export const updateDatasource = (datasourceId: string, payload: Partial<ChatbiDatasourceCreatePayload>) =>
  apiRequest<ChatbiDatasourceRecord>(`${REST_ENDPOINTS.datasource}/${datasourceId}`, { method: 'PUT', body: payload })

export const deleteDatasource = (datasourceId: string) =>
  apiRequest<void>(`${REST_ENDPOINTS.datasource}/${datasourceId}`, { method: 'DELETE' })

export const testDatasourceConnection = (datasourceId: string) =>
  apiRequest<void>(`${REST_ENDPOINTS.datasource}/${datasourceId}/test-connection`, { method: 'POST' })

export const preprocessDatasource = (datasourceId: string) =>
  apiRequest<{ taskId: string }>(`${REST_ENDPOINTS.datasource}/${datasourceId}/preprocess`, { method: 'POST' })

export const executeDatasourceSql = (datasourceId: string, sql: string) =>
  apiRequest<ChatbiExecuteSqlResult>(`${REST_ENDPOINTS.datasource}/${datasourceId}/execute-sql`, { method: 'POST', body: { sql } })

// --- QSQL ---

export type ChatbiQsqlRecord = {
  id: string
  datasourceId: string
  question: string
  sqlBody: string
  llmSimplifiedDescription?: string | null
  createdAt?: string | null
  updatedAt?: string | null
}

export type ChatbiQsqlListResponse = { total: number; current: number; pageSize: number; records: ChatbiQsqlRecord[] }

export const fetchQsqlList = (params?: ListQuery & { datasourceId?: string }) =>
  apiRequest<ChatbiQsqlListResponse>(`${REST_ENDPOINTS.qsql}${buildPageQuery({ page: params?.page ?? 1, pageSize: params?.pageSize ?? 50, datasourceId: params?.datasourceId })}`, { method: 'GET' })

export const createQsql = (payload: { datasourceId: string; question: string; sqlBody: string }) =>
  apiRequest<ChatbiQsqlRecord>(REST_ENDPOINTS.qsql, { method: 'POST', body: payload })

export const updateQsql = (recordId: string, payload: { question?: string; sqlBody?: string }) =>
  apiRequest<ChatbiQsqlRecord>(`${REST_ENDPOINTS.qsql}/${recordId}`, { method: 'PUT', body: payload })

export const deleteQsql = (recordId: string) =>
  apiRequest<void>(`${REST_ENDPOINTS.qsql}/${recordId}`, { method: 'DELETE' })

// --- Business Knowledge ---

export type ChatbiBusinessKnowledgeScope = 'GLOBAL' | 'SYSTEM_INFERRED'
export type ChatbiBusinessKnowledgeKind = 'DIMENSION' | 'METRIC' | 'TIME' | 'TERM'

export type ChatbiBusinessKnowledgeRecord = {
  id: string
  content: string
  scope: ChatbiBusinessKnowledgeScope
  kind: ChatbiBusinessKnowledgeKind
  datasourceId: string
  createdAt?: string | null
  updatedAt?: string | null
}

export type ChatbiBusinessKnowledgeListResponse = { total: number; current: number; pageSize: number; records: ChatbiBusinessKnowledgeRecord[] }

export const fetchBusinessKnowledgeList = (params?: ListQuery & { datasourceId?: string; scope?: string; kind?: string }) =>
  apiRequest<ChatbiBusinessKnowledgeListResponse>(`${REST_ENDPOINTS.businessKnowledge}${buildPageQuery({ page: params?.page ?? 1, pageSize: params?.pageSize ?? 50, datasourceId: params?.datasourceId, scope: params?.scope, kind: params?.kind })}`, { method: 'GET' })

export const createBusinessKnowledge = (payload: { content: string; scope: ChatbiBusinessKnowledgeScope; kind: ChatbiBusinessKnowledgeKind; datasourceId: string }) =>
  apiRequest<ChatbiBusinessKnowledgeRecord>(REST_ENDPOINTS.businessKnowledge, { method: 'POST', body: payload })

export const updateBusinessKnowledge = (recordId: string, payload: Partial<{ content: string; scope: ChatbiBusinessKnowledgeScope; kind: ChatbiBusinessKnowledgeKind; datasourceId: string }>) =>
  apiRequest<ChatbiBusinessKnowledgeRecord>(`${REST_ENDPOINTS.businessKnowledge}/${recordId}`, { method: 'PUT', body: payload })

export const deleteBusinessKnowledge = (recordId: string) =>
  apiRequest<void>(`${REST_ENDPOINTS.businessKnowledge}/${recordId}`, { method: 'DELETE' })

// --- Benchmark ---

export type BenchmarkDatasetRecord = {
  id: string
  datasetCode: string
  displayName: string
  description?: string | null
  currentVersion: string
  sampleCount: number
  datasourceCount: number
  status: string
  isEnabled: boolean
  createdAt?: string | null
  updatedAt?: string | null
}

export type BenchmarkDatasetDatasourceRecord = {
  id: string
  datasetId: string
  datasourceId: string
  dbId: string
  displayName: string
  status: string
  sampleCount: number
  sortOrder: number
  createdAt?: string | null
  updatedAt?: string | null
}


export const SCHEMA_FORMATS = ['ddl', 'summary', 'light', 'single'] as const
export type SchemaFormat = (typeof SCHEMA_FORMATS)[number]

export const PROMPT_FORMATS = ['direct', 'chain_of_thought', 'problem_decomposition'] as const
export type PromptFormat = (typeof PROMPT_FORMATS)[number]

export type SqlCandidatePath = `${SchemaFormat}:${PromptFormat}`

export const ALL_CANDIDATE_PATHS: SqlCandidatePath[] = SCHEMA_FORMATS.flatMap(s =>
  PROMPT_FORMATS.map(p => `${s}:${p}` as SqlCandidatePath),
)

export const SCHEMA_FORMAT_LABELS: Record<SchemaFormat, string> = {
  ddl: 'DDL',
  summary: 'Summary',
  light: 'Light',
  single: 'Plain (default schema text)',
}

export const PROMPT_FORMAT_LABELS: Record<PromptFormat, string> = {
  direct: 'Direct',
  chain_of_thought: 'Chain of Thought',
  problem_decomposition: 'Problem Decomposition',
}

export type BenchmarkMethodConfigPayload = {
  model?: string
  promptVersion?: string
  schemaSelectionEnabled?: boolean
  qsqlRecallEnabled?: boolean
  businessKnowledgeRecallEnabled?: boolean
  sqlFixEnabled?: boolean
  evidenceEnabled?: boolean
  rewriteEnabled?: boolean
  summaryEnabled?: boolean
  sqlCandidatePaths: SqlCandidatePath[]
  sqlSelectionEnabled?: boolean
  sqlValidateEnabled?: boolean
  schemaTopK?: number
  schemaFullIfSmall?: boolean
  schemaSmallTableThreshold?: number
  sqlFixMaxAttempts?: number
  valueFoundingEnabled?: boolean
  valueSearchEnabled?: boolean
  ragEnabled?: boolean
  groupByAuditEnabled?: boolean
}

export type BenchmarkRunCreatePayload = {
  datasetId: string
  methodType?: string
  methodConfig?: BenchmarkMethodConfigPayload
  sampleLimit?: number
  concurrency?: number
  timeoutSeconds?: number
  selectedDatasourceIds?: string[]
  sourceGroup?: string
}

export type BenchmarkRunRecord = {
  id: string
  datasetId: string
  datasetCode: string
  datasetVersion: string
  methodType: string
  methodConfigSnapshot: Record<string, unknown>
  selectedDatasourceIds?: string[] | null
  sourceGroup?: string | null
  sampleLimit?: number | null
  concurrency: number
  timeoutSeconds: number
  status: string
  totalCount: number
  processedCount: number
  successCount: number
  failedCount: number
  lastError?: string | null
  startedAt?: string | null
  finishedAt?: string | null
  createdAt?: string | null
  updatedAt?: string | null
}

export type BenchmarkMetricSummaryRecord = {
  id: string
  runId: string
  metricName: string
  metricValue: number
  sampleCount: number
  extraJson: Record<string, unknown>
  createdAt?: string | null
  updatedAt?: string | null
}

export type BenchmarkRunDetail = { run: BenchmarkRunRecord; metrics: BenchmarkMetricSummaryRecord[] }

export type BenchmarkCaseResultRecord = {
  id: string
  runId: string
  sampleId: string
  datasetId: string
  datasourceId: string
  sampleCode: string
  questionSnapshot: string
  goldSqlSnapshot: string
  generatedSql?: string | null
  executionAccuracy?: number | null
  tableF1?: number | null
  columnF1?: number | null
  joinF1?: number | null
  domainKnowledgeF1?: number | null
  status: string
  errorMessage?: string | null
  traceId?: string | null
  detailJson: Record<string, unknown>
  promptTokens?: number | null
  completionTokens?: number | null
  totalTokens?: number | null
  generatedSqlExecuteMs?: number | null
  goldSqlExecuteMs?: number | null
  startedAt?: string | null
  finishedAt?: string | null
  elapsedMs?: number | null
  createdAt?: string | null
  updatedAt?: string | null
}

export type BenchmarkDatasetListResponse = { records: BenchmarkDatasetRecord[] }
export type BenchmarkDatasetDatasourceListResponse = { records: BenchmarkDatasetDatasourceRecord[] }
export type BenchmarkRunListResponse = { total: number; current: number; pageSize: number; records: BenchmarkRunRecord[] }
export type BenchmarkCaseListResponse = { total: number; current: number; pageSize: number; records: BenchmarkCaseResultRecord[] }
export type BenchmarkRerunNonSuccessResult = { submittedCount: number; skippedCount: number }

export const fetchBenchmarkDatasets = () =>
  apiRequest<BenchmarkDatasetListResponse>(REST_ENDPOINTS.benchmarkDatasets, { method: 'GET' })

export const fetchBenchmarkDatasetDatasources = (datasetId: string) =>
  apiRequest<BenchmarkDatasetDatasourceListResponse>(REST_ENDPOINTS.benchmarkDatasetDatasources(datasetId), { method: 'GET' })

export const createBenchmarkRun = (payload: BenchmarkRunCreatePayload) =>
  apiRequest<BenchmarkRunRecord>(REST_ENDPOINTS.benchmarkRuns, { method: 'POST', body: payload })

export const fetchBenchmarkRuns = (params?: ListQuery & { datasetId?: string; status?: string }) =>
  apiRequest<BenchmarkRunListResponse>(`${REST_ENDPOINTS.benchmarkRuns}${buildPageQuery({ page: params?.page ?? 1, pageSize: params?.pageSize ?? 20, datasetId: params?.datasetId, status: params?.status })}`, { method: 'GET' })

export const fetchBenchmarkRunDetail = (runId: string) =>
  apiRequest<BenchmarkRunDetail>(REST_ENDPOINTS.benchmarkRun(runId), { method: 'GET' })

export const fetchBenchmarkCases = (runId: string, params?: ListQuery & { status?: string }) =>
  apiRequest<BenchmarkCaseListResponse>(`${REST_ENDPOINTS.benchmarkRunCases(runId)}${buildPageQuery({ page: params?.page ?? 1, pageSize: params?.pageSize ?? 20, status: params?.status })}`, { method: 'GET' })

export const fetchBenchmarkCaseDetail = (runId: string, resultId: string) =>
  apiRequest<BenchmarkCaseResultRecord>(REST_ENDPOINTS.benchmarkRunCase(runId, resultId), { method: 'GET' })

export const rerunBenchmarkCase = (runId: string, resultId: string) =>
  apiRequest<BenchmarkCaseResultRecord>(REST_ENDPOINTS.benchmarkRerunCase(runId, resultId), { method: 'POST' })

export const rerunBenchmarkNonSuccessCases = (runId: string) =>
  apiRequest<BenchmarkRerunNonSuccessResult>(REST_ENDPOINTS.benchmarkRerunNonSuccess(runId), { method: 'POST' })

export const cancelBenchmarkRun = (runId: string) =>
  apiRequest<void>(REST_ENDPOINTS.benchmarkCancelRun(runId), { method: 'POST' })

export const recoverBenchmarkRun = (runId: string) =>
  apiRequest<void>(REST_ENDPOINTS.benchmarkRecoverRun(runId), { method: 'POST' })

export const resumeBenchmarkRun = (runId: string) =>
  apiRequest<BenchmarkRunRecord>(REST_ENDPOINTS.benchmarkResumeRun(runId), { method: 'POST' })

export const deleteBenchmarkRun = (runId: string) =>
  apiRequest<void>(REST_ENDPOINTS.benchmarkRun(runId), { method: 'DELETE' })

// --- Query (SSE) ---

export type ChatbiQueryStreamEventName =
  | 'started' | 'rewritten_question' | 'business_knowledge_recall'
  | 'intent' | 'schema_linking' | 'schema_selected' | 'qsql_recall'
  | 'sql_candidates' | 'clarification_required' | 'sql'
  | 'sql_validate' | 'sql_group_audit' | 'data' | 'summary' | 'completed' | 'failed'
  | 'value_founding' | 'rag_knowledge_recall'
  | 'value_search'
  | 'round_start' | 'round_end' | 'thinking' | 'sql_update'
  | 'tool_call' | 'tool_result' | 'final'

export type ChatbiSqlCandidateItem = {
  pathName: string
  schemaFormat?: string
  promptStyle?: string
  sql?: string
  originalSql?: string
  fixed?: boolean
  generationError?: string
  executeError?: string
  fixError?: string
  columns?: string[]
  rows?: Record<string, unknown>[]
  rowCount?: number
  truncated?: boolean
  resultSignature?: string
  groupId?: string
  groupSize?: number
  score?: number
  wins?: number
  comparisons?: number
  selected?: boolean
  selectionReason?: string
}

export type ChatbiStreamEvent = {
  event: ChatbiQueryStreamEventName
  requestId?: string
  sessionId?: string
  messageId?: string
  question?: string
  isDegraded?: boolean
  intent?: string
  missingDatasource?: boolean
  datasourceId?: string
  datasourceName?: string
  fields?: string[]
  schemaLinking?: Record<string, unknown>
  items?: unknown[]
  sql?: string
  fixed?: boolean
  columns?: string[]
  rows?: Record<string, unknown>[]
  truncated?: boolean
  text?: string
  content?: string
  round?: number
  confidence?: number
  tool?: string
  params?: Record<string, unknown>
  result?: unknown
  raw?: Record<string, unknown>
  token?: string
  options?: string[]
  error?: Record<string, unknown>
  selection?: Record<string, unknown>
  valueFoundingLiterals?: { value: string; columns: string[] }[]
  valueFoundingMatches?: { literal: string; columnRef: string; value: string; score: number }[]
  valueSearchMatches?: { literal: string; columnRef: string; value: string; score: number; matchType?: string; frequency?: number }[]
  ragKnowledgeHits?: { chunkId: string; dbName: string; tableName: string; sourcePath: string; content: string; score: number }[]
  validation?: {
    originalSql?: string
    validatedSql?: string
    changed?: boolean
    latencyMs?: number
    context?: Record<string, unknown>
  }
  groupAudit?: {
    phase?: string
    round?: number
    thought?: string
    finalSql?: string
    tool?: string
    params?: Record<string, unknown>
    result?: unknown
    sql?: string
  }
}

export type ChatbiQueryStreamRequest = {
  question: string
  datasourceId?: string
  sessionId?: string
  clarificationToken?: string
  clarificationSkip?: boolean
  sqlCandidatePaths: SqlCandidatePath[]
  sqlSelectionEnabled?: boolean
  sqlValidateEnabled?: boolean
  valueFoundingEnabled?: boolean
  groupByAuditEnabled?: boolean
  rewriteEnabled?: boolean
  summaryEnabled?: boolean
  businessKnowledgeRecallEnabled?: boolean
  schemaSelectionEnabled?: boolean
  qsqlRecallEnabled?: boolean
  sqlFixEnabled?: boolean
  valueSearchEnabled?: boolean
  ragEnabled?: boolean
}

const normalizeStreamEvent = (frame: { eventName?: string; data: Record<string, unknown> }): ChatbiStreamEvent => {
  const d = frame.data
  const event = String(d.event ?? d.type ?? frame.eventName ?? 'started') as ChatbiQueryStreamEventName
  return {
    event,
    raw: d,
    requestId: d.requestId == null ? undefined : String(d.requestId),
    sessionId: d.sessionId == null ? undefined : String(d.sessionId),
    messageId: d.messageId == null ? undefined : String(d.messageId),
    question: d.question == null ? undefined : String(d.question),
    isDegraded: d.isDegraded == null ? undefined : Boolean(d.isDegraded),
    intent: d.intent == null ? undefined : String(d.intent),
    missingDatasource: d.missingDatasource == null ? undefined : Boolean(d.missingDatasource),
    datasourceId: d.datasourceId == null ? undefined : String(d.datasourceId),
    datasourceName: d.datasourceName == null ? undefined : String(d.datasourceName),
    fields: Array.isArray(d.fields) ? d.fields.map(String) : undefined,
    schemaLinking: event === 'schema_linking' ? d : undefined,
    items: Array.isArray(d.items) ? d.items : undefined,
    sql: d.sql == null ? undefined : String(d.sql),
    fixed: d.fixed == null ? undefined : Boolean(d.fixed),
    columns: Array.isArray(d.columns) ? d.columns.map(String) : undefined,
    rows: Array.isArray(d.rows) ? (d.rows as Record<string, unknown>[]) : undefined,
    truncated: d.truncated == null ? undefined : Boolean(d.truncated),
    text: d.text == null ? undefined : String(d.text),
    content: d.content == null ? undefined : String(d.content),
    round: typeof d.round === 'number' ? d.round : undefined,
    confidence: typeof d.confidence === 'number' ? d.confidence : undefined,
    tool: d.tool == null ? undefined : String(d.tool),
    params: d.params && typeof d.params === 'object' ? d.params as Record<string, unknown> : undefined,
    result: d.result,
    token: d.token == null ? undefined : String(d.token),
    options: Array.isArray(d.options) ? d.options.map(String) : undefined,
    error: d.error && typeof d.error === 'object' ? (d.error as Record<string, unknown>) : undefined,
    selection: d.selection && typeof d.selection === 'object' ? (d.selection as Record<string, unknown>) : undefined,
    valueFoundingLiterals: Array.isArray(d.literals) ? (d.literals as { value: string; columns: string[] }[]) : undefined,
    valueFoundingMatches: Array.isArray(d.matches) && event === 'value_founding'
      ? (d.matches as Record<string, unknown>[]).map((item) => ({
          literal: String(item.literal ?? ''),
          columnRef: String(item.columnRef ?? item.column_ref ?? ''),
          value: String(item.value ?? ''),
          score: typeof item.score === 'number' ? item.score : Number(item.score ?? 0),
        }))
      : undefined,
    valueSearchMatches: Array.isArray(d.matches) && event === 'value_search'
      ? (d.matches as Record<string, unknown>[]).map((item) => ({
          literal: String(item.literal ?? ''),
          columnRef: String(item.columnRef ?? item.column_ref ?? ''),
          value: String(item.value ?? ''),
          score: typeof item.score === 'number' ? item.score : Number(item.score ?? 0),
          matchType: item.matchType == null && item.match_type == null ? undefined : String(item.matchType ?? item.match_type),
          frequency: item.frequency == null ? undefined : Number(item.frequency),
        }))
      : undefined,
    ragKnowledgeHits: Array.isArray(d.items) && (d.event === 'rag_knowledge_recall' || d.type === 'rag_knowledge_recall')
      ? (d.items as { chunk_id?: string; chunkId?: string; db_name?: string; dbName?: string; table_name?: string; tableName?: string; source_path?: string; sourcePath?: string; content?: string; score?: number }[]).map((item) => ({
          chunkId: String(item.chunk_id ?? item.chunkId ?? ''),
          dbName: String(item.db_name ?? item.dbName ?? ''),
          tableName: String(item.table_name ?? item.tableName ?? ''),
          sourcePath: String(item.source_path ?? item.sourcePath ?? ''),
          content: String(item.content ?? ''),
          score: typeof item.score === 'number' ? item.score : 0,
        }))
      : undefined,
    validation: d.validation && typeof d.validation === 'object' ? {
      originalSql: (d.validation as Record<string, unknown>).originalSql == null ? undefined : String((d.validation as Record<string, unknown>).originalSql),
      validatedSql: (d.validation as Record<string, unknown>).validatedSql == null ? undefined : String((d.validation as Record<string, unknown>).validatedSql),
      changed: (d.validation as Record<string, unknown>).changed == null ? undefined : Boolean((d.validation as Record<string, unknown>).changed),
      latencyMs: typeof (d.validation as Record<string, unknown>).latencyMs === 'number' ? (d.validation as Record<string, unknown>).latencyMs as number : undefined,
      context: (d.validation as Record<string, unknown>).context && typeof (d.validation as Record<string, unknown>).context === 'object' ? (d.validation as Record<string, unknown>).context as Record<string, unknown> : undefined,
    } : undefined,
    groupAudit: d.groupAudit && typeof d.groupAudit === 'object' ? {
      phase: (d.groupAudit as Record<string, unknown>).phase == null ? undefined : String((d.groupAudit as Record<string, unknown>).phase),
      round: typeof (d.groupAudit as Record<string, unknown>).round === 'number' ? (d.groupAudit as Record<string, unknown>).round as number : undefined,
      thought: (d.groupAudit as Record<string, unknown>).thought == null ? undefined : String((d.groupAudit as Record<string, unknown>).thought),
      finalSql: (d.groupAudit as Record<string, unknown>).final_sql == null ? undefined : String((d.groupAudit as Record<string, unknown>).final_sql),
      tool: (d.groupAudit as Record<string, unknown>).tool == null ? undefined : String((d.groupAudit as Record<string, unknown>).tool),
      params: (d.groupAudit as Record<string, unknown>).params && typeof (d.groupAudit as Record<string, unknown>).params === 'object' ? (d.groupAudit as Record<string, unknown>).params as Record<string, unknown> : undefined,
      result: (d.groupAudit as Record<string, unknown>).result,
      sql: (d.groupAudit as Record<string, unknown>).sql == null ? undefined : String((d.groupAudit as Record<string, unknown>).sql),
    } : undefined,
  }
}

export async function* runQueryStream(payload: ChatbiQueryStreamRequest, options: { signal?: AbortSignal } = {}): AsyncGenerator<ChatbiStreamEvent> {
  const response = await apiRequestStream(REST_ENDPOINTS.queryStream, {
    method: 'POST',
    body: payload,
    headers: { Accept: 'text/event-stream' },
    signal: options.signal,
    timeoutMs: 0,
  })
  yield* readSseStream(response, (frame) => normalizeStreamEvent(frame), { parseErrorMessage: 'ChatBI SSE 解析失败' })
}

// --- Parsing helpers for benchmark case details ---

export const readDetailJsonValue = (detailJson: Record<string, unknown> | undefined | null, camelKey: string, snakeKey: string): unknown => {
  if (!detailJson) return undefined
  if (camelKey in detailJson) return detailJson[camelKey]
  return detailJson[snakeKey]
}

export const parseBenchmarkStreamEvents = (detailJson: Record<string, unknown> | undefined | null): ChatbiStreamEvent[] => {
  const raw = readDetailJsonValue(detailJson, 'queryStreamEvents', 'query_stream_events')
  if (!Array.isArray(raw)) return []
  return raw.map((item) => normalizeStreamEvent({ data: item && typeof item === 'object' ? (item as Record<string, unknown>) : {} }))
}

export type BenchmarkSqlResultPreview = {
  columns: string[]
  rows: Record<string, unknown>[]
  rowCount: number
  previewRowCount: number
  truncated: boolean
  elapsedMs?: number | null
}

export type BenchmarkSqlExecutionDetail = {
  generatedSqlExecuteMs?: number | null
  goldSqlExecuteMs?: number | null
  generated?: BenchmarkSqlResultPreview | null
  gold?: BenchmarkSqlResultPreview | null
  generatedError?: string | null
  goldError?: string | null
}

const parseSqlResultPreview = (value: unknown): BenchmarkSqlResultPreview | null => {
  if (!value || typeof value !== 'object') return null
  const raw = value as Record<string, unknown>
  const columns = Array.isArray(raw.columns) ? raw.columns.map(String) : []
  const rows = Array.isArray(raw.rows) ? raw.rows.filter((row): row is Record<string, unknown> => !!row && typeof row === 'object') : []
  const rowCount = typeof raw.rowCount === 'number' ? raw.rowCount : rows.length
  const previewRowCount = typeof raw.previewRowCount === 'number' ? raw.previewRowCount : rows.length
  return { columns, rows, rowCount, previewRowCount, truncated: Boolean(raw.truncated), elapsedMs: typeof raw.elapsedMs === 'number' ? raw.elapsedMs : null }
}

export const parseBenchmarkSqlExecution = (detailJson: Record<string, unknown> | undefined | null): BenchmarkSqlExecutionDetail | null => {
  const raw = readDetailJsonValue(detailJson, 'sqlExecution', 'sql_execution')
  if (!raw || typeof raw !== 'object') return null
  const record = raw as Record<string, unknown>
  return {
    generatedSqlExecuteMs: typeof record.generatedSqlExecuteMs === 'number' ? record.generatedSqlExecuteMs : null,
    goldSqlExecuteMs: typeof record.goldSqlExecuteMs === 'number' ? record.goldSqlExecuteMs : null,
    generated: parseSqlResultPreview(record.generated),
    gold: parseSqlResultPreview(record.gold),
    generatedError: typeof record.generatedError === 'string' ? record.generatedError : typeof record.generated_error === 'string' ? record.generated_error : null,
    goldError: typeof record.goldError === 'string' ? record.goldError : typeof record.gold_error === 'string' ? record.gold_error : null,
  }
}
