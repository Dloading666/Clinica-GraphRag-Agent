import { Typography, Slider, Space, Tag } from 'antd'
import {
  ThunderboltOutlined,
  ShareAltOutlined,
  MergeCellsOutlined,
  FunnelPlotOutlined,
  ExperimentOutlined,
  CaretRightOutlined,
} from '@ant-design/icons'
import { useConfigStore } from '../../stores/configStore'
import { useChatStore } from '../../stores/chatStore'
import { KNOWLEDGE_EXAMPLE_QUESTIONS } from '../../constants/exampleQuestions'

const STRATEGIES = [
  {
    id: 'naive_rag',
    name: 'NAIVE RAG',
    icon: <ThunderboltOutlined />,
    color: '#1677ff',
  },
  {
    id: 'graph_rag',
    name: 'GRAPH RAG',
    icon: <ShareAltOutlined />,
    color: '#722ed1',
  },
  {
    id: 'hybrid_rag',
    name: 'HYBRID RAG',
    icon: <MergeCellsOutlined />,
    color: '#13c2c2',
  },
  {
    id: 'fusion_rag',
    name: 'FUSION RAG',
    icon: <FunnelPlotOutlined />,
    color: '#fa8c16',
  },
  {
    id: 'deep_research',
    name: 'DEEP RESEARCH',
    icon: <ExperimentOutlined />,
    color: '#52c41a',
  },
]

const sectionLabelStyle = {
  fontSize: 11,
  marginBottom: 10,
  display: 'block',
  letterSpacing: '0.12em',
  textTransform: 'uppercase' as const,
  fontWeight: 600,
  color: '#74839a',
}

export default function Sidebar() {
  const {
    config,
    selectedStrategy,
    topK,
    similarityThreshold,
    setStrategy,
    setTopK,
    setThreshold,
  } = useConfigStore()
  const setDraftMessage = useChatStore((s) => s.setDraftMessage)

  const exampleQuestions = KNOWLEDGE_EXAMPLE_QUESTIONS.map((item, index) => ({
    ...item,
    text: config?.example_questions?.[index] ?? item.text,
  }))

  return (
    <div
      className="sidebar-scroll-area"
      style={{
        padding: '18px 16px 20px',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        background:
          'linear-gradient(180deg, rgba(248,250,253,0.98) 0%, rgba(242,246,251,0.98) 100%)',
      }}
    >
      <div
        style={{
          marginBottom: 22,
          paddingBottom: 16,
          borderBottom: '1px solid #e4ebf4',
        }}
      >
        <Typography.Text
          strong
          style={{ fontSize: 14, display: 'block', color: '#18253b' }}
        >
          配置中心
        </Typography.Text>
      </div>

      <div style={{ marginBottom: 22 }}>
        <Typography.Text type="secondary" style={sectionLabelStyle}>
          检索策略选择
        </Typography.Text>
        <Space direction="vertical" size={6} style={{ width: '100%' }}>
          {STRATEGIES.map((strategy) => {
            const isSelected = selectedStrategy === strategy.id

            return (
              <button
                key={strategy.id}
                type="button"
                onClick={() => setStrategy(strategy.id)}
                className={`sidebar-strategy-item${isSelected ? ' is-selected' : ''}`}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  padding: '10px 12px',
                  width: '100%',
                  borderRadius: 12,
                  border: `1px solid ${
                    isSelected ? 'rgba(22,119,255,0.34)' : 'rgba(223,230,240,0.94)'
                  }`,
                  background: isSelected
                    ? 'linear-gradient(135deg, rgba(231,243,255,0.98) 0%, rgba(241,247,255,0.9) 100%)'
                    : 'rgba(255,255,255,0.74)',
                  cursor: 'pointer',
                  transition:
                    'transform 0.2s ease, border-color 0.2s ease, background 0.2s ease, box-shadow 0.2s ease',
                  boxShadow: isSelected
                    ? '0 10px 26px rgba(22,119,255,0.08)'
                    : 'none',
                }}
              >
                <span
                  style={{
                    color: isSelected ? strategy.color : '#a8b3c3',
                    fontSize: 15,
                    display: 'flex',
                    alignItems: 'center',
                  }}
                >
                  {strategy.icon}
                </span>
                <Typography.Text
                  style={{
                    fontSize: 12,
                    fontWeight: isSelected ? 700 : 500,
                    color: isSelected ? '#1465d8' : '#445164',
                    letterSpacing: '0.02em',
                  }}
                >
                  {strategy.name}
                </Typography.Text>
              </button>
            )
          })}
        </Space>
      </div>

      <div
        style={{
          marginBottom: 22,
          paddingBottom: 18,
          borderBottom: '1px solid #e4ebf4',
        }}
      >
        <Typography.Text type="secondary" style={sectionLabelStyle}>
          搜索参数调节
        </Typography.Text>

        <div style={{ marginBottom: 18 }}>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: 6,
            }}
          >
            <Typography.Text style={{ fontSize: 11, color: '#708094' }}>
              TOP K RETRIEVAL
            </Typography.Text>
            <Tag
              bordered={false}
              style={{
                fontSize: 11,
                lineHeight: '20px',
                color: '#1465d8',
                background: 'rgba(22,119,255,0.1)',
                borderRadius: 999,
                marginInlineEnd: 0,
              }}
            >
              {topK}
            </Tag>
          </div>
          <Slider
            min={3}
            max={50}
            value={topK}
            onChange={setTopK}
            tooltip={{ formatter: (value) => `${value ?? topK} 条` }}
          />
        </div>

        <div>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: 6,
            }}
          >
            <Typography.Text style={{ fontSize: 11, color: '#708094' }}>
              SIMILARITY THRESHOLD
            </Typography.Text>
            <Tag
              bordered={false}
              style={{
                fontSize: 11,
                lineHeight: '20px',
                color: '#1465d8',
                background: 'rgba(22,119,255,0.1)',
                borderRadius: 999,
                marginInlineEnd: 0,
              }}
            >
              {similarityThreshold.toFixed(2)}
            </Tag>
          </div>
          <Slider
            min={0}
            max={1}
            step={0.01}
            value={similarityThreshold}
            onChange={setThreshold}
            tooltip={{ formatter: (value) => `${((value ?? 0) * 100).toFixed(0)}%` }}
          />
        </div>
      </div>

      <div style={{ marginBottom: 22 }}>
        <Typography.Text type="secondary" style={sectionLabelStyle}>
          示例问题
        </Typography.Text>
        <Space direction="vertical" size={10} style={{ width: '100%' }}>
          {exampleQuestions.map((item) => (
            <button
              key={item.text}
              type="button"
              className="sidebar-example-item"
              onClick={() => setDraftMessage(item.text)}
              style={{
                width: '100%',
                textAlign: 'left',
                padding: '12px 14px',
                borderRadius: 14,
                border: '1px solid rgba(219,228,238,0.96)',
                background:
                  'linear-gradient(180deg, rgba(255,255,255,0.96) 0%, rgba(247,250,253,0.92) 100%)',
                cursor: 'pointer',
                transition:
                  'transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease, background 0.2s ease',
                boxShadow: '0 10px 24px rgba(25,39,63,0.04)',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  justifyContent: 'space-between',
                  gap: 10,
                }}
              >
                <div style={{ minWidth: 0 }}>
                  <Typography.Text
                    style={{
                      display: 'block',
                      marginBottom: 6,
                      fontSize: 10,
                      letterSpacing: '0.12em',
                      textTransform: 'uppercase',
                      color: '#7d8da4',
                    }}
                  >
                    {item.source}
                  </Typography.Text>
                  <Typography.Text
                    style={{
                      display: 'block',
                      color: '#243246',
                      fontSize: 12,
                      lineHeight: 1.7,
                    }}
                  >
                    {item.text}
                  </Typography.Text>
                </div>
                <CaretRightOutlined
                  style={{
                    color: '#8ca3bf',
                    fontSize: 12,
                    marginTop: 4,
                    flexShrink: 0,
                  }}
                />
              </div>
            </button>
          ))}
        </Space>
      </div>
    </div>
  )
}
