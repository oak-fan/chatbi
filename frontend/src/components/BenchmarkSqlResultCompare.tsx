import { Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useMemo } from 'react'
import type { BenchmarkSqlExecutionDetail, BenchmarkSqlResultPreview } from '../api/chatbiApi'

const { Text, Paragraph } = Typography

const formatCell = (value: unknown) => {
  if (value == null) return '-'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

const buildColumns = (columns: string[]): ColumnsType<Record<string, unknown>> =>
  columns.map((column) => ({ title: column, dataIndex: column, key: column, ellipsis: true, render: (value: unknown) => formatCell(value) }))

const SqlResultTable = ({ title, preview, executeMs }: { title: string; preview: BenchmarkSqlResultPreview; executeMs?: number | null }) => {
  const cols = useMemo(() => buildColumns(preview.columns), [preview.columns])
  const data = useMemo(() => preview.rows.map((row, index) => ({ ...row, key: index })), [preview.rows])
  return (
    <div>
      <Space style={{ marginBottom: 8 }} wrap>
        <Paragraph strong style={{ margin: 0 }}>{title}</Paragraph>
        {executeMs != null ? <Text type="secondary">执行耗时 {executeMs} ms</Text> : null}
        <Text type="secondary">共 {preview.rowCount} 行{preview.truncated ? `（预览前 ${preview.previewRowCount} 行）` : ''}</Text>
      </Space>
      <Table size="small" bordered scroll={{ x: true }} columns={cols} dataSource={data}
        pagination={preview.rows.length > 10 ? { pageSize: 10, size: 'small' } : false}
        locale={{ emptyText: '无数据' }} />
    </div>
  )
}

const BenchmarkSqlResultCompare = ({ execution, executionMatched }: { execution?: BenchmarkSqlExecutionDetail | null; executionMatched?: boolean | null }) => {
  const hasDetail = execution?.gold || execution?.generated || execution?.generatedError || execution?.goldError

  if (!hasDetail) {
    return <Text type="secondary" style={{ display: 'block', marginTop: 12 }}>暂无 SQL 执行结果预览</Text>
  }

  return (
    <div style={{ marginTop: 12 }}>
      <Space style={{ marginBottom: 12 }} wrap>
        <Paragraph strong style={{ margin: 0 }}>SQL 执行结果对比</Paragraph>
        {executionMatched == null ? null : executionMatched ? <Tag color="success">结果一致</Tag> : <Tag color="error">结果不一致</Tag>}
      </Space>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {execution?.gold ? <SqlResultTable title="Gold SQL 执行结果" preview={execution.gold} executeMs={execution.goldSqlExecuteMs} />
          : execution?.goldError ? <Text type="danger">Gold SQL 执行失败：{execution.goldError}</Text>
            : <Text type="secondary">Gold SQL 执行结果不可用</Text>}
        {execution?.generated ? <SqlResultTable title="Generated SQL 执行结果" preview={execution.generated} executeMs={execution.generatedSqlExecuteMs} />
          : execution?.generatedError ? <Text type="danger">Generated SQL 执行失败：{execution.generatedError}</Text>
            : <Text type="secondary">Generated SQL 执行结果不可用</Text>}
      </Space>
    </div>
  )
}

export default BenchmarkSqlResultCompare
