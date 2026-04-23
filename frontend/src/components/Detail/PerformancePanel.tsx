import { Empty, Progress, Typography } from 'antd'
import { CheckCircleOutlined } from '@ant-design/icons'
import { useChatStore } from '../../stores/chatStore'

const STEP_COLORS: Record<string, string> = {
  '实体抽取': '#fa8c16',
  '向量搜索 (Vector Retrieval)': '#1677ff',
  向量搜索: '#1677ff',
  '图谱扩展 (KG Expansion)': '#722ed1',
  '逻辑推演与生成': '#52c41a',
  全局搜索: '#13c2c2',
}

function getStepColor(name: string): string {
  return STEP_COLORS[name] || '#8c8c8c'
}

export default function PerformancePanel() {
  const {
    currentTraceSteps,
    currentThinkingSteps,
    totalLatency,
    tokenCount,
    firstTokenLatencyMs,
    retrieveLatencyMs,
    answerCompleteLatencyMs,
    messages,
    isStreaming,
  } = useChatStore()

  const latestAssistantMessage = [...messages]
    .reverse()
    .find((message) => message.role === 'assistant')
  const traceSteps =
    currentTraceSteps.length > 0
      ? currentTraceSteps
      : !isStreaming
        ? latestAssistantMessage?.traceSteps ?? []
        : []
  const thinkingSteps =
    currentThinkingSteps.length > 0
      ? currentThinkingSteps
      : !isStreaming
        ? latestAssistantMessage?.thinkingSteps ?? []
        : []
  const resolvedTotalLatency =
    totalLatency > 0
      ? totalLatency
      : !isStreaming
        ? latestAssistantMessage?.totalLatency ?? 0
        : 0
  const resolvedTokenCount =
    tokenCount > 0
      ? tokenCount
      : !isStreaming
        ? latestAssistantMessage?.tokenCount ?? 0
        : 0
  const resolvedFirstTokenLatencyMs =
    firstTokenLatencyMs > 0
      ? firstTokenLatencyMs
      : !isStreaming
        ? latestAssistantMessage?.firstTokenLatencyMs ?? 0
        : 0
  const resolvedRetrieveLatencyMs =
    retrieveLatencyMs > 0
      ? retrieveLatencyMs
      : !isStreaming
        ? latestAssistantMessage?.retrieveLatencyMs ?? 0
        : 0
  const resolvedAnswerCompleteLatencyMs =
    answerCompleteLatencyMs > 0
      ? answerCompleteLatencyMs
      : !isStreaming
        ? latestAssistantMessage?.answerCompleteLatencyMs ?? 0
        : 0

  const stepsWithLatency = traceSteps.filter(
    (step) => step.latency !== undefined && step.latency > 0
  )
  const stepCount = traceSteps.length > 0 ? traceSteps.length : thinkingSteps.length
  const derivedTotalLatency =
    resolvedTotalLatency && resolvedTotalLatency > 0
      ? resolvedTotalLatency
      : stepsWithLatency.reduce((sum, step) => sum + (step.latency ?? 0), 0)
  const showLatencySummary = derivedTotalLatency > 0
  const showTokenSummary = resolvedTokenCount > 0
  const hasTimingBreakdown =
    resolvedFirstTokenLatencyMs > 0 ||
    resolvedRetrieveLatencyMs > 0 ||
    resolvedAnswerCompleteLatencyMs > 0

  if (stepCount === 0 && !showLatencySummary && !showTokenSummary && !hasTimingBreakdown) {
    return (
      <div style={{ padding: 12 }}>
        <Empty
          description={
            <span style={{ fontSize: 12, color: '#bbb' }}>暂无性能数据</span>
          }
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          style={{ marginTop: 60 }}
        />
      </div>
    )
  }

  return (
    <div style={{ padding: 12, height: '100%', overflowY: 'auto' }}>
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
        性能分析
      </Typography.Text>

      {(showLatencySummary || showTokenSummary) && (
        <div
          style={{
            display: 'flex',
            gap: 10,
            marginBottom: 16,
          }}
        >
          {showLatencySummary && (
            <div
              style={{
                flex: 1,
                padding: '10px 12px',
                background: '#f0f7ff',
                borderRadius: 8,
                border: '1px solid #cce0ff',
              }}
            >
              <Typography.Text type="secondary" style={{ fontSize: 10 }}>
                总延迟
              </Typography.Text>
              <div style={{ marginTop: 6 }}>
                <Typography.Text strong style={{ fontSize: 20, color: '#1677ff' }}>
                  {derivedTotalLatency.toFixed(2)}s
                </Typography.Text>
              </div>
            </div>
          )}

          {showTokenSummary && (
            <div
              style={{
                flex: 1,
                padding: '10px 12px',
                background: '#f9f0ff',
                borderRadius: 8,
                border: '1px solid #d3adf7',
              }}
            >
              <Typography.Text type="secondary" style={{ fontSize: 10 }}>
                Token 消耗
              </Typography.Text>
              <div style={{ marginTop: 6 }}>
                <Typography.Text strong style={{ fontSize: 20, color: '#722ed1' }}>
                  {resolvedTokenCount >= 1000
                    ? `${(resolvedTokenCount / 1000).toFixed(1)}k`
                    : resolvedTokenCount.toString()}
                </Typography.Text>
              </div>
            </div>
          )}
        </div>
      )}

      {hasTimingBreakdown && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
            gap: 10,
            marginBottom: 16,
          }}
        >
          <MetricCard label="首字耗时" value={resolvedFirstTokenLatencyMs} accent="#1677ff" />
          <MetricCard label="检索完成" value={resolvedRetrieveLatencyMs} accent="#13c2c2" />
          <MetricCard label="回答完成" value={resolvedAnswerCompleteLatencyMs} accent="#52c41a" />
        </div>
      )}

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          marginBottom: 14,
          padding: '8px 12px',
          background: '#f6ffed',
          borderRadius: 6,
          border: '1px solid #b7eb8f',
        }}
      >
        <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 12 }} />
        <Typography.Text style={{ fontSize: 12, color: '#52c41a' }}>
          完成 {stepCount} 个推理步骤
        </Typography.Text>
      </div>

      {stepsWithLatency.length > 0 && (
        <>
          <Typography.Text
            type="secondary"
            style={{
              fontSize: 10,
              display: 'block',
              marginBottom: 10,
              letterSpacing: '0.05em',
              textTransform: 'uppercase',
              fontWeight: 600,
            }}
          >
            各阶段耗时分布
          </Typography.Text>

          {stepsWithLatency.map((step, index) => {
            const color = getStepColor(step.node)
            const percent =
              derivedTotalLatency > 0
                ? Math.round(((step.latency ?? 0) / derivedTotalLatency) * 100)
                : undefined

            return (
              <div key={index} style={{ marginBottom: 12 }}>
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginBottom: 4,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <div
                      style={{
                        width: 6,
                        height: 6,
                        borderRadius: '50%',
                        background: color,
                        flexShrink: 0,
                      }}
                    />
                    <Typography.Text style={{ fontSize: 11, color: '#333' }}>
                      {step.node}
                    </Typography.Text>
                  </div>

                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                      {step.latency!.toFixed(2)}s
                    </Typography.Text>
                    {percent !== undefined && (
                      <Typography.Text
                        style={{ fontSize: 10, color, fontWeight: 600 }}
                      >
                        {percent}%
                      </Typography.Text>
                    )}
                  </div>
                </div>

                {percent !== undefined && (
                  <Progress
                    percent={percent}
                    size="small"
                    showInfo={false}
                    strokeColor={color}
                    trailColor="#f0f0f0"
                  />
                )}
              </div>
            )
          })}
        </>
      )}
    </div>
  )
}

function MetricCard({
  label,
  value,
  accent,
}: {
  label: string
  value: number
  accent: string
}) {
  return (
    <div
      style={{
        padding: '10px 12px',
        borderRadius: 8,
        border: `1px solid ${accent}33`,
        background: `${accent}10`,
      }}
    >
      <Typography.Text type="secondary" style={{ fontSize: 10 }}>
        {label}
      </Typography.Text>
      <div style={{ marginTop: 6 }}>
        <Typography.Text strong style={{ fontSize: 18, color: accent }}>
          {value > 0 ? `${(value / 1000).toFixed(2)}s` : '--'}
        </Typography.Text>
      </div>
    </div>
  )
}
