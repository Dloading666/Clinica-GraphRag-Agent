import { useCallback, useEffect, useRef, useState } from 'react'
import { Button, Spin, Tag, Typography } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { api } from '../../api'
import { useChatStore } from '../../stores/chatStore'
import type {
  KGData,
  KGLink,
  KGNode,
  KnowledgeBaseStatus,
} from '../../types'

const TYPE_COLORS: Record<string, string> = {
  疾病: '#ff4d4f',
  药物: '#1677ff',
  症状: '#fa8c16',
  治疗方法: '#52c41a',
  中药方剂: '#722ed1',
  检查项目: '#13c2c2',
  体征: '#eb2f96',
  病因: '#f5222d',
}

function getTypeColor(type: string): string {
  return TYPE_COLORS[type] || '#8c8c8c'
}

function formatKbStatus(status: KnowledgeBaseStatus | null): string | null {
  if (!status) return null

  if (status.status === 'running') {
    if (status.stage === 'ingesting') {
      return `正在导入知识库文档，当前已检测到 ${status.source_files} 个源文件，请稍候。`
    }
    if (status.stage === 'building_graph') {
      return '文档已导入，正在抽取实体关系并构建知识图谱。这个阶段会稍慢一些。'
    }
    return status.message || '知识库任务正在后台执行。'
  }

  if (status.status === 'failed') {
    return status.error
      ? `${status.message || '知识库任务失败。'} ${status.error}`
      : status.message || '知识库任务失败。'
  }

  if (status.counts.entities > 0 || status.counts.relationships > 0) {
    return `已构建 ${status.counts.entities} 个实体、${status.counts.relationships} 条关系。`
  }

  if (status.source_files > 0 && status.counts.documents === 0) {
    return `检测到 ${status.source_files} 个知识库文件尚未导入。点击“重建图谱”会自动先导入知识库，再构建图谱。`
  }

  if (status.source_files === 0) {
    return '当前没有检测到知识库源文件，请先上传或挂载知识库文档。'
  }

  return status.message || '当前知识图谱为空，请先重建图谱或重新导入知识库。'
}

interface NodePosition {
  x: number
  y: number
}

function SimpleGraph({ data }: { data: KGData }) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [hoveredNode, setHoveredNode] = useState<string | null>(null)

  const width = 296
  const height = 260
  const centerX = width / 2
  const centerY = height / 2

  const displayNodes = data.nodes.slice(0, 20)
  const nodePositions: Record<string, NodePosition> = {}

  if (displayNodes.length === 1) {
    nodePositions[displayNodes[0].id] = { x: centerX, y: centerY }
  } else if (displayNodes.length <= 8) {
    const radius = 80
    displayNodes.forEach((node, index) => {
      const angle = (index / displayNodes.length) * 2 * Math.PI - Math.PI / 2
      nodePositions[node.id] = {
        x: centerX + radius * Math.cos(angle),
        y: centerY + radius * Math.sin(angle),
      }
    })
  } else {
    const innerNodes = displayNodes.slice(0, 6)
    const outerNodes = displayNodes.slice(6)

    innerNodes.forEach((node, index) => {
      const angle = (index / innerNodes.length) * 2 * Math.PI - Math.PI / 2
      nodePositions[node.id] = {
        x: centerX + 60 * Math.cos(angle),
        y: centerY + 60 * Math.sin(angle),
      }
    })

    outerNodes.forEach((node, index) => {
      const angle = (index / outerNodes.length) * 2 * Math.PI - Math.PI / 2
      nodePositions[node.id] = {
        x: centerX + 105 * Math.cos(angle),
        y: centerY + 105 * Math.sin(angle),
      }
    })
  }

  const visibleLinks = data.links.filter(
    (link) =>
      nodePositions[link.source] !== undefined &&
      nodePositions[link.target] !== undefined
  )

  const nodeMap = new Map<string, KGNode>(data.nodes.map((node) => [node.id, node]))

  return (
    <svg
      ref={svgRef}
      width={width}
      height={height}
      style={{ width: '100%', height, background: '#fafafa', borderRadius: 8 }}
    >
      <defs>
        <pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse">
          <path d="M 20 0 L 0 0 0 20" fill="none" stroke="#f0f0f0" strokeWidth="0.5" />
        </pattern>
      </defs>
      <rect width={width} height={height} fill="url(#grid)" />

      {visibleLinks.map((link: KGLink, index: number) => {
        const source = nodePositions[link.source]
        const target = nodePositions[link.target]
        if (!source || !target) return null

        const labelX = (source.x + target.x) / 2
        const labelY = (source.y + target.y) / 2
        const isHighlighted =
          hoveredNode === link.source || hoveredNode === link.target

        return (
          <g key={index}>
            <line
              x1={source.x}
              y1={source.y}
              x2={target.x}
              y2={target.y}
              stroke={isHighlighted ? '#1677ff' : '#e0e0e0'}
              strokeWidth={isHighlighted ? 1.5 : 1}
              strokeDasharray={isHighlighted ? 'none' : '3,3'}
              opacity={isHighlighted ? 1 : 0.6}
            />
            {link.label && isHighlighted && (
              <text x={labelX} y={labelY - 3} textAnchor="middle" fontSize={8} fill="#666">
                {link.label.substring(0, 8)}
              </text>
            )}
          </g>
        )
      })}

      {displayNodes.map((node: KGNode) => {
        const position = nodePositions[node.id]
        if (!position) return null

        const color = getTypeColor(node.type)
        const isHovered = hoveredNode === node.id
        const radius = isHovered ? 9 : 7

        return (
          <g
            key={node.id}
            transform={`translate(${position.x},${position.y})`}
            style={{ cursor: 'pointer' }}
            onMouseEnter={() => setHoveredNode(node.id)}
            onMouseLeave={() => setHoveredNode(null)}
          >
            <circle r={radius + 4} fill={color} opacity={0.12} />
            <circle
              r={radius}
              fill={color}
              opacity={isHovered ? 1 : 0.85}
              stroke="#fff"
              strokeWidth={1.5}
            />
            <text
              y={-radius - 5}
              textAnchor="middle"
              fontSize={isHovered ? 10 : 9}
              fill={isHovered ? '#1a1a2e' : '#666'}
              fontWeight={isHovered ? 600 : 400}
            >
              {node.label.substring(0, 5)}
            </text>
          </g>
        )
      })}

      {hoveredNode &&
        (() => {
          const node = nodeMap.get(hoveredNode)
          const position = nodePositions[hoveredNode]
          if (!node || !position) return null

          const color = getTypeColor(node.type)
          const tooltipX = position.x + (position.x > width / 2 ? -60 : 12)
          const tooltipY = position.y + (position.y > height / 2 ? -36 : 12)

          return (
            <g>
              <rect
                x={tooltipX}
                y={tooltipY}
                width={60}
                height={28}
                rx={4}
                fill="#1a1a2e"
                opacity={0.85}
              />
              <text
                x={tooltipX + 30}
                y={tooltipY + 11}
                textAnchor="middle"
                fontSize={8}
                fill={color}
              >
                {node.type}
              </text>
              <text
                x={tooltipX + 30}
                y={tooltipY + 22}
                textAnchor="middle"
                fontSize={9}
                fill="#fff"
              >
                {node.label.substring(0, 8)}
              </text>
            </g>
          )
        })()}
    </svg>
  )
}

export default function KnowledgeGraphPanel() {
  const { currentKgData, currentKgStatus, messages, isStreaming } = useChatStore()
  const [fullKgData, setFullKgData] = useState<KGData | null>(null)
  const [loading, setLoading] = useState(false)
  const [rebuilding, setRebuilding] = useState(false)
  const [statusMessage, setStatusMessage] = useState<string | null>(null)
  const [kbStatus, setKbStatus] = useState<KnowledgeBaseStatus | null>(null)

  const latestAssistantMessage = [...messages]
    .reverse()
    .find((message) => message.role === 'assistant')
  const resolvedKgData =
    currentKgData ?? (!isStreaming ? latestAssistantMessage?.kgData ?? null : null)
  const resolvedKgStatus =
    currentKgStatus !== 'idle'
      ? currentKgStatus
      : !isStreaming
        ? latestAssistantMessage?.kgStatus ?? 'idle'
        : 'idle'

  const hasCurrentGraph =
    !!resolvedKgData &&
    (resolvedKgData.nodes.length > 0 || resolvedKgData.links.length > 0)
  const hasFullGraph =
    !!fullKgData &&
    (fullKgData.nodes.length > 0 || fullKgData.links.length > 0)
  const displayData = hasCurrentGraph ? resolvedKgData : hasFullGraph ? fullKgData : null
  const graphStatusMessage =
    resolvedKgStatus === 'loading' && !hasCurrentGraph
      ? '正在加载当前问题相关子图，请稍候。'
      : resolvedKgStatus === 'error' && !hasCurrentGraph
        ? '当前问题相关子图加载失败，你可以手动加载全图。'
        : statusMessage

  const loadFullGraph = useCallback(
    async (silent = false) => {
      setLoading(true)
      try {
        const res = await api.getKgVisualization()
        setFullKgData(res.data)
        if (res.data.nodes.length > 0 || res.data.links.length > 0) {
          setStatusMessage(
            `知识图谱已加载，当前展示 ${res.data.nodes.length} 个节点、${res.data.links.length} 条关系。`
          )
          return
        }

        if (!silent) {
          setStatusMessage('当前知识图谱为空，正在检查后台导入和建图状态。')
        }
      } catch {
        if (!silent) {
          setStatusMessage('加载知识图谱失败，请稍后重试。')
        }
      } finally {
        setLoading(false)
      }
    },
    []
  )

  const refreshKnowledgeBaseStatus = useCallback(
    async (autoLoadGraph = true) => {
      try {
        const res = await api.getKnowledgeBaseStatus()
        const nextStatus = res.data
        setKbStatus(nextStatus)

        const nextMessage = formatKbStatus(nextStatus)
        if (nextMessage) {
          setStatusMessage(nextMessage)
        }

        const isRunning = nextStatus.status === 'running' || nextStatus.active === true
        setRebuilding(isRunning)

        if (
          autoLoadGraph &&
          !isRunning &&
          nextStatus.counts.entities > 0 &&
          !hasCurrentGraph &&
          !hasFullGraph
        ) {
          void loadFullGraph(true)
        }
      } catch {
        setStatusMessage('获取知识库状态失败，请稍后重试。')
      }
    },
    [hasCurrentGraph, hasFullGraph, loadFullGraph]
  )

  useEffect(() => {
    void loadFullGraph(true)
    void refreshKnowledgeBaseStatus(false)
  }, [loadFullGraph, refreshKnowledgeBaseStatus])

  useEffect(() => {
    if (!kbStatus || kbStatus.status !== 'running') {
      return
    }

    const timer = window.setInterval(() => {
      void refreshKnowledgeBaseStatus(true)
    }, 5000)

    return () => window.clearInterval(timer)
  }, [kbStatus, refreshKnowledgeBaseStatus])

  const rebuildGraph = useCallback(async () => {
    setRebuilding(true)
    setStatusMessage('已提交后台任务，正在准备导入知识库并重建图谱。')
    try {
      const res = await api.rebuildKnowledgeGraph()
      setKbStatus(res.data)
      const nextMessage = formatKbStatus(res.data)
      if (nextMessage) {
        setStatusMessage(nextMessage)
      }
      void refreshKnowledgeBaseStatus(true)
    } catch {
      setRebuilding(false)
      setStatusMessage('提交重建任务失败，请稍后重试。')
    }
  }, [refreshKnowledgeBaseStatus])

  const presentTypes = displayData
    ? [...new Set(displayData.nodes.map((node) => node.type))]
    : []

  return (
    <div style={{ padding: 12, height: '100%', overflowY: 'auto' }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 10,
          gap: 8,
        }}
      >
        <Typography.Text style={{ fontSize: 12, fontWeight: 600 }}>
          知识子图预览
        </Typography.Text>
        <div style={{ display: 'flex', gap: 6 }}>
          <Button
            size="small"
            icon={<ReloadOutlined />}
            onClick={() => void loadFullGraph(false)}
            loading={loading}
          >
            加载全图
          </Button>
          <Button
            size="small"
            type="dashed"
            onClick={() => void rebuildGraph()}
            loading={rebuilding}
          >
            重建图谱
          </Button>
        </div>
      </div>

      {kbStatus && (
        <div style={{ marginBottom: 8, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          <Tag color={kbStatus.status === 'failed' ? 'error' : kbStatus.status === 'running' ? 'processing' : 'default'}>
            {kbStatus.status === 'running'
              ? '构建中'
              : kbStatus.status === 'failed'
                ? '失败'
                : kbStatus.counts.entities > 0
                  ? '已就绪'
                  : '空库'}
          </Tag>
          <Tag>文档 {kbStatus.counts.documents}</Tag>
          <Tag>文本块 {kbStatus.counts.chunks}</Tag>
          <Tag>实体 {kbStatus.counts.entities}</Tag>
          <Tag>关系 {kbStatus.counts.relationships}</Tag>
        </div>
      )}

      {graphStatusMessage && (
        <div style={{ marginBottom: 10 }}>
          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
            {graphStatusMessage}
          </Typography.Text>
        </div>
      )}

      {loading || rebuilding || (currentKgStatus === 'loading' && !hasCurrentGraph) ? (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 10,
            paddingTop: 52,
          }}
        >
          <Spin />
          <Typography.Text type="secondary" style={{ fontSize: 12, textAlign: 'center' }}>
            {graphStatusMessage || '正在处理中，请稍候。'}
          </Typography.Text>
        </div>
      ) : displayData && displayData.nodes.length > 0 ? (
        <>
          <SimpleGraph data={displayData} />

          {presentTypes.length > 0 && (
            <div style={{ marginTop: 10, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {presentTypes.slice(0, 6).map((type) => (
                <Tag
                  key={type}
                  style={{
                    fontSize: 10,
                    padding: '0 6px',
                    lineHeight: '18px',
                    borderColor: getTypeColor(type),
                    color: getTypeColor(type),
                    background: `${getTypeColor(type)}15`,
                    margin: 0,
                  }}
                >
                  {type}
                </Tag>
              ))}
            </div>
          )}

          <div
            style={{
              marginTop: 8,
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}
          >
            <Typography.Text type="secondary" style={{ fontSize: 10 }}>
              显示 {Math.min(displayData.nodes.length, 20)} / {displayData.nodes.length} 个节点
            </Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 10 }}>
              {displayData.links.length} 条关系
            </Typography.Text>
          </div>
        </>
      ) : (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            paddingTop: 40,
            gap: 10,
          }}
        >
          <span style={{ fontSize: 28, color: '#8c8c8c' }}>图</span>
          <Typography.Text type="secondary" style={{ fontSize: 12, textAlign: 'center' }}>
            {graphStatusMessage || '发送消息后会自动加载相关子图，也可以手动加载全图。'}
          </Typography.Text>
          <div style={{ display: 'flex', gap: 8 }}>
            <Button
              size="small"
              type="dashed"
              icon={<ReloadOutlined />}
              onClick={() => void loadFullGraph(false)}
              loading={loading}
            >
              手动加载知识图谱
            </Button>
            <Button size="small" onClick={() => void rebuildGraph()} loading={rebuilding}>
              重建图谱
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
