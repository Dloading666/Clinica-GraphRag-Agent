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
  const { currentTraceSteps, totalLatency, tokenCount } = useChatStore()

  const stepsWithLatency = currentTraceSteps.filter(
    (step) => step.latency !== undefined && step.latency > 0
  )
  const derivedTotalLatency =
    totalLatency && totalLatency > 0
      ? totalLatency
      : stepsWithLatency.reduce((sum, step) => sum + (step.latency ?? 0), 0)
  const showLatencySummary = derivedTotalLatency > 0
  const showTokenSummary = tokenCount > 0

  if (currentTraceSteps.length === 0) {
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
                  {tokenCount >= 1000
                    ? `${(tokenCount / 1000).toFixed(1)}k`
                    : tokenCount.toString()}
                </Typography.Text>
              </div>
            </div>
          )}
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
          完成 {currentTraceSteps.length} 个推理步骤
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
