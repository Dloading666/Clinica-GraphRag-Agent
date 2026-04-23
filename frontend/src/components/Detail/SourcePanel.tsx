import { Empty, Tag, Typography } from 'antd'
import { useChatStore } from '../../stores/chatStore'
import type { SourceItem, ThinkingStep, TraceStep } from '../../types'

function normalizeThinkingSteps(steps: ThinkingStep[]): TraceStep[] {
  return steps.map((step) => ({
    node: step.label,
    output: step.content,
  }))
}

function uniqueSteps(steps: TraceStep[]) {
  const seen = new Set<string>()
  return steps.filter((step) => {
    const key = `${step.node}::${step.output ?? ''}`
    if (!step.output?.trim() || seen.has(key)) {
      return false
    }
    seen.add(key)
    return true
  })
}

function buildFallbackSources(steps: TraceStep[]): SourceItem[] {
  return uniqueSteps(steps).map((step, index) => ({
    id: `trace:${step.node}:${index}`,
    source_type: 'chunk',
    label: step.node,
    title: `来源片段 ${index + 1}`,
    content: step.output ?? '',
  }))
}

function getTagColor(sourceType: string) {
  switch (sourceType) {
    case 'chunk':
      return 'blue'
    case 'entity':
      return 'purple'
    case 'relation':
      return 'geekblue'
    case 'community':
      return 'cyan'
    default:
      return 'default'
  }
}

export default function SourcePanel() {
  const { currentTraceSteps, currentThinkingSteps, messages, isStreaming } = useChatStore()

  const latestAssistantMessage = [...messages]
    .reverse()
    .find((message) => message.role === 'assistant')

  const liveTraceSteps =
    currentTraceSteps.length > 0
      ? currentTraceSteps
      : normalizeThinkingSteps(currentThinkingSteps)
  const archivedTraceSteps = latestAssistantMessage?.traceSteps?.length
    ? latestAssistantMessage.traceSteps
    : normalizeThinkingSteps(latestAssistantMessage?.thinkingSteps ?? [])

  const sourceItems =
    latestAssistantMessage?.sourceItems && latestAssistantMessage.sourceItems.length > 0
      ? latestAssistantMessage.sourceItems
      : buildFallbackSources(
          liveTraceSteps.length > 0 ? liveTraceSteps : !isStreaming ? archivedTraceSteps : []
        )

  if (sourceItems.length === 0) {
    return (
      <div style={{ padding: 12 }}>
        <Empty
          description={
            <span style={{ fontSize: 12, color: '#bbb' }}>
              当前还没有可展示的源内容
            </span>
          }
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          style={{ marginTop: 60 }}
        />
      </div>
    )
  }

  return (
    <div
      style={{
        padding: 12,
        minHeight: '100%',
        boxSizing: 'border-box',
      }}
    >
      <Typography.Text
        type="secondary"
        style={{
          fontSize: 10,
          letterSpacing: '0.1em',
          display: 'block',
          marginBottom: 14,
          textTransform: 'uppercase',
          fontWeight: 600,
        }}
      >
        SOURCE CONTEXT
      </Typography.Text>

      {sourceItems.map((source, index) => (
        <div
          key={source.id || `${source.source_type}-${index}`}
          style={{
            marginBottom: 12,
            padding: '12px 12px 10px',
            borderRadius: 10,
            border: '1px solid #eaecf0',
            background: '#fff',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 8,
              marginBottom: 8,
            }}
          >
            <Typography.Text strong style={{ fontSize: 13 }}>
              {source.title || `来源片段 ${index + 1}`}
            </Typography.Text>
            <Tag color={getTagColor(source.source_type)} style={{ margin: 0 }}>
              {source.label}
            </Tag>
          </div>

          {source.document_name ? (
            <Typography.Text
              type="secondary"
              style={{
                display: 'block',
                marginBottom: 8,
                fontSize: 11,
              }}
            >
              来源文档：{source.document_name}
            </Typography.Text>
          ) : null}

          <Typography.Paragraph
            style={{
              margin: 0,
              fontSize: 12,
              lineHeight: 1.7,
              color: '#4b5563',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}
          >
            {source.content}
          </Typography.Paragraph>
        </div>
      ))}
    </div>
  )
}
