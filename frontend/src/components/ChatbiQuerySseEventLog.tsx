import { Card, Collapse, Empty, Tag, Typography } from 'antd'
import type { ChatbiStreamEvent } from '../api/chatbiApi'

const { Text } = Typography

const EVENT_COLOR: Record<string, string> = {
  started: 'default',
  rewritten_question: 'blue',
  business_knowledge_recall: 'cyan',
  intent: 'geekblue',
  schema_linking: 'purple',
  schema_selected: 'purple',
  qsql_recall: 'cyan',
  sql_candidates: 'magenta',
  clarification_required: 'gold',
  sql: 'success',
  sql_validate: 'volcano',
  sql_group_audit: 'geekblue',
  data: 'green',
  value_founding: 'orange',
  value_search: 'orange',
  rag_knowledge_recall: 'cyan',
  round_start: 'default',
  round_end: 'default',
  thinking: 'blue',
  sql_update: 'purple',
  tool_call: 'gold',
  tool_result: 'cyan',
  final: 'success',
  summary: 'orange',
  completed: 'default',
  failed: 'error',
}

const formatEventSummary = (event: ChatbiStreamEvent) => {
  switch (event.event) {
    case 'rewritten_question': return event.question
    case 'intent': return [event.intent, event.datasourceId].filter(Boolean).join(' · ')
    case 'schema_linking': {
      const linking = event.schemaLinking ?? {}
      const mode = linking.mode == null ? 'schema linking' : String(linking.mode)
      const tableCandidates = Array.isArray(linking.tableCandidates) ? linking.tableCandidates.length : 0
      const columnCandidates = Array.isArray(linking.columnCandidates) ? linking.columnCandidates.length : 0
      const fieldCount = typeof linking.fieldCount === 'number' ? linking.fieldCount : event.fields?.length
      return [
        mode,
        fieldCount == null ? undefined : `${fieldCount} fields`,
        tableCandidates ? `${tableCandidates} tables` : undefined,
        columnCandidates ? `${columnCandidates} columns` : undefined,
      ].filter(Boolean).join(' Â· ')
    }
    case 'schema_selected': return `${event.fields?.length ?? 0} fields`
    case 'business_knowledge_recall':
    case 'qsql_recall': return `${event.items?.length ?? 0} items`
    case 'sql_candidates': {
      const items = (event.items ?? []) as { selected?: boolean; pathName?: string }[]
      const selected = items.find((item) => item.selected)
      return `${items.length} candidates${selected?.pathName ? ` · ${selected.pathName}` : ''}`
    }
    case 'sql': return event.fixed ? 'SQL (fixed)' : 'SQL'
    case 'sql_validate': {
      const changed = event.validation?.changed
      const latencyMs = event.validation?.latencyMs
      return [changed == null ? undefined : changed ? 'changed' : 'unchanged', latencyMs == null ? undefined : `${latencyMs}ms`].filter(Boolean).join(' · ')
    }
    case 'sql_group_audit': {
      const ga = event.groupAudit
      const phase = ga?.phase
      const round = ga?.round
      const thought = ga?.thought
      const tool = ga?.tool
      if (phase === 'tool_call') return `R${round} call: ${tool}`
      if (phase === 'tool_result') return `R${round} result: ${tool}`
      if (phase === 'final') return `final · ${thought || ga?.sql || ''}`
      if (phase === 'thinking') return `R${round} · ${thought || ''}`
      return phase ?? 'group_audit'
    }
    case 'data': return `${event.rows?.length ?? 0} rows`
    case 'value_founding': {
      const literalsCount = event.valueFoundingLiterals?.length ?? 0
      const matchesCount = event.valueFoundingMatches?.length ?? 0
      return `${literalsCount} literals, ${matchesCount} matches`
    }
    case 'value_search': return `${event.valueSearchMatches?.length ?? 0} matches`
    case 'rag_knowledge_recall': return `${event.ragKnowledgeHits?.length ?? 0} chunks`
    case 'round_start': return event.round == null ? 'round start' : `round ${event.round}`
    case 'round_end': return event.round == null ? 'round end' : `round ${event.round}`
    case 'thinking': return event.content
    case 'sql_update': return [
      event.round == null ? undefined : `round ${event.round}`,
      event.confidence == null ? undefined : `confidence ${event.confidence.toFixed(2)}`,
    ].filter(Boolean).join(' · ')
    case 'tool_call': return event.tool
    case 'tool_result': return event.tool
    case 'final': return [
      'final SQL',
      event.confidence == null ? undefined : `confidence ${event.confidence.toFixed(2)}`,
    ].filter(Boolean).join(' · ')
    case 'summary':
    case 'failed': return event.text ?? (event.error ? JSON.stringify(event.error) : undefined)
    default: return undefined
  }
}

type Props = {
  events: ChatbiStreamEvent[]
  maxHeight?: number
  emptyText?: string
}

const ChatbiQuerySseEventLog = ({ events, maxHeight = 320, emptyText = '无 SSE 事件记录' }: Props) => {
  if (events.length === 0) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyText} />

  return (
    <Card size="small" title={`SSE 事件 (${events.length})`}>
      <Collapse
        size="small"
        style={{ maxHeight, overflow: 'auto' }}
        items={events.map((event, index) => {
          const summary = formatEventSummary(event)
          return {
            key: String(index),
            label: (
              <span>
                <Text type="secondary" style={{ marginRight: 8 }}>{index + 1}.</Text>
                <Tag color={EVENT_COLOR[event.event] ?? 'default'}>{event.event}</Tag>
                {summary ? <Text ellipsis style={{ marginLeft: 8, maxWidth: 520 }}>{summary}</Text> : null}
              </span>
            ),
            children: <pre style={{ margin: 0, fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{JSON.stringify(event, null, 2)}</pre>,
          }
        })}
      />
    </Card>
  )
}

export default ChatbiQuerySseEventLog
