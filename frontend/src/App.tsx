import { Button, Card, Checkbox, Col, Form, Input, InputNumber, Modal, Row, Select, Space, Switch, Table, Tabs, Tooltip, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  createBusinessKnowledge, createDatasource, createQsql,
  deleteBusinessKnowledge, deleteDatasource, deleteQsql,
  executeDatasourceSql, fetchBusinessKnowledgeList, fetchDatasources, fetchQsqlList,
  preprocessDatasource, runQueryStream, testDatasourceConnection,
  updateBusinessKnowledge, updateQsql,
  SCHEMA_FORMATS, SCHEMA_FORMAT_LABELS, PROMPT_FORMATS, PROMPT_FORMAT_LABELS,
  type ChatbiBusinessKnowledgeKind, type ChatbiBusinessKnowledgeRecord, type ChatbiBusinessKnowledgeScope,
  type ChatbiDatasourceRecord, type ChatbiStreamEvent, type ChatbiSqlCandidateItem, type ChatbiQsqlRecord, type SqlCandidatePath,
} from './api/chatbiApi'
import ChatbiBenchmarkTab from './components/ChatbiBenchmarkTab'

const { Paragraph } = Typography
const { TextArea } = Input

const BIZ_SCOPES: ChatbiBusinessKnowledgeScope[] = ['GLOBAL', 'SYSTEM_INFERRED']
const BIZ_KINDS: ChatbiBusinessKnowledgeKind[] = ['DIMENSION', 'METRIC', 'TIME', 'TERM']

const formatError = (e: unknown) => (e instanceof Error ? e.message : '操作失败')

// --- Datasource Tab ---

const DatasourceTab = ({ datasources, loading, onRefresh }: { datasources: ChatbiDatasourceRecord[]; loading: boolean; onRefresh: () => Promise<void> }) => {
  const [pgModalOpen, setPgModalOpen] = useState(false)
  const [sqlModal, setSqlModal] = useState<{ id: string; sql: string } | null>(null)
  const [sqlResult, setSqlResult] = useState<{ columns: string[]; rows: Record<string, unknown>[]; truncated: boolean } | null>(null)
  const [pgForm] = Form.useForm()

  const cols: ColumnsType<ChatbiDatasourceRecord> = [
    { title: 'ID', dataIndex: 'id', width: 180, ellipsis: true }, { title: '名称', dataIndex: 'name' }, { title: '类型', dataIndex: 'connectorType', width: 110 },
    { title: 'Schema', width: 80, render: (_, r) => (r.dbSchema ? '有' : '无') },
    { title: 'Schema 更新', dataIndex: 'dbSchemaUpdatedAt', width: 170, ellipsis: true },
    { title: '操作', width: 300, render: (_, r) => <Space size="small">
      <Button size="small" onClick={async () => { try { await testDatasourceConnection(r.id); message.success('连接成功') } catch (e) { message.error(formatError(e)) } }}>测连</Button>
      <Button size="small" onClick={async () => { try { const t = await preprocessDatasource(r.id); message.success(`预处理已入队，taskId=${t.taskId}`) } catch (e) { message.error(formatError(e)) } }}>预处理</Button>
      <Button size="small" onClick={() => setSqlModal({ id: r.id, sql: 'SELECT 1' })}>执行 SQL</Button>
      <Button size="small" danger onClick={() => Modal.confirm({ title: '删除数据源？', onOk: async () => { await deleteDatasource(r.id); message.success('已删除'); await onRefresh() } })}>删除</Button>
    </Space> },
  ]

  return <>
    <Space style={{ marginBottom: 12 }}>
      <Button type="primary" onClick={() => { pgForm.resetFields(); pgForm.setFieldsValue({ type: 'POSTGRESQL', port: 5432 }); setPgModalOpen(true) }}>新建 PostgreSQL</Button>
      <Button onClick={() => void onRefresh()} loading={loading}>刷新</Button>
    </Space>
    <Table rowKey="id" size="small" loading={loading} dataSource={datasources} columns={cols} pagination={false} />
    <Modal title="新建 PostgreSQL 数据源" open={pgModalOpen} onCancel={() => setPgModalOpen(false)} onOk={() => void pgForm.submit()} width={560} destroyOnClose>
      <Form form={pgForm} layout="vertical" onFinish={async (v) => { try { const { type, ...rest } = v; await createDatasource({ ...rest, connectorType: type }); message.success('创建成功'); setPgModalOpen(false); await onRefresh() } catch (e) { message.error(formatError(e)) } }}>
        <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="type" label="类型" rules={[{ required: true }]}><Input disabled /></Form.Item>
        <Form.Item name="host" label="Host" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="port" label="Port" rules={[{ required: true }]}><InputNumber style={{ width: '100%' }} /></Form.Item>
        <Form.Item name="database" label="Database" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="schemaName" label="Schema"><Input placeholder="public" /></Form.Item>
        <Form.Item name="username" label="Username" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="password" label="Password" rules={[{ required: true }]}><Input.Password /></Form.Item>
        <Form.Item name="remark" label="备注"><Input /></Form.Item>
      </Form>
    </Modal>
    <Modal title="执行 SQL" open={Boolean(sqlModal)} onCancel={() => { setSqlModal(null); setSqlResult(null) }} onOk={async () => { if (!sqlModal?.sql.trim()) return; try { setSqlResult(await executeDatasourceSql(sqlModal.id, sqlModal.sql)) } catch (e) { message.error(formatError(e)) } }} width={720}>
      <TextArea rows={4} value={sqlModal?.sql ?? ''} onChange={(e) => setSqlModal(prev => (prev ? { ...prev, sql: e.target.value } : null))} />
      {sqlResult ? <Table style={{ marginTop: 12 }} size="small" scroll={{ x: true }} dataSource={sqlResult.rows.map((r, i) => ({ ...r, key: i }))} columns={sqlResult.columns.map(c => ({ title: c, dataIndex: c }))} pagination={{ pageSize: 10 }} footer={() => sqlResult.truncated ? '结果已截断' : undefined} /> : null}
    </Modal>
  </>
}

// --- QSQL Tab ---

const QsqlTab = ({ datasourceOptions, onRefreshDs }: { datasourceOptions: { label: string; value: string }[]; onRefreshDs: () => Promise<void> }) => {
  const [dsId, setDsId] = useState<string>()
  const [records, setRecords] = useState<ChatbiQsqlRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<ChatbiQsqlRecord | null>(null)
  const [form] = Form.useForm()
  const load = useCallback(async () => { setLoading(true); try { setRecords((await fetchQsqlList({ page: 1, pageSize: 100, datasourceId: dsId })).records ?? []) } catch (e) { message.error(formatError(e)) } finally { setLoading(false) } }, [dsId])
  useEffect(() => { void load() }, [load])
  const cols: ColumnsType<ChatbiQsqlRecord> = [
    { title: 'ID', dataIndex: 'id', width: 160, ellipsis: true }, { title: '数据源', dataIndex: 'datasourceId', width: 160, ellipsis: true },
    { title: '问题', dataIndex: 'question', ellipsis: true }, { title: 'SQL', dataIndex: 'sqlBody', ellipsis: true },
    { title: '操作', width: 140, render: (_, r) => <Space>
      <Button size="small" onClick={() => { setEditing(r); form.setFieldsValue(r); setModalOpen(true) }}>编辑</Button>
      <Button size="small" danger onClick={() => Modal.confirm({ title: '删除 Q-SQL？', onOk: async () => { await deleteQsql(r.id); message.success('已删除'); await load() } })}>删除</Button>
    </Space> },
  ]
  return <>
    <Space style={{ marginBottom: 12 }} wrap>
      <Select allowClear placeholder="按数据源筛选" style={{ width: 280 }} options={datasourceOptions} value={dsId} onChange={setDsId} />
      <Button onClick={() => void onRefreshDs()}>刷新数据源列表</Button>
      <Button onClick={() => void load()} loading={loading}>刷新 Q-SQL</Button>
      <Button type="primary" onClick={() => { setEditing(null); form.setFieldsValue({ datasourceId: dsId, question: '', sqlBody: '' }); setModalOpen(true) }}>新建</Button>
    </Space>
    <Table rowKey="id" size="small" loading={loading} dataSource={records} columns={cols} />
    <Modal title={editing ? '编辑 Q-SQL' : '新建 Q-SQL'} open={modalOpen} onCancel={() => setModalOpen(false)} onOk={() => void form.submit()} width={640} destroyOnClose>
      <Form form={form} layout="vertical" onFinish={async (v) => { try { if (editing) await updateQsql(editing.id, { question: v.question, sqlBody: v.sqlBody }); else await createQsql(v); message.success('保存成功'); setModalOpen(false); await load() } catch (e) { message.error(formatError(e)) } }}>
        <Form.Item name="datasourceId" label="数据源" rules={[{ required: true }]}><Select options={datasourceOptions} /></Form.Item>
        <Form.Item name="question" label="问题" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="sqlBody" label="SQL" rules={[{ required: true }]}><TextArea rows={6} /></Form.Item>
      </Form>
    </Modal>
  </>
}

// --- Business Knowledge Tab ---

const BizKnowledgeTab = ({ datasourceOptions }: { datasourceOptions: { label: string; value: string }[] }) => {
  const [dsId, setDsId] = useState<string>()
  const [records, setRecords] = useState<ChatbiBusinessKnowledgeRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<ChatbiBusinessKnowledgeRecord | null>(null)
  const [form] = Form.useForm()
  const load = useCallback(async () => { setLoading(true); try { setRecords((await fetchBusinessKnowledgeList({ page: 1, pageSize: 100, datasourceId: dsId })).records ?? []) } catch (e) { message.error(formatError(e)) } finally { setLoading(false) } }, [dsId])
  useEffect(() => { void load() }, [load])
  const cols: ColumnsType<ChatbiBusinessKnowledgeRecord> = [
    { title: 'ID', dataIndex: 'id', width: 160, ellipsis: true }, { title: 'scope', dataIndex: 'scope', width: 130 }, { title: 'kind', dataIndex: 'kind', width: 100 },
    { title: '数据源', dataIndex: 'datasourceId', width: 160, ellipsis: true }, { title: '内容', dataIndex: 'content', ellipsis: true },
    { title: '操作', width: 140, render: (_, r) => <Space>
      <Button size="small" onClick={() => { setEditing(r); form.setFieldsValue(r); setModalOpen(true) }}>编辑</Button>
      <Button size="small" danger onClick={() => Modal.confirm({ title: '删除业务字典？', onOk: async () => { await deleteBusinessKnowledge(r.id); message.success('已删除'); await load() } })}>删除</Button>
    </Space> },
  ]
  return <>
    <Space style={{ marginBottom: 12 }} wrap>
      <Select allowClear placeholder="按数据源筛选" style={{ width: 280 }} options={datasourceOptions} value={dsId} onChange={setDsId} />
      <Button onClick={() => void load()} loading={loading}>刷新</Button>
      <Button type="primary" onClick={() => { setEditing(null); form.setFieldsValue({ datasourceId: dsId, scope: 'GLOBAL', kind: 'TERM', content: '' }); setModalOpen(true) }}>新建</Button>
    </Space>
    <Table rowKey="id" size="small" loading={loading} dataSource={records} columns={cols} />
    <Modal title={editing ? '编辑业务字典' : '新建业务字典'} open={modalOpen} onCancel={() => setModalOpen(false)} onOk={() => void form.submit()} width={640} destroyOnClose>
      <Form form={form} layout="vertical" onFinish={async (v) => { try { if (editing) await updateBusinessKnowledge(editing.id, v); else await createBusinessKnowledge(v); message.success('保存成功'); setModalOpen(false); await load() } catch (e) { message.error(formatError(e)) } }}>
        <Form.Item name="datasourceId" label="数据源" rules={[{ required: true }]}><Select options={datasourceOptions} /></Form.Item>
        <Form.Item name="scope" label="scope" rules={[{ required: true }]}><Select options={BIZ_SCOPES.map(v => ({ label: v, value: v }))} /></Form.Item>
        <Form.Item name="kind" label="kind" rules={[{ required: true }]}><Select options={BIZ_KINDS.map(v => ({ label: v, value: v }))} /></Form.Item>
        <Form.Item name="content" label="内容" rules={[{ required: true }]}><TextArea rows={4} /></Form.Item>
      </Form>
    </Modal>
  </>
}

// --- Query Tab ---

const QueryTab = ({ datasourceOptions }: { datasourceOptions: { label: string; value: string }[] }) => {
  const [datasourceId, setDatasourceId] = useState<string>()
  const [question, setQuestion] = useState('')
  const [sqlCandidatePaths, setSqlCandidatePaths] = useState<SqlCandidatePath[]>(['ddl:chain_of_thought'])
  const [streaming, setStreaming] = useState(false)
  const [executingSql, setExecutingSql] = useState(false)
  const [events, setEvents] = useState<ChatbiStreamEvent[]>([])
  const [lastSql, setLastSql] = useState<string>()
  const [lastSummary, setLastSummary] = useState<string>()
  const [lastSqlCandidates, setLastSqlCandidates] = useState<ChatbiSqlCandidateItem[]>([])
  const [dataPreview, setDataPreview] = useState<{ columns: string[]; rows: Record<string, unknown>[] } | null>(null)
  const [clarification, setClarification] = useState<{ token: string; question: string; options: string[] } | null>(null)
  const [pipelineOptions, setPipelineOptions] = useState({
    rewriteEnabled: false,
    summaryEnabled: false,
    businessKnowledgeRecallEnabled: false,
    schemaSelectionEnabled: false,
    qsqlRecallEnabled: false,
    sqlFixEnabled: false,
    sqlValidateEnabled: false,
    valueFoundingEnabled: false,
    valueSearchEnabled: false,
    groupByAuditEnabled: false,
    ragEnabled: false,
  })
  const abortRef = useRef<AbortController | null>(null)

  const appendEvent = (event: ChatbiStreamEvent) => {
    setEvents(prev => [...prev, event])
    if (event.sql) { setLastSql(event.sql); setExecutingSql(true) }
    if (event.event === 'sql_candidates') setLastSqlCandidates((event.items ?? []) as ChatbiSqlCandidateItem[])
    if (event.event === 'data' || event.event === 'summary' || event.event === 'failed' || event.event === 'completed') setExecutingSql(false)
    if (event.text) setLastSummary(event.text)
    if (event.columns && event.rows) setDataPreview({ columns: event.columns, rows: event.rows })
    if (event.event === 'clarification_required' && event.token) { setClarification({ token: event.token, question: event.question ?? '', options: event.options ?? [] }); setQuestion('') }
  }

  const runQuery = async (payload: { question: string; datasourceId?: string; clarificationToken?: string; clarificationSkip?: boolean; sqlCandidatePaths: SqlCandidatePath[] } & Record<string, unknown>) => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setStreaming(true)
    setExecutingSql(false)
    if (!payload.clarificationToken) { setClarification(null); setLastSqlCandidates([]) }
    try {
      for await (const event of runQueryStream(payload, { signal: controller.signal })) {
        appendEvent(event)
        if (payload.clarificationToken && ['sql', 'data', 'summary', 'completed', 'failed'].includes(event.event)) setClarification(null)
        if (event.event === 'failed') message.error(event.error ? JSON.stringify(event.error) : '问数失败')
      }
    } catch (e) {
      if (!(e instanceof DOMException && e.name === 'AbortError')) message.error(formatError(e))
    } finally { setStreaming(false); setExecutingSql(false); abortRef.current = null }
  }

  const handleSend = () => {
    if (sqlCandidatePaths.length === 0) { message.warning('Please select at least one candidate path'); return }
    if (clarification) {
      const text = question.trim()
      if (!text) { message.warning('请输入澄清内容'); return }
      void runQuery({ question: text, datasourceId: datasourceId || undefined, clarificationToken: clarification.token, clarificationSkip: false, sqlCandidatePaths, ...pipelineOptions })
      setQuestion('')
      return
    }
    const q = question.trim()
    if (!q) { message.warning('请输入问题'); return }
    void runQuery({ question: q, datasourceId: datasourceId || undefined, sqlCandidatePaths, ...pipelineOptions })
    setQuestion('')
  }

  return <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
    <div style={{ flex: 1, minWidth: 0 }}>
      <Card title="问数" size="small">
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Select allowClear placeholder="数据源（可选）" style={{ width: '100%' }} options={datasourceOptions} value={datasourceId} onChange={setDatasourceId} />
          <Card size="small" title="候选路径" style={{ marginBottom: 0 }}>
            <Row gutter={[8, 4]}>
              {SCHEMA_FORMATS.map(schema => (
                <Col key={schema} span={12}>
                  <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 2, color: '#666' }}>{SCHEMA_FORMAT_LABELS[schema]}</div>
                  <Checkbox.Group
                    options={PROMPT_FORMATS.map(p => ({ label: PROMPT_FORMAT_LABELS[p], value: `${schema}:${p}` as SqlCandidatePath }))}
                    value={sqlCandidatePaths.filter(p => p.startsWith(schema + ':'))}
                    onChange={(checked) => {
                      const checkedSchema = checked as SqlCandidatePath[]
                      const otherPaths = sqlCandidatePaths.filter(p => !p.startsWith(schema + ':'))
                      setSqlCandidatePaths([...otherPaths, ...checkedSchema].sort())
                    }}
                  />
                </Col>
              ))}
            </Row>
          </Card>
          <Card size="small" title="Pipeline 选项" style={{ marginBottom: 0 }}>
            <Row gutter={[16, 8]}>
              {([
                { key: 'rewriteEnabled', label: '问题改写' },
                { key: 'summaryEnabled', label: '结果摘要' },
                { key: 'businessKnowledgeRecallEnabled', label: '业务知识召回' },
                { key: 'schemaSelectionEnabled', label: 'Schema Linking', tooltip: '召回相关表/列作为提示；Text2SQL 仍接收完整 schema，小 schema 自动走全量 schema' },
                { key: 'qsqlRecallEnabled', label: 'Q-SQL 召回' },
                { key: 'sqlFixEnabled', label: 'SQL 修复' },
                { key: 'sqlValidateEnabled', label: 'SQL 验证' },
                { key: 'valueFoundingEnabled', label: 'Value Finding', tooltip: '提取问题中的字面值，并结合候选列做库内值验证；可独立开启' },
                { key: 'valueSearchEnabled', label: 'Value Search', tooltip: '使用预处理建立的全库值索引，搜索真实 table.column = value 绑定' },
                { key: 'groupByAuditEnabled', label: 'GROUP BY 审计' },
                { key: 'ragEnabled', label: 'RAG 知识召回' },
              ] satisfies readonly { key: keyof typeof pipelineOptions; label: string; tooltip?: string }[]).map(({ key, label, tooltip }) => (
                <Col key={key} span={8}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <Switch
                      size="small"
                      checked={pipelineOptions[key]}
                      onChange={(v) => setPipelineOptions(prev => ({ ...prev, [key]: v }))}
                    />
                    {tooltip ? (
                      <Tooltip title={tooltip} placement="topLeft">
                        <span style={{ fontSize: 12, color: '#666' }}>{label}</span>
                      </Tooltip>
                    ) : (
                      <span style={{ fontSize: 12, color: '#666' }}>{label}</span>
                    )}
                  </div>
                </Col>
              ))}
            </Row>
          </Card>
          {clarification ? (
            <Card size="small" title="需要澄清" style={{ border: '1px solid #d48806' }} styles={{ header: { background: '#ffc53d', borderBottom: '1px solid #d48806', color: '#612500', fontWeight: 600 }, body: { background: '#fff1b8', color: 'rgba(0, 0, 0, 0.88)' } }}>
              <Paragraph style={{ marginBottom: 12, color: 'rgba(0, 0, 0, 0.88)' }}>{clarification.question || '请补充信息后继续问数'}</Paragraph>
              {clarification.options.length > 0 ? <Space wrap style={{ marginBottom: 12 }}>{clarification.options.map(opt => <Button key={opt} size="small" loading={streaming} onClick={() => { void runQuery({ question: opt, datasourceId: datasourceId || undefined, clarificationToken: clarification.token, clarificationSkip: false, sqlCandidatePaths, ...pipelineOptions }); setQuestion('') }}>{opt}</Button>)}</Space> : null}
              <TextArea rows={2} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder={clarification.options.length > 0 ? '也可在此输入其它澄清内容' : '请在此输入澄清内容'}
                onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); handleSend() } }} />
              <Space wrap style={{ marginTop: 8 }}>
                <Button type="primary" loading={streaming} onClick={handleSend}>提交</Button>
                <Button loading={streaming} onClick={() => { void runQuery({ question: '（用户选择跳过澄清）', datasourceId: datasourceId || undefined, clarificationToken: clarification.token, clarificationSkip: true, sqlCandidatePaths, ...pipelineOptions }); setQuestion('') }}>跳过</Button>
                <Button disabled={streaming} onClick={() => { setClarification(null); setQuestion('') }}>取消</Button>
              </Space>
            </Card>
          ) : <TextArea rows={3} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="输入自然语言问题" onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); handleSend() } }} />}
          <Space wrap>
            {!clarification ? <Button type="primary" loading={streaming} onClick={handleSend}>发送问数</Button> : null}
            <Button disabled={!streaming} onClick={() => abortRef.current?.abort()}>中止</Button>
            <Button onClick={() => { setEvents([]); setLastSqlCandidates([]) }}>清空日志</Button>
          </Space>
          {lastSql ? <Card size="small" title="SQL"><Paragraph copyable style={{ margin: 0, fontFamily: 'monospace' }}>{lastSql}</Paragraph>{executingSql ? <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>正在执行 SQL…</Paragraph> : null}</Card> : null}
          {lastSqlCandidates.length > 0 ? <Card size="small" title="SQL Candidates">
            <Table rowKey={(_, i) => String(i)} size="small" scroll={{ x: true }} dataSource={lastSqlCandidates} pagination={false}
              columns={[
                { title: 'Path', dataIndex: 'pathName', width: 220, ellipsis: true },
                { title: 'Selected', dataIndex: 'selected', width: 90, render: (s?: boolean) => s ? 'Yes' : '' },
                { title: 'Score', dataIndex: 'score', width: 90, render: (s?: number) => s == null ? '-' : s.toFixed(2) },
                { title: 'Rows', dataIndex: 'rowCount', width: 80, render: (rc?: number) => rc ?? '-' },
                { title: 'Status', width: 180, render: (_, r) => r.executeError || r.generationError || 'OK' },
                { title: 'SQL', dataIndex: 'sql', render: (sql?: string) => <Paragraph copyable={Boolean(sql)} style={{ margin: 0, fontFamily: 'monospace' }}>{sql || '-'}</Paragraph> },
              ]} />
          </Card> : null}
          {dataPreview ? <Table size="small" scroll={{ x: true }} dataSource={dataPreview.rows.map((r, i) => ({ ...r, key: i }))} columns={dataPreview.columns.map(c => ({ title: c, dataIndex: c }))} pagination={{ pageSize: 10 }} /> : null}
          {lastSummary ? <Card size="small" title="Summary"><Paragraph style={{ margin: 0 }}>{lastSummary}</Paragraph></Card> : null}
          <Card size="small" title="SSE 事件日志"><pre style={{ maxHeight: 240, overflow: 'auto', fontSize: 11, margin: 0 }}>{events.map((e, i) => `${i + 1}. ${e.event} ${JSON.stringify(e)}\n`).join('')}</pre></Card>
        </Space>
      </Card>
    </div>
  </div>
}

// --- Main App ---

const App = () => {
  const [datasources, setDatasources] = useState<ChatbiDatasourceRecord[]>([])
  const [loadingDs, setLoadingDs] = useState(false)
  const [activeTab, setActiveTab] = useState('datasource')

  const loadDatasources = useCallback(async () => {
    setLoadingDs(true)
    try { setDatasources((await fetchDatasources({ page: 1, pageSize: 100 })).records ?? []) } catch (e) { message.error(formatError(e)) } finally { setLoadingDs(false) }
  }, [])

  useEffect(() => { void loadDatasources() }, [loadDatasources])

  const datasourceOptions = useMemo(() => datasources.map(d => ({ label: `${d.name} (${d.id})`, value: d.id })), [datasources])

  return (
    <div style={{ padding: 16 }}>
      <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
        { key: 'datasource', label: '数据源', children: <DatasourceTab datasources={datasources} loading={loadingDs} onRefresh={loadDatasources} /> },
        { key: 'qsql', label: 'Q-SQL', children: <QsqlTab datasourceOptions={datasourceOptions} onRefreshDs={loadDatasources} /> },
        { key: 'biz', label: '业务字典', children: <BizKnowledgeTab datasourceOptions={datasourceOptions} /> },
        { key: 'query', label: '问数', children: <QueryTab datasourceOptions={datasourceOptions} /> },
        { key: 'benchmark', label: '基准评价', children: <ChatbiBenchmarkTab /> },
      ]} />
    </div>
  )
}

export default App
