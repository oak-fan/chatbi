import { Dropdown, Button, Card, Checkbox, Col, Collapse, Descriptions, Form, Input, InputNumber, Modal, Progress, Row, Select, Space, Spin, Switch, Table, Tag, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  cancelBenchmarkRun,
  deleteBenchmarkRun,
  createBenchmarkRun,
  fetchBenchmarkCaseDetail,
  fetchBenchmarkCases,
  fetchBenchmarkDatasetDatasources,
  fetchBenchmarkDatasets,
  fetchBenchmarkRunDetail,
  fetchBenchmarkRuns,
  parseBenchmarkStreamEvents,
  parseBenchmarkSqlExecution,
  readDetailJsonValue,
  recoverBenchmarkRun,
  resumeBenchmarkRun,
  rerunBenchmarkCase,
  rerunBenchmarkNonSuccessCases,
  type BenchmarkCaseResultRecord,
  type BenchmarkDatasetDatasourceRecord,
  type BenchmarkDatasetRecord,
  type BenchmarkMetricSummaryRecord,
  type BenchmarkRunRecord,
  SCHEMA_FORMATS, SCHEMA_FORMAT_LABELS, PROMPT_FORMATS, PROMPT_FORMAT_LABELS, type SqlCandidatePath,
} from '../api/chatbiApi'
import ChatbiQuerySseEventLog from './ChatbiQuerySseEventLog'
import BenchmarkSqlResultCompare from './BenchmarkSqlResultCompare'
import { downloadBenchmarkReport , downloadErrorSampleCodes, downloadExZeroReport } from '../utils/benchmarkReportDownload'
import { DownOutlined } from '@ant-design/icons'

const { Text, Paragraph } = Typography

const formatError = (error: unknown) => (error instanceof Error ? error.message : '操作失败')

const RUN_STATUS_COLOR: Record<string, string> = {
  PENDING: 'default', RUNNING: 'processing', SUCCESS: 'success', FAILED: 'error', CANCELED: 'warning',
}

const CASE_STATUS_COLOR: Record<string, string> = {
  SUCCESS: 'success', EXEC_ERROR: 'error', PARSE_ERROR: 'error', TIMEOUT: 'warning', SKIPPED: 'default', RERUNNING: 'processing',
}

const formatMetricName = (name: string) => name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

const formatPercent = (value?: number | null) => value == null ? '-' : `${(value * 100).toFixed(2)}%`

const isPercentMetric = (name: string) => name.endsWith('_rate') || name.includes('accuracy') || name.includes('_f1')

const formatMetricValue = (name: string, value?: number | null) => {
  if (value == null) return '-'
  if (isPercentMetric(name)) return formatPercent(value)
  if (name.endsWith('_ms')) return `${Math.round(value)} ms`
  if (name.includes('tokens')) return Math.round(value).toLocaleString()
  return value.toFixed(2)
}

const isRunActive = (status: string) => status === 'PENDING' || status === 'RUNNING'

type MethodConfigSnapshot = {
  model?: string
  promptVersion?: string
  schemaSelectionEnabled?: boolean
  qsqlRecallEnabled?: boolean
  businessKnowledgeRecallEnabled?: boolean
  sqlFixEnabled?: boolean
  evidenceEnabled?: boolean
  rewriteEnabled?: boolean
  summaryEnabled?: boolean
  sqlCandidatePaths?: SqlCandidatePath[]
  sqlSelectionEnabled?: boolean
  sqlValidateEnabled?: boolean
  schemaTopK?: number
  schemaFullIfSmall?: boolean
  schemaSmallTableThreshold?: number
  sqlFixMaxAttempts?: number
  valueFoundingEnabled?: boolean
  valueSearchEnabled?: boolean
  groupByAuditEnabled?: boolean
}

const readSnapField = (snap: Record<string, unknown>, camel: string, snake: string) => (camel in snap ? snap[camel] : snap[snake])

const readSnapStr = (snap: Record<string, unknown>, camel: string, snake: string) => { const v = readSnapField(snap, camel, snake); return typeof v === 'string' ? v : undefined }

const readSnapBool = (snap: Record<string, unknown>, camel: string, snake: string) => { const v = readSnapField(snap, camel, snake); return typeof v === 'boolean' ? v : undefined }

const readSnapNum = (snap: Record<string, unknown>, camel: string, snake: string) => { const v = readSnapField(snap, camel, snake); return typeof v === 'number' ? v : undefined }

const parseMethodConfig = (snap: Record<string, unknown>): MethodConfigSnapshot => {
  return {
    model: readSnapStr(snap, 'model', 'model'),
    promptVersion: readSnapStr(snap, 'promptVersion', 'prompt_version'),
    schemaSelectionEnabled: readSnapBool(snap, 'schemaSelectionEnabled', 'schema_selection_enabled'),
    qsqlRecallEnabled: readSnapBool(snap, 'qsqlRecallEnabled', 'qsql_recall_enabled'),
    businessKnowledgeRecallEnabled: readSnapBool(snap, 'businessKnowledgeRecallEnabled', 'business_knowledge_recall_enabled'),
    sqlFixEnabled: readSnapBool(snap, 'sqlFixEnabled', 'sql_fix_enabled'),
    evidenceEnabled: readSnapBool(snap, 'evidenceEnabled', 'evidence_enabled'),
    rewriteEnabled: readSnapBool(snap, 'rewriteEnabled', 'rewrite_enabled'),
    summaryEnabled: readSnapBool(snap, 'summaryEnabled', 'summary_enabled'),
    sqlCandidatePaths: (readSnapField(snap, 'sqlCandidatePaths', 'sql_candidate_paths') as SqlCandidatePath[] | undefined) ?? undefined,
    sqlSelectionEnabled: readSnapBool(snap, 'sqlSelectionEnabled', 'sql_selection_enabled'),
    sqlValidateEnabled: readSnapBool(snap, 'sqlValidateEnabled', 'sql_validate_enabled'),
    schemaTopK: readSnapNum(snap, 'schemaTopK', 'schema_top_k'),
    schemaFullIfSmall: readSnapBool(snap, 'schemaFullIfSmall', 'schema_full_if_small'),
    schemaSmallTableThreshold: readSnapNum(snap, 'schemaSmallTableThreshold', 'schema_small_table_threshold'),
    sqlFixMaxAttempts: readSnapNum(snap, 'sqlFixMaxAttempts', 'sql_fix_max_attempts'),
    valueFoundingEnabled: readSnapBool(snap, 'valueFoundingEnabled', 'value_founding_enabled'),
    valueSearchEnabled: readSnapBool(snap, 'valueSearchEnabled', 'value_search_enabled'),
    groupByAuditEnabled: readSnapBool(snap, 'groupByAuditEnabled', 'group_by_audit_enabled'),
  }
}

const formatBool = (v?: boolean) => (v == null ? '-' : v ? '是' : '否')

const CandidatePathCheckbox = ({ value, onChange }: { value?: SqlCandidatePath[]; onChange?: (v: SqlCandidatePath[]) => void }) => {
  const selected = value ?? []
  const handleChange = (schema: string, checked: SqlCandidatePath[]) => {
    const otherPaths = selected.filter(p => !p.startsWith(schema + ':'))
    onChange?.([...otherPaths, ...checked].sort())
  }
  return (
    <div style={{ border: '1px solid #d9d9d9', borderRadius: 6, padding: '8px 12px' }}>
      <Row gutter={[8, 4]}>
        {SCHEMA_FORMATS.map(schema => (
          <Col key={schema} span={12}>
            <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 2, color: '#666' }}>{SCHEMA_FORMAT_LABELS[schema]}</div>
            <Checkbox.Group
              options={PROMPT_FORMATS.map(p => ({ label: PROMPT_FORMAT_LABELS[p], value: `${schema}:${p}` as SqlCandidatePath }))}
              value={selected.filter(p => p.startsWith(schema + ':'))}
              onChange={(checked) => handleChange(schema, checked as SqlCandidatePath[])}
            />
          </Col>
        ))}
      </Row>
    </div>
  )
}

type Props = Record<string, never>

const ChatbiBenchmarkTab = (_props: Props) => {
  const [datasets, setDatasets] = useState<BenchmarkDatasetRecord[]>([])
  const [datasetDatasources, setDatasetDatasources] = useState<BenchmarkDatasetDatasourceRecord[]>([])
  const [runs, setRuns] = useState<BenchmarkRunRecord[]>([])
  const [runsTotal, setRunsTotal] = useState(0)
  const [runsPage, setRunsPage] = useState(1)
  const [selectedRunId, setSelectedRunId] = useState<string>()
  const [runDetail, setRunDetail] = useState<BenchmarkRunRecord | null>(null)
  const [runMetrics, setRunMetrics] = useState<BenchmarkMetricSummaryRecord[]>([])
  const [cases, setCases] = useState<BenchmarkCaseResultRecord[]>([])
  const [casesTotal, setCasesTotal] = useState(0)
  const [casesPage, setCasesPage] = useState(1)
  const [casesPageSize, setCasesPageSize] = useState(20)
  const [runsPageSize, setRunsPageSize] = useState(20)
  const [caseStatusFilter, setCaseStatusFilter] = useState<string>()
  const [loadingDatasets, setLoadingDatasets] = useState(false)
  const [loadingRuns, setLoadingRuns] = useState(false)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [loadingCases, setLoadingCases] = useState(false)
  const [createModalOpen, setCreateModalOpen] = useState(false)
  const [createForm] = Form.useForm()
  const [caseDetailOpen, setCaseDetailOpen] = useState(false)
  const [caseDetailLoading, setCaseDetailLoading] = useState(false)
  const [caseDetail, setCaseDetail] = useState<BenchmarkCaseResultRecord | null>(null)
  const [runDatasetDatasources, setRunDatasetDatasources] = useState<BenchmarkDatasetDatasourceRecord[]>([])
  const [downloadingReport, setDownloadingReport] = useState(false)
  const [compareModalOpen, setCompareModalOpen] = useState(false)
  const [selectedCompareRunIds, setSelectedCompareRunIds] = useState<string[]>([])
  const [downloadingCompare, setDownloadingCompare] = useState(false)
  const [rerunningCaseId, setRerunningCaseId] = useState<string>()
  const [rerunningNonSuccess, setRerunningNonSuccess] = useState(false)

  const loadDatasets = useCallback(async (silent?: boolean) => {
    if (!silent) setLoadingDatasets(true)
    try { setDatasets((await fetchBenchmarkDatasets()).records ?? []) } catch (e) { message.error(formatError(e)) } finally { if (!silent) setLoadingDatasets(false) }
  }, [])

  const loadRuns = useCallback(async (page = 1, silent?: boolean, pageSize?: number) => {
    if (!silent) setLoadingRuns(true)
    const size = pageSize ?? runsPageSize
    try { const r = await fetchBenchmarkRuns({ page, pageSize: size }); setRuns(r.records ?? []); setRunsTotal(r.total ?? 0); setRunsPage(page) } catch (e) { message.error(formatError(e)) } finally { if (!silent) setLoadingRuns(false) }
  }, [runsPageSize])

  const loadRunDetail = useCallback(async (runId: string, silent?: boolean) => {
    if (!silent) setLoadingDetail(true)
    try { const r = await fetchBenchmarkRunDetail(runId); setRunDetail(r.run); setRunMetrics(r.metrics ?? []); return r.run } catch (e) { message.error(formatError(e)); return null } finally { if (!silent) setLoadingDetail(false) }
  }, [])

  const loadCases = useCallback(async (runId: string, page = 1, status?: string, silent?: boolean, pageSize?: number) => {
    if (!silent) setLoadingCases(true)
    const size = pageSize ?? casesPageSize
    try { const r = await fetchBenchmarkCases(runId, { page, pageSize: size, status }); setCases(r.records ?? []); setCasesTotal(r.total ?? 0); setCasesPage(page) } catch (e) { message.error(formatError(e)) } finally { if (!silent) setLoadingCases(false) }
  }, [casesPageSize])

  const loadDatasetDatasources = useCallback(async (datasetId: string) => {
    try { setDatasetDatasources((await fetchBenchmarkDatasetDatasources(datasetId)).records ?? []) } catch { setDatasetDatasources([]) }
  }, [])

  useEffect(() => { void loadDatasets(); void loadRuns(1) }, [loadDatasets, loadRuns])

  useEffect(() => {
    if (!selectedRunId) { setRunDetail(null); setRunMetrics([]); setCases([]); setCasesTotal(0); setRunDatasetDatasources([]); return }
    setRunDetail(null); setRunMetrics([]); setCases([]); setRunDatasetDatasources([])
    void loadRunDetail(selectedRunId); void loadCases(selectedRunId, 1, caseStatusFilter)
  }, [selectedRunId, caseStatusFilter, loadRunDetail, loadCases])

  useEffect(() => {
    if (!runDetail?.datasetId) { setRunDatasetDatasources([]); return }
    fetchBenchmarkDatasetDatasources(runDetail.datasetId).then(r => setRunDatasetDatasources(r.records ?? [])).catch(() => setRunDatasetDatasources([]))
  }, [runDetail?.datasetId])

  useEffect(() => {
    if (!selectedRunId || !runDetail) return
    const hasRerunning = cases.some(c => c.status === 'RERUNNING')
    if (!isRunActive(runDetail.status) && !hasRerunning) return
    const timer = setInterval(() => {
      void loadRunDetail(selectedRunId, true).then(run => { if (run && !isRunActive(run.status)) { void loadCases(selectedRunId, casesPage, caseStatusFilter, true); void loadRuns(runsPage, true) } })
      void loadCases(selectedRunId, casesPage, caseStatusFilter, true)
      if (isRunActive(runDetail.status)) void loadRuns(runsPage, true)
    }, 3000)
    return () => clearInterval(timer)
  }, [selectedRunId, runDetail?.status, cases, casesPage, caseStatusFilter, runsPage, loadRunDetail, loadCases, loadRuns])

  const datasetOptions = useMemo(() => datasets.map(d => ({ label: `${d.displayName} (${d.datasetCode}, ${d.sampleCount} 样本)`, value: d.id, disabled: !d.isEnabled || d.status === 'NOT_READY' || d.status === 'DISABLED' })), [datasets])

  const datasetDsOptions = useMemo(() => datasetDatasources.map(d => ({ label: `${d.displayName} [${d.dbId}] (${d.status}, ${d.sampleCount})`, value: d.datasourceId, disabled: d.status !== 'READY' })), [datasetDatasources])

  const openCreateModal = () => {
    createForm.resetFields()
    createForm.setFieldsValue({
      methodType: 'LUOSHU_CHATBI', concurrency: 1, timeoutSeconds: 60,
      evidenceEnabled: true,
      sqlCandidatePaths: ['ddl:chain_of_thought'], sqlSelectionStrategy: 'llm_tournament',
      schemaFullIfSmall: true,
      schemaSmallTableThreshold: 15,
    })
    setDatasetDatasources([])
    setCreateModalOpen(true)
  }

  const handleCreateRun = async (values: Record<string, unknown>) => {
    try {
      const run = await createBenchmarkRun({
        datasetId: String(values.datasetId),
        methodType: String(values.methodType ?? 'LUOSHU_CHATBI'),
        methodConfig: {
          model: values.model ? String(values.model) : undefined,
          promptVersion: values.promptVersion ? String(values.promptVersion) : undefined,
          schemaSelectionEnabled: Boolean(values.schemaSelectionEnabled),
          qsqlRecallEnabled: Boolean(values.qsqlRecallEnabled),
          businessKnowledgeRecallEnabled: Boolean(values.businessKnowledgeRecallEnabled),
          sqlFixEnabled: Boolean(values.sqlFixEnabled),
          evidenceEnabled: Boolean(values.evidenceEnabled),
          rewriteEnabled: Boolean(values.rewriteEnabled),
          summaryEnabled: Boolean(values.summaryEnabled),
          sqlCandidatePaths: values.sqlCandidatePaths as SqlCandidatePath[],
          sqlSelectionEnabled: values.sqlSelectionStrategy !== 'fallback_rank',
          sqlValidateEnabled: Boolean(values.sqlValidateEnabled),
          groupByAuditEnabled: Boolean(values.groupByAuditEnabled),
          schemaTopK: values.schemaTopK == null || values.schemaTopK === '' ? undefined : Number(values.schemaTopK),
          schemaFullIfSmall: values.schemaFullIfSmall !== false,
          schemaSmallTableThreshold: Number(values.schemaSmallTableThreshold ?? 15),
          valueFoundingEnabled: Boolean(values.valueFoundingEnabled),
          valueSearchEnabled: Boolean(values.valueSearchEnabled),
          ragEnabled: Boolean(values.ragEnabled),
          sqlFixMaxAttempts: values.sqlFixMaxAttempts == null || values.sqlFixMaxAttempts === '' ? undefined : Number(values.sqlFixMaxAttempts),
        },
        sampleLimit: values.sampleLimit == null ? undefined : Number(values.sampleLimit),
        concurrency: Number(values.concurrency ?? 1),
        timeoutSeconds: Number(values.timeoutSeconds ?? 60),
        selectedDatasourceIds: Array.isArray(values.selectedDatasourceIds) && values.selectedDatasourceIds.length > 0 ? values.selectedDatasourceIds.map(String) : undefined,
        sourceGroup: values.sourceGroup ? String(values.sourceGroup) : undefined,
      })
      message.success(`评价任务已创建：${run.id}`)
      setCreateModalOpen(false)
      setSelectedRunId(run.id)
      await loadRuns(1)
    } catch (e) { message.error(formatError(e)) }
  }

  const handleCancelRun = (runId: string) => {
    Modal.confirm({ title: '取消评价任务？', onOk: async () => { await cancelBenchmarkRun(runId); message.success('已取消'); if (selectedRunId === runId) await loadRunDetail(runId); await loadRuns(runsPage) } })
  }

  const handleRecoverRun = (runId: string) => {
    Modal.confirm({ title: '恢复中断的评价任务？', content: '将重置为待调度状态，已处理的样本结果将被清空，任务会从头重新执行。', okText: '恢复', onOk: async () => { await recoverBenchmarkRun(runId); message.success('已恢复，等待调度执行'); if (selectedRunId === runId) await loadRunDetail(runId); await loadRuns(runsPage) } })
  }

  const handleResumeRun = (runId: string) => {
    Modal.confirm({
      title: '续跑评价任务？',
      content: '保留已完成样本结果，仅调度剩余未跑样本。',
      okText: '续跑',
      onOk: async () => {
        await resumeBenchmarkRun(runId)
        message.success('已提交续跑，等待调度执行')
        if (selectedRunId === runId) await loadRunDetail(runId)
        await loadRuns(runsPage)
      },
    })
  }

  const canResumeRun = (run: BenchmarkRunRecord) => {
    if (run.status === 'SUCCESS') return run.processedCount < run.totalCount
    return ['PENDING', 'RUNNING', 'FAILED', 'CANCELED'].includes(run.status)
  }

  const handleDeleteRun = (runId: string) => {
    Modal.confirm({ title: '删除评价任务？', content: '将删除该任务及其样本结果、汇总指标，且不可恢复。', okText: '删除', okButtonProps: { danger: true }, onOk: async () => { try { await deleteBenchmarkRun(runId); message.success('已删除'); if (selectedRunId === runId) { setSelectedRunId(undefined); setRunDetail(null); setRunMetrics([]); setCases([]); setCasesTotal(0) } await loadRuns(runsPage) } catch (e) { message.error(formatError(e)); throw e } } })
  }

  const viewCaseDetail = async (runId: string, resultId: string) => {
    setCaseDetailLoading(true); setCaseDetailOpen(true)
    try { setCaseDetail(await fetchBenchmarkCaseDetail(runId, resultId)) } catch (e) { setCaseDetailOpen(false); message.error(formatError(e)) } finally { setCaseDetailLoading(false) }
  }

  const handleRerunCase = async (runId: string, resultId: string) => {
    setRerunningCaseId(resultId)
    try { await rerunBenchmarkCase(runId, resultId); message.success('样本重跑已提交'); await loadCases(runId, casesPage, caseStatusFilter, true) } catch (e) { message.error(formatError(e)) } finally { setRerunningCaseId(undefined) }
  }

  const handleRerunNonSuccess = () => {
    if (!selectedRunId || !runDetail) return
    Modal.confirm({
      title: '一键重跑非成功样本？',
      content: `将提交 ${runDetail.processedCount - runDetail.successCount} 个非 SUCCESS 样本重跑`,
      okText: '重跑',
      onOk: async () => {
        setRerunningNonSuccess(true)
        try { const r = await rerunBenchmarkNonSuccessCases(selectedRunId); message.success(`已提交 ${r.submittedCount} 个${r.skippedCount > 0 ? `，跳过 ${r.skippedCount} 个` : ''}`); await loadCases(selectedRunId, casesPage, caseStatusFilter, true) } catch (e) { message.error(formatError(e)) } finally { setRerunningNonSuccess(false) }
      },
    })
  }

  const caseDetailStreamEvents = useMemo(() => parseBenchmarkStreamEvents(caseDetail?.detailJson), [caseDetail?.detailJson])
  const caseSqlExecution = useMemo(() => parseBenchmarkSqlExecution(caseDetail?.detailJson), [caseDetail?.detailJson])
  const caseExecutionMatched = useMemo(() => {
    const compare = readDetailJsonValue(caseDetail?.detailJson, 'resultCompare', 'result_compare')
    if (compare && typeof compare === 'object') { const matched = (compare as Record<string, unknown>).matched; if (typeof matched === 'boolean') return matched }
    if (caseDetail?.executionAccuracy === 1) return true
    if (caseDetail?.executionAccuracy === 0) return false
    return null
  }, [caseDetail?.detailJson, caseDetail?.executionAccuracy])

  const datasetColumns: ColumnsType<BenchmarkDatasetRecord> = [
    { title: '编码', dataIndex: 'datasetCode', width: 100 }, { title: '名称', dataIndex: 'displayName' },
    { title: '版本', dataIndex: 'currentVersion', width: 100 }, { title: '样本数', dataIndex: 'sampleCount', width: 80 },
    { title: '数据源数', dataIndex: 'datasourceCount', width: 90 },
    { title: '状态', dataIndex: 'status', width: 120, render: (s: string) => <Tag>{s}</Tag> },
    { title: '启用', dataIndex: 'isEnabled', width: 70, render: (e: boolean) => e ? '是' : '否' },
  ]

  const runColumns: ColumnsType<BenchmarkRunRecord> = [
    { title: 'ID', dataIndex: 'id', width: 170, ellipsis: true }, { title: '数据集', dataIndex: 'datasetCode', width: 100 },
    { title: '方法', dataIndex: 'methodType', width: 130, ellipsis: true },
    { title: '状态', dataIndex: 'status', width: 100, render: (s: string) => <Tag color={RUN_STATUS_COLOR[s]}>{s}</Tag> },
    { title: '进度', width: 140, render: (_, r) => <Text>{r.processedCount}/{r.totalCount} (成功 {r.successCount})</Text> },
    { title: '创建时间', dataIndex: 'createdAt', width: 170, ellipsis: true },
    { title: '操作', width: 320, render: (_, r) => <Space size="small">
      <Button size="small" type={selectedRunId === r.id ? 'primary' : 'default'} onClick={() => setSelectedRunId(r.id)}>详情</Button>
      {canResumeRun(r) ? <Button size="small" onClick={() => handleResumeRun(r.id)}>续跑</Button> : null}
      {r.status === 'RUNNING' ? <Button size="small" onClick={() => handleRecoverRun(r.id)}>恢复</Button> : null}
      {isRunActive(r.status) ? <Button size="small" danger onClick={() => handleCancelRun(r.id)}>取消</Button> : <Button size="small" danger onClick={() => handleDeleteRun(r.id)}>删除</Button>}
    </Space> },
  ]

  const caseColumns: ColumnsType<BenchmarkCaseResultRecord> = [
    { title: '样本', dataIndex: 'sampleCode', width: 120, ellipsis: true },
    { title: '问题', dataIndex: 'questionSnapshot', ellipsis: true },
    { title: '状态', dataIndex: 'status', width: 130, render: (s: string, row) => <Space size={4}>
      <Tag color={CASE_STATUS_COLOR[s]}>{s}</Tag>
      {s === 'EXEC_ERROR' && row.errorMessage?.includes('Gold SQL') ? <Tag color="error">Gold</Tag> : null}
      {s === 'EXEC_ERROR' && row.errorMessage?.includes('Generated SQL') ? <Tag color="error">Gen</Tag> : null}
    </Space> },
    { title: 'EX', width: 70, render: (_, r) => formatPercent(r.executionAccuracy) },
    { title: 'Table', width: 70, render: (_, r) => formatPercent(r.tableF1) },
    { title: 'Column', width: 70, render: (_, r) => formatPercent(r.columnF1) },
    { title: 'Join', width: 70, render: (_, r) => formatPercent(r.joinF1) },
    { title: 'Domain', width: 70, render: (_, r) => formatPercent(r.domainKnowledgeF1) },
    { title: '耗时', dataIndex: 'elapsedMs', width: 80, render: (v?: number | null) => v == null ? '-' : `${v}ms` },
    { title: '操作', width: 130, render: (_, r) => <Space size="small">
      <Button size="small" onClick={() => void viewCaseDetail(r.runId, r.id)}>查看</Button>
      <Button size="small" loading={rerunningCaseId === r.id} disabled={rerunningCaseId != null || r.status === 'RERUNNING' || !runDetail || isRunActive(runDetail.status)} onClick={() => void handleRerunCase(r.runId, r.id)}>重跑</Button>
    </Space> },
  ]

  const progressPercent = runDetail && runDetail.totalCount > 0 ? Math.round((runDetail.processedCount / runDetail.totalCount) * 100) : 0
  const methodConfig = useMemo(() => runDetail ? parseMethodConfig(runDetail.methodConfigSnapshot ?? {}) : null, [runDetail])

  const selectedDsLabel = useMemo(() => {
    if (!runDetail?.selectedDatasourceIds?.length) return '全部'
    const idSet = new Set(runDetail.selectedDatasourceIds)
    const labels = runDatasetDatasources.filter(d => idSet.has(d.datasourceId)).map(d => `${d.displayName} [${d.dbId}]`)
    const unmatched = runDetail.selectedDatasourceIds.filter(id => !new Set(runDatasetDatasources.map(d => d.datasourceId)).has(id))
    return [...labels, ...unmatched].join('、')
  }, [runDetail, runDatasetDatasources])

  return (
    <div>
      <Space style={{ marginBottom: 12 }} wrap>
        <Button type="primary" onClick={openCreateModal}>创建评价任务</Button>
        <Button onClick={() => void loadDatasets()} loading={loadingDatasets}>刷新数据集</Button>
        <Button onClick={() => void loadRuns(runsPage)} loading={loadingRuns}>刷新任务列表</Button>
        {selectedRunId ? <Button onClick={() => { void loadRunDetail(selectedRunId); void loadCases(selectedRunId, casesPage, caseStatusFilter) }} loading={loadingDetail || loadingCases}>刷新当前任务</Button> : null}
        <Button onClick={() => setCompareModalOpen(true)}>下载对比报告</Button>
      </Space>

      <Row gutter={16}>
        <Col span={24} style={{ marginBottom: 16 }}>
          <Card title="基准数据集" size="small">
            <Table rowKey="id" size="small" loading={loadingDatasets} dataSource={datasets} columns={datasetColumns} pagination={false} />
          </Card>
        </Col>
        <Col span={24} style={{ marginBottom: 16 }}>
          <Card title="评价任务历史" size="small">
            <Table rowKey="id" size="small" loading={loadingRuns} dataSource={runs} columns={runColumns}
              pagination={{ current: runsPage, pageSize: runsPageSize, total: runsTotal, showSizeChanger: true, pageSizeOptions: [20, 50, 100], onChange: (p) => void loadRuns(p), onShowSizeChange: (_p, size) => { setRunsPageSize(size); void loadRuns(1, false, size) } }} />
          </Card>
        </Col>
        {selectedRunId ? (
          <Col span={24}>
            <Card title={`任务详情 #${selectedRunId}`} size="small" loading={loadingDetail && !runDetail}
              extra={runDetail ? <Space size="small">
                <Dropdown menu={{ items: [{ key: 'report', label: '下载报告' }, { key: 'errors', label: '下载错误条目编号' }, { key: 'ex-zero', label: '下载EX=0报告' }], onClick: async ({ key }) => { if (key === 'report') { setDownloadingReport(true); try { await downloadBenchmarkReport(selectedRunId); message.success('报告已下载') } catch (e) { message.error(formatError(e)) } finally { setDownloadingReport(false) } } else if (key === 'errors') { setDownloadingReport(true); try { await downloadErrorSampleCodes(selectedRunId); message.success('错误条目已下载') } catch (e) { message.error(formatError(e)) } finally { setDownloadingReport(false) } } else if (key === 'ex-zero') { setDownloadingReport(true); try { await downloadExZeroReport(selectedRunId); message.success('EX=0报告已下载') } catch (e) { message.error(formatError(e)) } finally { setDownloadingReport(false) } } } }}><Button size="small" loading={downloadingReport}><Space><DownOutlined />下载报告</Space></Button></Dropdown>
                {canResumeRun(runDetail) ? <Button size="small" onClick={() => handleResumeRun(selectedRunId)}>续跑</Button> : null}
                {runDetail.status === 'RUNNING' ? <Button size="small" onClick={() => handleRecoverRun(selectedRunId)}>恢复任务</Button> : null}
                {!isRunActive(runDetail.status) ? <Button size="small" loading={rerunningNonSuccess} disabled={rerunningNonSuccess || rerunningCaseId != null || runDetail.processedCount <= runDetail.successCount} onClick={() => handleRerunNonSuccess()}>一键重跑非成功样本</Button> : null}
                {isRunActive(runDetail.status) ? <Button danger size="small" onClick={() => handleCancelRun(selectedRunId)}>取消任务</Button> : null}
              </Space> : null}
            >
              {runDetail ? (
                <Space direction="vertical" style={{ width: '100%' }} size="middle">
                  <Collapse size="small" items={[
                    { key: 'info', label: '任务信息', children: <Descriptions column={4} size="small" bordered>
                      <Descriptions.Item label="数据集">{runDetail.datasetCode}</Descriptions.Item>
                      <Descriptions.Item label="版本">{runDetail.datasetVersion}</Descriptions.Item>
                      <Descriptions.Item label="方法">{runDetail.methodType}</Descriptions.Item>
                      <Descriptions.Item label="状态"><Tag color={RUN_STATUS_COLOR[runDetail.status]}>{runDetail.status}</Tag></Descriptions.Item>
                      <Descriptions.Item label="并发">{runDetail.concurrency}</Descriptions.Item>
                      <Descriptions.Item label="超时">{runDetail.timeoutSeconds}s</Descriptions.Item>
                      <Descriptions.Item label="样本上限">{runDetail.sampleLimit ?? '全部'}</Descriptions.Item>
                      <Descriptions.Item label="来源分组">{runDetail.sourceGroup ?? '全部'}</Descriptions.Item>
                      <Descriptions.Item label="指定数据源" span={4}>{selectedDsLabel}</Descriptions.Item>
                    </Descriptions> },
                    ...(methodConfig ? [{ key: 'config', label: '方法配置', children: <Descriptions column={4} size="small" bordered>
                      <Descriptions.Item label="Model">{methodConfig.model ?? 'default'}</Descriptions.Item>
                      <Descriptions.Item label="Prompt Version">{methodConfig.promptVersion ?? 'default'}</Descriptions.Item>
                      <Descriptions.Item label="SQL Generation">Agentar Scale SQL</Descriptions.Item>
                      <Descriptions.Item label="Candidates">{methodConfig.sqlCandidatePaths?.length ? methodConfig.sqlCandidatePaths.join(', ') : '-'}</Descriptions.Item>
                      <Descriptions.Item label="1. Rewrite">{formatBool(methodConfig.rewriteEnabled)}</Descriptions.Item>
                      <Descriptions.Item label="2. Evidence in Question">{formatBool(methodConfig.evidenceEnabled)}</Descriptions.Item>
                      <Descriptions.Item label="3. Business Knowledge Recall">{formatBool(methodConfig.businessKnowledgeRecallEnabled)}</Descriptions.Item>
                      <Descriptions.Item label="4. Schema Linking">{formatBool(methodConfig.schemaSelectionEnabled)}</Descriptions.Item>
                      <Descriptions.Item label="Small Schema Guard">{formatBool(methodConfig.schemaFullIfSmall)}</Descriptions.Item>
                      <Descriptions.Item label="Schema Hint Top-K">{methodConfig.schemaTopK ?? '默认'}</Descriptions.Item>
                      <Descriptions.Item label="Small Schema Threshold">{methodConfig.schemaSmallTableThreshold ?? 15}</Descriptions.Item>
                      <Descriptions.Item label="5. Q-SQL Recall">{formatBool(methodConfig.qsqlRecallEnabled)}</Descriptions.Item>
                      <Descriptions.Item label="6. Value Finding">{formatBool(methodConfig.valueFoundingEnabled)}</Descriptions.Item>
                      <Descriptions.Item label="6a. Value Search">{formatBool(methodConfig.valueSearchEnabled)}</Descriptions.Item>
                      <Descriptions.Item label="7. SQL Fix">{formatBool(methodConfig.sqlFixEnabled)}</Descriptions.Item>
                      <Descriptions.Item label="7a. SQL Fix Max Attempts">{methodConfig.sqlFixMaxAttempts ?? '默认'}</Descriptions.Item>
                      <Descriptions.Item label="8. SQL Validate">{formatBool(methodConfig.sqlValidateEnabled)}</Descriptions.Item>
                      <Descriptions.Item label="8a. GROUP BY Audit">{formatBool(methodConfig.groupByAuditEnabled)}</Descriptions.Item>
                      <Descriptions.Item label="9. Summary">{formatBool(methodConfig.summaryEnabled)}</Descriptions.Item>
                      <Descriptions.Item label="SQL Selection">{methodConfig.sqlSelectionEnabled === false ? 'Fallback rank' : 'LLM tournament'}</Descriptions.Item>
                    </Descriptions> }] : []),
                  ]} />
                  {isRunActive(runDetail.status) ? <Progress percent={progressPercent} status="active" /> : <Progress percent={progressPercent} />}
                  <Text type="secondary">已处理 {runDetail.processedCount}/{runDetail.totalCount}，成功 {runDetail.successCount}，失败 {runDetail.failedCount}</Text>
                  {runMetrics.length > 0 ? <Card size="small" title="汇总指标">
                    <Row gutter={[12, 12]}>
                      {runMetrics.map(m => <Col key={m.id} xs={12} sm={8} md={6} lg={4}>
                        <Card size="small"><Text type="secondary">{formatMetricName(m.metricName)}</Text><div style={{ fontSize: 18, fontWeight: 600 }}>{formatMetricValue(m.metricName, m.metricValue)}</div><Text type="secondary" style={{ fontSize: 12 }}>n={m.sampleCount}</Text></Card>
                      </Col>)}
                    </Row>
                  </Card> : null}
                  <Card size="small" title="样本结果" extra={<Select allowClear placeholder="按状态筛选" style={{ width: 160 }} value={caseStatusFilter} onChange={(v) => { setCaseStatusFilter(v); setCasesPage(1) }} options={['SUCCESS', 'EXEC_ERROR', 'PARSE_ERROR', 'TIMEOUT', 'SKIPPED'].map(s => ({ label: s, value: s }))} />}>
                    <Table rowKey="id" size="small" loading={loadingCases && cases.length === 0} dataSource={cases} columns={caseColumns}
                      pagination={{ current: casesPage, pageSize: casesPageSize, total: casesTotal, showSizeChanger: true, pageSizeOptions: [20, 50, 100], onChange: (p) => void loadCases(selectedRunId, p, caseStatusFilter), onShowSizeChange: (_p, size) => { setCasesPageSize(size); void loadCases(selectedRunId, 1, caseStatusFilter, false, size) } }} />
                  </Card>
                </Space>
              ) : null}
            </Card>
          </Col>
        ) : null}
      </Row>

      <Modal title="创建评价任务" open={createModalOpen} onCancel={() => setCreateModalOpen(false)} onOk={() => void createForm.submit()} width={640} destroyOnClose>
        <Form form={createForm} layout="vertical" onFinish={(v) => void handleCreateRun(v)}>
          <Form.Item name="datasetId" label="数据集" rules={[{ required: true }]}>
            <Select placeholder="选择数据集" options={datasetOptions} onChange={(v) => { if (v) void loadDatasetDatasources(String(v)); else setDatasetDatasources([]); createForm.setFieldValue('selectedDatasourceIds', undefined) }} />
          </Form.Item>
          <Form.Item name="methodType" label="被测方法"><Select options={[{ label: 'LUOSHU_CHATBI', value: 'LUOSHU_CHATBI' }, { label: 'DIN_SQL', value: 'DIN_SQL' }, { label: 'SINGLE_AGENT', value: 'SINGLE_AGENT' }]} /></Form.Item>
          <Row gutter={12}>
            <Col span={8}><Form.Item name="sampleLimit" label="样本数量上限"><InputNumber min={1} style={{ width: '100%' }} placeholder="全部" /></Form.Item></Col>
            <Col span={8}><Form.Item name="concurrency" label="并发数" rules={[{ required: true }]}><InputNumber min={1} max={20} style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={8}><Form.Item name="timeoutSeconds" label="超时 (秒)" rules={[{ required: true }]}><InputNumber min={5} max={300} style={{ width: '100%' }} /></Form.Item></Col>
          </Row>
          <Collapse size="small" style={{ marginBottom: 12 }} items={[{
            key: 'config', label: '方法配置', children: <>
              <Row gutter={12}>
                <Col span={12}><Form.Item name="model" label="Model"><Input placeholder="default" /></Form.Item></Col>
                <Col span={12}><Form.Item name="promptVersion" label="Prompt Version"><Input placeholder="default" /></Form.Item></Col>
              </Row>
              <Row gutter={12}>
                <Col span={8}><Form.Item label="SQL Generation"><Input defaultValue="Agentar Scale SQL" disabled /></Form.Item></Col>
                <Col span={8}><Form.Item name="sqlSelectionStrategy" label="SQL Selection"><Select options={[{ label: 'LLM tournament', value: 'llm_tournament' }, { label: 'Fallback rank', value: 'fallback_rank' }]} /></Form.Item></Col>
              </Row>
              <Row gutter={12}>
                <Col span={24}><Form.Item name="sqlCandidatePaths" label="Candidate Paths" rules={[{ validator: (_, value) => Array.isArray(value) && value.length > 0 ? Promise.resolve() : Promise.reject(new Error('Please select at least one candidate path')) }]}>
                  <CandidatePathCheckbox />
                </Form.Item></Col>
              </Row>
              <Row gutter={12}>
                <Col span={12}><Form.Item name="rewriteEnabled" label="1. Question Rewrite" valuePropName="checked" tooltip="关闭后 benchmark 使用原始问题，不做 LLM 改写"><Switch /></Form.Item></Col>
                <Col span={12}><Form.Item name="evidenceEnabled" label="2. Evidence in Question" valuePropName="checked" tooltip="开启后将样本 evidence 以固定格式追加到问题末尾"><Switch /></Form.Item></Col>
                <Col span={12}><Form.Item name="businessKnowledgeRecallEnabled" label="3. Business Knowledge Recall" valuePropName="checked"><Switch /></Form.Item></Col>
                <Col span={12}><Form.Item name="schemaSelectionEnabled" label="4. Schema Linking" valuePropName="checked" tooltip="召回相关表/列作为提示；Text2SQL 仍接收完整 schema，不再硬过滤重要列"><Switch /></Form.Item></Col>
                <Col span={8}><Form.Item name="schemaFullIfSmall" label="Small Schema Guard" valuePropName="checked" tooltip="后端固定保护：表数不超过阈值时使用完整 schema"><Switch disabled /></Form.Item></Col>
                <Col span={8}><Form.Item name="schemaSmallTableThreshold" label="Small Schema Threshold" tooltip="小 schema 自动使用完整 schema 的表数上限"><InputNumber min={1} max={100} style={{ width: '100%' }} /></Form.Item></Col>
                <Col span={8}><Form.Item name="schemaTopK" label="Schema Hint Top-K" tooltip="大库 schema linking 的表/列提示召回上限，留空使用系统默认"><InputNumber min={1} max={100} style={{ width: '100%' }} /></Form.Item></Col>
                <Col span={12}><Form.Item name="qsqlRecallEnabled" label="5. Q-SQL Recall" valuePropName="checked"><Switch /></Form.Item></Col>
                <Col span={12}><Form.Item name="valueFoundingEnabled" label="6. Value Finding" valuePropName="checked" tooltip="提取问题中的字面值，并结合候选列做库内值验证；可独立开启"><Switch /></Form.Item></Col>
                <Col span={12}><Form.Item name="valueSearchEnabled" label="6a. Value Search" valuePropName="checked" tooltip="使用预处理建立的全库值索引，搜索真实 table.column = value 绑定"><Switch /></Form.Item></Col>
                <Col span={12}><Form.Item name="ragEnabled" label="6b. RAG Knowledge Recall" valuePropName="checked" tooltip="从 BIRD 知识库检索 schema 相关 chunks 并拼入 prompt，类似 MULTI_AGENT 的 RAG 环节"><Switch /></Form.Item></Col>
                <Col span={12}><Form.Item name="sqlFixEnabled" label="7. SQL Fix" valuePropName="checked"><Switch /></Form.Item></Col>
                <Col span={12}><Form.Item name="sqlFixMaxAttempts" label="7a. SQL Fix Attempts" tooltip="执行失败时最多修复次数，留空使用系统默认"><InputNumber min={0} max={5} style={{ width: '100%' }} /></Form.Item></Col>
                <Col span={12}><Form.Item name="sqlValidateEnabled" label="8. SQL Validate" valuePropName="checked"><Switch /></Form.Item></Col>
                <Col span={12}><Form.Item name="groupByAuditEnabled" label="8a. GROUP BY Audit" valuePropName="checked" tooltip="SQL 生成后对 GROUP BY 和聚合函数进行探测式审计"><Switch /></Form.Item></Col>
                <Col span={12}><Form.Item name="summaryEnabled" label="9. Result Summary" valuePropName="checked" tooltip="关闭后跳过结果摘要 LLM"><Switch /></Form.Item></Col>
              </Row>
            </>,
          }]} />
          <Card size="small" title="高级筛选（可选）">
            <Form.Item name="selectedDatasourceIds" label="指定数据源"><Select mode="multiple" allowClear placeholder="默认跑整个数据集" options={datasetDsOptions} /></Form.Item>
            <Form.Item name="sourceGroup" label="来源分组 (sourceGroup)"><Input allowClear placeholder="如 dw / dw_real / dev，留空表示全部" /></Form.Item>
          </Card>
        </Form>
      </Modal>

      <Modal title={caseDetail ? `样本结果 ${caseDetail.sampleCode}` : '样本结果'} open={caseDetailOpen} onCancel={() => { setCaseDetailOpen(false); setCaseDetail(null) }} footer={null} width={1100} destroyOnClose>
        {caseDetailLoading ? <div style={{ minHeight: 160, display: 'flex', justifyContent: 'center', alignItems: 'center' }}><Spin /></div>
          : caseDetail ? <div style={{ maxHeight: '70vh', overflow: 'auto' }}>
            <Descriptions column={2} size="small" bordered style={{ marginBottom: 12 }}>
              <Descriptions.Item label="状态">{caseDetail.status}</Descriptions.Item>
              <Descriptions.Item label="Execution Acc">{formatPercent(caseDetail.executionAccuracy)}</Descriptions.Item>
              <Descriptions.Item label="Table F1">{formatPercent(caseDetail.tableF1)}</Descriptions.Item>
              <Descriptions.Item label="Column F1">{formatPercent(caseDetail.columnF1)}</Descriptions.Item>
              <Descriptions.Item label="Join F1">{formatPercent(caseDetail.joinF1)}</Descriptions.Item>
              <Descriptions.Item label="Domain F1">{formatPercent(caseDetail.domainKnowledgeF1)}</Descriptions.Item>
            </Descriptions>
            <Space direction="vertical" size="middle" style={{ width: '100%' }}>
              <Descriptions column={2} size="small" bordered>
                <Descriptions.Item label="问题" span={2}>{caseDetail.questionSnapshot}</Descriptions.Item>
                <Descriptions.Item label="Gold SQL" span={2}><Paragraph copyable style={{ margin: 0, fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>{caseDetail.goldSqlSnapshot}</Paragraph></Descriptions.Item>
                <Descriptions.Item label="Generated SQL" span={2}><Paragraph copyable style={{ margin: 0, fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>{caseDetail.generatedSql ?? '-'}</Paragraph></Descriptions.Item>
              </Descriptions>
              <BenchmarkSqlResultCompare execution={caseSqlExecution} executionMatched={caseExecutionMatched} />
              <ChatbiQuerySseEventLog events={caseDetailStreamEvents} />
            </Space>
          </div> : null}
      </Modal>
      <Modal title="下载对比报告" open={compareModalOpen} onCancel={() => { setCompareModalOpen(false); setSelectedCompareRunIds([]) }}
        footer={<Space><Button onClick={() => { setCompareModalOpen(false); setSelectedCompareRunIds([]) }}>取消</Button>
          <Button type="primary" loading={downloadingCompare} disabled={selectedCompareRunIds.length < 2}
            onClick={async () => {
              setDownloadingCompare(true)
              try {
                const { downloadBenchmarkComparisonReport } = await import('../utils/benchmarkComparisonReport')
                await downloadBenchmarkComparisonReport(selectedCompareRunIds)
                message.success('对比报告已下载')
                setCompareModalOpen(false)
                setSelectedCompareRunIds([])
              } catch (e) { message.error(formatError(e)) }
              finally { setDownloadingCompare(false) }
            }}>下载</Button></Space>}
        width={800} destroyOnClose>
        <Table rowKey="id" size="small" dataSource={runs}
          rowSelection={{ type: 'checkbox', selectedRowKeys: selectedCompareRunIds, onChange: (keys) => setSelectedCompareRunIds(keys as string[]) }}
          columns={[
            { title: '任务ID', dataIndex: 'id', width: 80, ellipsis: true },
            { title: '数据集', dataIndex: 'datasetCode', width: 100 },
            { title: '版本', dataIndex: 'datasetVersion', width: 80 },
            { title: '状态', dataIndex: 'status', width: 100, render: (s: string) => <Tag color={RUN_STATUS_COLOR[s]}>{s}</Tag> },
            { title: '创建时间', dataIndex: 'createdAt', width: 160, render: (v: string) => v ?? '-' },
          ]}
          pagination={false} scroll={{ y: 400 }} />
      </Modal>
    </div>
  )
}

export default ChatbiBenchmarkTab
