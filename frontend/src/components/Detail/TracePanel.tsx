import { Typography, Divider, Tag } from 'antd'
import { CheckCircleFilled, LoadingOutlined } from '@ant-design/icons'
import { useChatStore } from '../../stores/chatStore'

const NODE_COLORS: Record<string, string> = {
  '实体抽取': '#fa8c16',
  '向量搜索 (Vector Retrieval)': '#1677ff',
  '向量搜索': '#1677ff',
  '图谱扩展 (KG Expansion)': '#722ed1',
  '图谱汇总': '#722ed1',
  '逻辑推演与生成': '#52c41a',
  '全局搜索': '#13c2c2',
  '关键词提取': '#eb2f96',
  '缓存命中': '#52c41a',
  '全局缓存命中': '#52c41a',
}

function getNodeColor(nodeName: string): string {
  return NODE_COLORS[nodeName] || '#8c8c8c'
}

export default function TracePanel() {
  const { currentTraceSteps, totalLatency, tokenCount, isStreaming } =
    useChatStore()

  if (currentTraceSteps.length === 0) {
    return (
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          paddingTop: 60,
          padding: 16,
        }}
      >
        {isStreaming ? (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12, paddingTop: 40 }}>
            <LoadingOutlined style={{ fontSize: 24, color: '#1677ff' }} />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              执行中，等待轨迹数据...
            </Typography.Text>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8, paddingTop: 40 }}>
            <span style={{ fontSize: 32 }}>🔍</span>
            <Typography.Text type="secondary" style={{ fontSize: 12, textAlign: 'center' }}>
              发送消息后查看执行轨迹
            </Typography.Text>
          </div>
        )}
      </div>
    )
  }

  return (
    <div style={{ padding: '14px 12px' }}>
      {/* Trace Sequence Header */}
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
        TRACE SEQUENCE
      </Typography.Text>

      {/* Trace Steps */}
      <div style={{ position: 'relative', paddingLeft: 16 }}>
        {/* Vertical connecting line */}
        {currentTraceSteps.length > 1 && (
          <div
            style={{
              position: 'absolute',
              left: 3,
              top: 8,
              bottom: 8,
              width: 1,
              background: '#e8e8e8',
            }}
          />
        )}

        {currentTraceSteps.map((step, i) => {
          const color = getNodeColor(step.node)
          return (
            <div
              key={i}
              style={{
                display: 'flex',
                gap: 10,
                marginBottom: 14,
                position: 'relative',
              }}
            >
              {/* Step dot */}
              <div
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: color,
                  marginTop: 4,
                  flexShrink: 0,
                  position: 'absolute',
                  left: -13,
                  boxShadow: `0 0 0 2px ${color}30`,
                }}
              />

              <div style={{ flex: 1 }}>
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    gap: 6,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                    <span style={{ fontSize: 11 }}>{step.icon}</span>
                    <Typography.Text
                      style={{
                        fontSize: 12,
                        fontWeight: 500,
                        color: '#1a1a2e',
                      }}
                    >
                      {step.node}
                    </Typography.Text>
                  </div>
                  {step.latency !== undefined && (
                    <Tag
                      style={{
                        fontSize: 10,
                        lineHeight: '16px',
                        padding: '0 5px',
                        color: color,
                        borderColor: `${color}40`,
                        background: `${color}10`,
                        flexShrink: 0,
                      }}
                    >
                      {step.latency.toFixed(2)}s
                    </Tag>
                  )}
                </div>
                {step.output && (
                  <Typography.Text
                    type="secondary"
                    style={{
                      fontSize: 11,
                      display: 'block',
                      marginTop: 3,
                      lineHeight: '1.5',
                    }}
                  >
                    {step.output.substring(0, 100)}
                    {step.output.length > 100 ? '...' : ''}
                  </Typography.Text>
                )}
              </div>
            </div>
          )
        })}
      </div>

      <Divider style={{ margin: '12px 0' }} />

      {/* Performance Metrics */}
      <Typography.Text
        type="secondary"
        style={{
          fontSize: 10,
          letterSpacing: '0.08em',
          display: 'block',
          marginBottom: 10,
          textTransform: 'uppercase',
          fontWeight: 600,
        }}
      >
        推理性能指标
      </Typography.Text>

      <div
        style={{
          display: 'flex',
          gap: 16,
          marginBottom: 14,
          padding: '10px 12px',
          background: '#f8f9fc',
          borderRadius: 8,
          border: '1px solid #eaecf0',
        }}
      >
        <div>
          <Typography.Text
            type="secondary"
            style={{ fontSize: 10, display: 'block', marginBottom: 2 }}
          >
            总延迟
          </Typography.Text>
          <Typography.Text
            strong
            style={{ fontSize: 20, color: '#1677ff' }}
          >
            {totalLatency ? `${totalLatency.toFixed(2)}s` : '--'}
          </Typography.Text>
        </div>
        <div style={{ width: 1, background: '#eaecf0' }} />
        <div>
          <Typography.Text
            type="secondary"
            style={{ fontSize: 10, display: 'block', marginBottom: 2 }}
          >
            Token 消耗
          </Typography.Text>
          <Typography.Text
            strong
            style={{ fontSize: 20, color: '#722ed1' }}
          >
            {tokenCount ? tokenCount.toLocaleString() : '--'}
          </Typography.Text>
        </div>
      </div>

      {/* System Status */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '8px 12px',
          background: '#f6ffed',
          border: '1px solid #b7eb8f',
          borderRadius: 6,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <CheckCircleFilled style={{ color: '#52c41a', fontSize: 12 }} />
          <Typography.Text style={{ fontSize: 11, color: '#52c41a' }}>
            系统运行正常
          </Typography.Text>
        </div>
        <Tag color="blue" style={{ fontSize: 10, margin: 0 }}>
          v1.0.0
        </Tag>
      </div>
    </div>
  )
}
