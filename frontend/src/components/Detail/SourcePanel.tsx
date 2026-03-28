import { Typography, Empty, Collapse, Tag } from 'antd'
import { FileTextOutlined } from '@ant-design/icons'
import { useChatStore } from '../../stores/chatStore'

export default function SourcePanel() {
  const { messages } = useChatStore()
  const lastAssistant = [...messages]
    .reverse()
    .find((m) => m.role === 'assistant' && m.traceSteps && m.traceSteps.length > 0)

  const stepsWithOutput = lastAssistant?.traceSteps?.filter(
    (s) => s.output && s.output.trim().length > 0
  )

  return (
    <div style={{ padding: 12, height: '100%', overflowY: 'auto' }}>
      <Typography.Text
        type="secondary"
        style={{
          fontSize: 10,
          letterSpacing: '0.1em',
          display: 'block',
          marginBottom: 12,
          textTransform: 'uppercase',
          fontWeight: 600,
        }}
      >
        源文档引用
      </Typography.Text>

      {stepsWithOutput && stepsWithOutput.length > 0 ? (
        <Collapse
          size="small"
          style={{ background: 'transparent' }}
          items={stepsWithOutput.map((step, i) => ({
            key: i,
            label: (
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <FileTextOutlined style={{ color: '#1677ff', fontSize: 12 }} />
                <Tag
                  color="blue"
                  style={{ fontSize: 10, margin: 0, lineHeight: '18px' }}
                >
                  {step.node}
                </Tag>
                {step.latency !== undefined && (
                  <Tag
                    style={{ fontSize: 10, margin: 0, lineHeight: '18px' }}
                  >
                    {step.latency.toFixed(2)}s
                  </Tag>
                )}
              </div>
            ),
            children: (
              <div
                style={{
                  padding: '8px 12px',
                  background: '#f8f9fc',
                  borderRadius: 6,
                  border: '1px solid #eaecf0',
                }}
              >
                <Typography.Text
                  style={{
                    fontSize: 11,
                    color: '#555',
                    lineHeight: '1.7',
                    display: 'block',
                    whiteSpace: 'pre-wrap',
                  }}
                >
                  {step.output}
                </Typography.Text>
              </div>
            ),
          }))}
        />
      ) : (
        <Empty
          description={
            <span style={{ fontSize: 12, color: '#bbb' }}>暂无源内容</span>
          }
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          style={{ marginTop: 60 }}
        />
      )}
    </div>
  )
}
