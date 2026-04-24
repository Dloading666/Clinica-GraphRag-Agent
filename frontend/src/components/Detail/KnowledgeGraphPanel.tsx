import { useCallback, useEffect, useRef, useState } from 'react'
import { Button, Spin, Tag, Typography } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { api } from '../../api'
import { buildKgFromSourceItems } from '../../lib/sourceGraph'
import { useChatStore } from '../../stores/chatStore'
import type {
  KGData,
  KGLink,
  KGNode,
  KnowledgeBaseStatus,
} from '../../types'

const CANVAS_WIDTH = 360
const CANVAS_HEIGHT = 440
const MAX_VISIBLE_NODES = 24

const TYPE_COLORS: Record<string, string> = {
  疾病: '#ff4d4f',
  药物: '#1677ff',
  症状: '#fa8c16',
  治疗方法: '#52c41a',
  中药方剂: '#722ed1',
  检查项目: '#13c2c2',
  体征: '#eb2f96',
  病因: '#f5222d',
  相关实体: '#7a7f8a',
  实体关系: '#4f46e5',
  社区摘要: '#14b8a6',
  文献片段: '#f59e0b',
  文档: '#64748b',
}

type NodePosition = { x: number; y: number }

function getTypeColor(type: string): string {
  return TYPE_COLORS[type] || '#8c8c8c'
}

function formatKbStatus(status: KnowledgeBaseStatus | null): string | null {
  if (!status) return null

  if (status.status === 'running') {
    if (status.stage === 'ingesting') {
      return `正在导入知识库文档，当前检测到 ${status.source_files} 个源文件，请稍候。`
    }
    if (status.stage === 'building_graph') {
      return '文档已导入，正在抽取实体关系并构建知识图谱。'
    }
    return status.message || '知识库任务正在后台执行。'
  }

  if (status.status === 'failed') {
    return status.error
      ? `${status.message || '知识库任务失败。'} ${status.error}`
      : status.message || '知识库任务失败。'
  }

  if (status.counts.entities > 0 || status.counts.relationships > 0) {
    return `知识库已就绪，当前包含 ${status.counts.entities} 个实体、${status.counts.relationships} 条关系。`
  }

  if (status.source_files > 0 && status.counts.documents === 0) {
    return `检测到 ${status.source_files} 个知识库文件，尚未导入。点击“重建图谱”会自动导入并构建图谱。`
  }

  if (status.source_files === 0) {
    return '当前没有检测到知识库源文件，请先上传或挂载知识库文档。'
  }

  return status.message || '当前知识图谱为空，请先重建图谱。'
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

function getVisibleGraph(data: KGData) {
  const visibleNodes = data.nodes.slice(0, MAX_VISIBLE_NODES)
  const visibleIds = new Set(visibleNodes.map((node) => node.id))
  const visibleLinks = data.links.filter(
    (link) => visibleIds.has(link.source) && visibleIds.has(link.target)
  )
  return { visibleNodes, visibleLinks }
}

function buildForceLayout(data: KGData): Record<string, NodePosition> {
  const { visibleNodes, visibleLinks } = getVisibleGraph(data)
  const centerX = CANVAS_WIDTH / 2
  const centerY = CANVAS_HEIGHT / 2
  const margin = 48
  const degrees = new Map<string, number>()
  const positions = new Map<string, NodePosition>()
  const velocities = new Map<string, NodePosition>()

  for (const node of visibleNodes) {
    degrees.set(node.id, 0)
  }

  for (const link of visibleLinks) {
    degrees.set(link.source, (degrees.get(link.source) ?? 0) + 1)
    degrees.set(link.target, (degrees.get(link.target) ?? 0) + 1)
  }

  const seededNodes = [...visibleNodes].sort(
    (a, b) => (degrees.get(b.id) ?? 0) - (degrees.get(a.id) ?? 0)
  )

  seededNodes.forEach((node, index) => {
    const angle = index * 2.399963229728653
    const radius = 28 + Math.sqrt(index + 1) * 34
    positions.set(node.id, {
      x: centerX + Math.cos(angle) * radius,
      y: centerY + Math.sin(angle) * radius,
    })
    velocities.set(node.id, { x: 0, y: 0 })
  })

  const repulsionStrength = 28000
  const springStrength = 0.015
  const centerStrength = 0.0035
  const damping = 0.85
  const idealLength = visibleNodes.length > 16 ? 86 : 96
  const collisionRadius = 30
  const iterations = 220

  for (let iteration = 0; iteration < iterations; iteration += 1) {
    const forces = new Map<string, NodePosition>()

    for (const node of visibleNodes) {
      forces.set(node.id, { x: 0, y: 0 })
    }

    for (let i = 0; i < seededNodes.length; i += 1) {
      const a = seededNodes[i]
      const aPos = positions.get(a.id)
      if (!aPos) continue

      for (let j = i + 1; j < seededNodes.length; j += 1) {
        const b = seededNodes[j]
        const bPos = positions.get(b.id)
        if (!bPos) continue

        let dx = aPos.x - bPos.x
        let dy = aPos.y - bPos.y
        let distance = Math.sqrt(dx * dx + dy * dy)
        if (distance < 1) {
          dx = 0.5 - ((i + j) % 2)
          dy = 0.5 - ((i * j + 1) % 2)
          distance = 1
        }

        const repel = repulsionStrength / (distance * distance)
        const overlap = Math.max(0, collisionRadius - distance)
        const collisionBoost = overlap * 0.22
        const fx = (dx / distance) * (repel + collisionBoost)
        const fy = (dy / distance) * (repel + collisionBoost)

        const aForce = forces.get(a.id)
        const bForce = forces.get(b.id)
        if (aForce && bForce) {
          aForce.x += fx
          aForce.y += fy
          bForce.x -= fx
          bForce.y -= fy
        }
      }
    }

    for (const link of visibleLinks) {
      const sourcePos = positions.get(link.source)
      const targetPos = positions.get(link.target)
      if (!sourcePos || !targetPos) continue

      let dx = targetPos.x - sourcePos.x
      let dy = targetPos.y - sourcePos.y
      let distance = Math.sqrt(dx * dx + dy * dy)
      if (distance < 1) distance = 1

      const weight = link.weight ?? 0.5
      const spring = (distance - idealLength) * (springStrength + weight * 0.006)
      const fx = (dx / distance) * spring
      const fy = (dy / distance) * spring

      const sourceForce = forces.get(link.source)
      const targetForce = forces.get(link.target)
      if (sourceForce && targetForce) {
        sourceForce.x += fx
        sourceForce.y += fy
        targetForce.x -= fx
        targetForce.y -= fy
      }
    }

    for (const node of visibleNodes) {
      const pos = positions.get(node.id)
      const velocity = velocities.get(node.id)
      const force = forces.get(node.id)
      if (!pos || !velocity || !force) continue

      const degree = degrees.get(node.id) ?? 0
      const gravity = centerStrength * Math.max(0.45, 1.2 - degree * 0.08)
      force.x += (centerX - pos.x) * gravity
      force.y += (centerY - pos.y) * gravity

      velocity.x = (velocity.x + force.x) * damping
      velocity.y = (velocity.y + force.y) * damping

      pos.x += velocity.x
      pos.y += velocity.y
    }
  }

  const posValues = [...positions.values()]
  if (posValues.length === 0) return {}

  let minX = Infinity
  let maxX = -Infinity
  let minY = Infinity
  let maxY = -Infinity
  for (const pos of posValues) {
    minX = Math.min(minX, pos.x)
    maxX = Math.max(maxX, pos.x)
    minY = Math.min(minY, pos.y)
    maxY = Math.max(maxY, pos.y)
  }

  const spanX = Math.max(1, maxX - minX)
  const spanY = Math.max(1, maxY - minY)
  const scale = Math.min(
    (CANVAS_WIDTH - margin * 2) / spanX,
    (CANVAS_HEIGHT - margin * 2) / spanY
  )

  const normalized: Record<string, NodePosition> = {}
  for (const node of visibleNodes) {
    const pos = positions.get(node.id)
    if (!pos) continue
    normalized[node.id] = {
      x: margin + (pos.x - minX) * scale,
      y: margin + (pos.y - minY) * scale,
    }
  }

  return normalized
}

function relaxLayout(
  visibleNodes: KGNode[],
  visibleLinks: KGLink[],
  basePositions: Record<string, NodePosition>,
  fixedNodeId: string
): Record<string, NodePosition> {
  const nextPositions: Record<string, NodePosition> = {}
  const velocities = new Map<string, NodePosition>()
  const padding = 26
  const repulsionStrength = 15000
  const springStrength = 0.02
  const centerStrength = 0.0016
  const collisionRadius = 28
  const damping = 0.82
  const idealLength = visibleNodes.length > 16 ? 84 : 96
  const iterations = 18

  for (const node of visibleNodes) {
    const current = basePositions[node.id]
    if (!current) continue
    nextPositions[node.id] = { x: current.x, y: current.y }
    velocities.set(node.id, { x: 0, y: 0 })
  }

  for (let iteration = 0; iteration < iterations; iteration += 1) {
    const forces = new Map<string, NodePosition>()
    for (const node of visibleNodes) {
      forces.set(node.id, { x: 0, y: 0 })
    }

    for (let i = 0; i < visibleNodes.length; i += 1) {
      const sourceNode = visibleNodes[i]
      const sourcePos = nextPositions[sourceNode.id]
      if (!sourcePos) continue

      for (let j = i + 1; j < visibleNodes.length; j += 1) {
        const targetNode = visibleNodes[j]
        const targetPos = nextPositions[targetNode.id]
        if (!targetPos) continue

        let dx = sourcePos.x - targetPos.x
        let dy = sourcePos.y - targetPos.y
        let distance = Math.sqrt(dx * dx + dy * dy)
        if (distance < 1) {
          dx = 0.5
          dy = 0.5
          distance = 1
        }

        const repulsion = repulsionStrength / (distance * distance)
        const overlap = Math.max(0, collisionRadius - distance)
        const separation = overlap * 0.28
        const fx = (dx / distance) * (repulsion + separation)
        const fy = (dy / distance) * (repulsion + separation)

        const sourceForce = forces.get(sourceNode.id)
        const targetForce = forces.get(targetNode.id)
        if (sourceForce && targetForce) {
          sourceForce.x += fx
          sourceForce.y += fy
          targetForce.x -= fx
          targetForce.y -= fy
        }
      }
    }

    for (const link of visibleLinks) {
      const sourcePos = nextPositions[link.source]
      const targetPos = nextPositions[link.target]
      if (!sourcePos || !targetPos) continue

      let dx = targetPos.x - sourcePos.x
      let dy = targetPos.y - sourcePos.y
      let distance = Math.sqrt(dx * dx + dy * dy)
      if (distance < 1) {
        distance = 1
      }

      const spring =
        (distance - idealLength) * (springStrength + (link.weight ?? 0.4) * 0.004)
      const fx = (dx / distance) * spring
      const fy = (dy / distance) * spring

      const sourceForce = forces.get(link.source)
      const targetForce = forces.get(link.target)
      if (sourceForce && targetForce) {
        sourceForce.x += fx
        sourceForce.y += fy
        targetForce.x -= fx
        targetForce.y -= fy
      }
    }

    for (const node of visibleNodes) {
      const position = nextPositions[node.id]
      const velocity = velocities.get(node.id)
      const force = forces.get(node.id)
      if (!position || !velocity || !force) continue

      if (node.id === fixedNodeId) {
        velocity.x = 0
        velocity.y = 0
        position.x = clamp(position.x, padding, CANVAS_WIDTH - padding)
        position.y = clamp(position.y, padding, CANVAS_HEIGHT - padding)
        continue
      }

      force.x += (CANVAS_WIDTH / 2 - position.x) * centerStrength
      force.y += (CANVAS_HEIGHT / 2 - position.y) * centerStrength

      velocity.x = (velocity.x + force.x) * damping
      velocity.y = (velocity.y + force.y) * damping

      position.x = clamp(position.x + velocity.x, padding, CANVAS_WIDTH - padding)
      position.y = clamp(position.y + velocity.y, padding, CANVAS_HEIGHT - padding)
    }
  }

  return nextPositions
}

function CanvasGraph({ data }: { data: KGData }) {
  const { visibleNodes, visibleLinks } = getVisibleGraph(data)
  const [positions, setPositions] = useState<Record<string, NodePosition>>(() =>
    buildForceLayout(data)
  )
  const [viewport, setViewport] = useState({ x: 0, y: 0, scale: 1 })
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null)
  const dragStateRef = useRef<
    | {
        mode: 'pan'
        pointerId: number
        startX: number
        startY: number
        originX: number
        originY: number
      }
    | {
        mode: 'node'
        pointerId: number
        nodeId: string
        startX: number
        startY: number
        originX: number
        originY: number
      }
    | null
  >(null)

  useEffect(() => {
    setPositions(buildForceLayout(data))
    setViewport({ x: 0, y: 0, scale: 1 })
    setHoveredNodeId(null)
  }, [data])

  const handleBackgroundPointerDown = useCallback(
    (event: React.PointerEvent<SVGSVGElement>) => {
      dragStateRef.current = {
        mode: 'pan',
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        originX: viewport.x,
        originY: viewport.y,
      }
      event.currentTarget.setPointerCapture(event.pointerId)
    },
    [viewport.x, viewport.y]
  )

  const handleNodePointerDown = useCallback(
    (event: React.PointerEvent<SVGGElement>, nodeId: string) => {
      event.stopPropagation()
      const current = positions[nodeId]
      if (!current) return

      dragStateRef.current = {
        mode: 'node',
        pointerId: event.pointerId,
        nodeId,
        startX: event.clientX,
        startY: event.clientY,
        originX: current.x,
        originY: current.y,
      }
      event.currentTarget.setPointerCapture(event.pointerId)
    },
    [positions]
  )

  const handlePointerMove = useCallback(
    (event: React.PointerEvent<SVGSVGElement>) => {
      const dragState = dragStateRef.current
      if (!dragState || dragState.pointerId !== event.pointerId) return

      if (dragState.mode === 'pan') {
        setViewport((current) => ({
          ...current,
          x: dragState.originX + (event.clientX - dragState.startX),
          y: dragState.originY + (event.clientY - dragState.startY),
        }))
        return
      }

      const deltaX = (event.clientX - dragState.startX) / viewport.scale
      const deltaY = (event.clientY - dragState.startY) / viewport.scale
      setPositions((current) => {
        const next = {
          ...current,
          [dragState.nodeId]: {
            x: dragState.originX + deltaX,
            y: dragState.originY + deltaY,
          },
        }
        return relaxLayout(visibleNodes, visibleLinks, next, dragState.nodeId)
      })
    },
    [viewport.scale, visibleLinks, visibleNodes]
  )

  const clearPointerState = useCallback((event: React.PointerEvent<SVGSVGElement>) => {
    if (dragStateRef.current?.pointerId === event.pointerId) {
      dragStateRef.current = null
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
  }, [])

  const handleWheel = useCallback((event: React.WheelEvent<SVGSVGElement>) => {
    event.preventDefault()
    const delta = event.deltaY < 0 ? 0.12 : -0.12
    setViewport((current) => ({
      ...current,
      scale: clamp(Number((current.scale + delta).toFixed(2)), 0.55, 2.2),
    }))
  }, [])

  const degrees = new Map<string, number>()
  for (const node of visibleNodes) {
    degrees.set(node.id, 0)
  }
  for (const link of visibleLinks) {
    degrees.set(link.source, (degrees.get(link.source) ?? 0) + 1)
    degrees.set(link.target, (degrees.get(link.target) ?? 0) + 1)
  }

  const nodeMap = new Map(visibleNodes.map((node) => [node.id, node]))

  return (
    <div
      style={{
        border: '1px solid #eef2f7',
        borderRadius: 12,
        background:
          'radial-gradient(circle at top, rgba(64, 144, 255, 0.08), transparent 45%), #fbfdff',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '8px 10px',
          borderBottom: '1px solid #eef2f7',
          fontSize: 11,
        }}
      >
        <Typography.Text type="secondary">
          拖动画布或节点，滚轮缩放
        </Typography.Text>
        <Button size="small" onClick={() => setViewport({ x: 0, y: 0, scale: 1 })}>
          重置视图
        </Button>
      </div>

      <svg
        width="100%"
        height={CANVAS_HEIGHT}
        viewBox={`0 0 ${CANVAS_WIDTH} ${CANVAS_HEIGHT}`}
        onPointerDown={handleBackgroundPointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={clearPointerState}
        onPointerCancel={clearPointerState}
        onWheel={handleWheel}
        style={{ display: 'block', touchAction: 'none', cursor: 'grab' }}
      >
        <defs>
          <pattern id="kg-grid" width="24" height="24" patternUnits="userSpaceOnUse">
            <path
              d="M 24 0 L 0 0 0 24"
              fill="none"
              stroke="#edf2f7"
              strokeWidth="0.8"
            />
          </pattern>
        </defs>
        <rect width={CANVAS_WIDTH} height={CANVAS_HEIGHT} fill="url(#kg-grid)" />

        <g transform={`translate(${viewport.x} ${viewport.y}) scale(${viewport.scale})`}>
          {visibleLinks.map((link, index) => {
            const source = positions[link.source]
            const target = positions[link.target]
            if (!source || !target) return null
            const highlighted =
              hoveredNodeId === null ||
              hoveredNodeId === link.source ||
              hoveredNodeId === link.target

            return (
              <g key={`${link.source}-${link.target}-${index}`}>
                <line
                  x1={source.x}
                  y1={source.y}
                  x2={target.x}
                  y2={target.y}
                  stroke={highlighted ? '#94a3b8' : '#dbe2ea'}
                  strokeWidth={highlighted ? 1.5 : 1}
                  strokeOpacity={highlighted ? 0.85 : 0.45}
                />
                {link.label && highlighted && (
                  <text
                    x={(source.x + target.x) / 2}
                    y={(source.y + target.y) / 2 - 4}
                    textAnchor="middle"
                    fontSize={8}
                    fill="#64748b"
                  >
                    {link.label.slice(0, 8)}
                  </text>
                )}
              </g>
            )
          })}

          {visibleNodes.map((node) => {
            const position = positions[node.id]
            if (!position) return null

            const color = getTypeColor(node.type)
            const hovered = hoveredNodeId === node.id
            const degree = degrees.get(node.id) ?? 0
            const radius = hovered ? 10 : 8
            const dx = position.x - CANVAS_WIDTH / 2
            const dy = position.y - CANVAS_HEIGHT / 2
            const labelAnchor =
              Math.abs(dx) < 14 ? 'middle' : dx > 0 ? 'start' : 'end'
            const labelX = Math.abs(dx) < 14 ? 0 : dx > 0 ? radius + 9 : -(radius + 9)
            const labelY =
              Math.abs(dx) < 14 ? (dy > 0 ? radius + 16 : -(radius + 10)) : 4
            const showLabel = true

            return (
              <g
                key={node.id}
                transform={`translate(${position.x}, ${position.y})`}
                onPointerDown={(event) => handleNodePointerDown(event, node.id)}
                onMouseEnter={() => setHoveredNodeId(node.id)}
                onMouseLeave={() => setHoveredNodeId(null)}
                style={{ cursor: 'grab' }}
              >
                <circle r={radius + 7} fill={color} opacity={0.12} />
                <circle r={radius} fill={color} stroke="#fff" strokeWidth={2} />
                {showLabel && (
                  <text
                    x={labelX}
                    y={labelY}
                    textAnchor={labelAnchor}
                    fontSize={hovered ? 10 : 8.3}
                    fill="#334155"
                    fontWeight={hovered ? 700 : degree >= 3 ? 650 : 560}
                    stroke="rgba(255,255,255,0.95)"
                    strokeWidth={3}
                    paintOrder="stroke"
                  >
                    {node.label}
                  </text>
                )}
              </g>
            )
          })}
        </g>
      </svg>

      {hoveredNodeId && nodeMap.get(hoveredNodeId) && (
        <div
          style={{
            padding: '8px 10px',
            borderTop: '1px solid #eef2f7',
            background: '#fff',
          }}
        >
          <Typography.Text style={{ fontSize: 12, fontWeight: 600 }}>
            {nodeMap.get(hoveredNodeId)?.label}
          </Typography.Text>
          <div style={{ marginTop: 4 }}>
            <Tag
              style={{
                margin: 0,
                borderColor: getTypeColor(nodeMap.get(hoveredNodeId)?.type || ''),
                color: getTypeColor(nodeMap.get(hoveredNodeId)?.type || ''),
                background: `${getTypeColor(nodeMap.get(hoveredNodeId)?.type || '')}15`,
              }}
            >
              {nodeMap.get(hoveredNodeId)?.type}
            </Tag>
          </div>
          {!!nodeMap.get(hoveredNodeId)?.properties?.description && (
            <Typography.Paragraph
              style={{ marginTop: 8, marginBottom: 0, fontSize: 12 }}
              ellipsis={{ rows: 3, expandable: false }}
            >
              {String(nodeMap.get(hoveredNodeId)?.properties?.description || '')}
            </Typography.Paragraph>
          )}
        </div>
      )}
    </div>
  )
}

export default function KnowledgeGraphPanel() {
  const { currentKgData, currentKgStatus, messages, isStreaming } = useChatStore()
  const [fullKgData, setFullKgData] = useState<KGData | null>(null)
  const [showFullGraph, setShowFullGraph] = useState(false)
  const [loading, setLoading] = useState(false)
  const [rebuilding, setRebuilding] = useState(false)
  const [statusMessage, setStatusMessage] = useState<string | null>(null)
  const [kbStatus, setKbStatus] = useState<KnowledgeBaseStatus | null>(null)

  const latestAssistantMessage = [...messages]
    .reverse()
    .find((message) => message.role === 'assistant')

  const evidenceGraph = buildKgFromSourceItems(latestAssistantMessage?.sourceItems)
  const resolvedKgData =
    currentKgData && (currentKgData.nodes.length > 0 || currentKgData.links.length > 0)
      ? currentKgData
      : latestAssistantMessage?.kgData &&
          (latestAssistantMessage.kgData.nodes.length > 0 ||
            latestAssistantMessage.kgData.links.length > 0)
        ? latestAssistantMessage.kgData
        : evidenceGraph.nodes.length > 0 || evidenceGraph.links.length > 0
          ? evidenceGraph
          : null

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
    !!fullKgData && (fullKgData.nodes.length > 0 || fullKgData.links.length > 0)

  const displayData = showFullGraph
    ? hasFullGraph
      ? fullKgData
      : hasCurrentGraph
        ? resolvedKgData
        : null
    : hasCurrentGraph
      ? resolvedKgData
      : null

  const displayMeta = displayData?.meta
  const graphStatusMessage =
    resolvedKgStatus === 'loading' && !hasCurrentGraph
      ? '正在加载当前回答对应的知识子图，请稍候。'
      : resolvedKgStatus === 'error' && !hasCurrentGraph
        ? '当前回答子图加载失败，你可以手动加载全图。'
        : statusMessage

  const loadFullGraph = useCallback(async () => {
    setShowFullGraph(true)
    setLoading(true)
    try {
      const res = await api.getKgVisualization()
      setFullKgData({
        ...res.data,
        meta: {
          ...(res.data.meta ?? {}),
          mode: 'full',
          note: '全量知识图谱',
        },
      })
      setStatusMessage(
        `已加载全图，当前显示 ${res.data.nodes.length} 个节点、${res.data.links.length} 条关系。`
      )
    } catch {
      setStatusMessage('加载全图失败，请稍后重试。')
    } finally {
      setLoading(false)
    }
  }, [])

  const refreshKnowledgeBaseStatus = useCallback(async () => {
    try {
      const res = await api.getKnowledgeBaseStatus()
      setKbStatus(res.data)
      setStatusMessage(formatKbStatus(res.data))
      const isRunning = res.data.status === 'running' || res.data.active === true
      setRebuilding(isRunning)
    } catch {
      setStatusMessage('获取知识库状态失败，请稍后重试。')
    }
  }, [])

  useEffect(() => {
    void refreshKnowledgeBaseStatus()
  }, [refreshKnowledgeBaseStatus])

  useEffect(() => {
    setShowFullGraph(false)
  }, [latestAssistantMessage?.id])

  useEffect(() => {
    if (!kbStatus || kbStatus.status !== 'running') return

    const timer = window.setInterval(() => {
      void refreshKnowledgeBaseStatus()
    }, 5000)
    return () => window.clearInterval(timer)
  }, [kbStatus, refreshKnowledgeBaseStatus])

  const rebuildGraph = useCallback(async () => {
    setRebuilding(true)
    setStatusMessage('已提交重建任务，正在准备导入知识库并重建图谱。')
    try {
      const res = await api.rebuildKnowledgeGraph()
      setKbStatus(res.data)
      setStatusMessage(formatKbStatus(res.data))
      void refreshKnowledgeBaseStatus()
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
          gap: 8,
          marginBottom: 10,
        }}
      >
        <Typography.Text style={{ fontSize: 12, fontWeight: 700 }}>
          知识图谱画布
        </Typography.Text>
        <div style={{ display: 'flex', gap: 6 }}>
          {showFullGraph && hasCurrentGraph && (
            <Button size="small" onClick={() => setShowFullGraph(false)}>
              当前子图
            </Button>
          )}
          <Button
            size="small"
            icon={<ReloadOutlined />}
            onClick={() => void loadFullGraph()}
            loading={loading}
          >
            加载全图
          </Button>
          <Button size="small" type="dashed" onClick={() => void rebuildGraph()} loading={rebuilding}>
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
          <Tag>社区 {kbStatus.counts.communities}</Tag>
        </div>
      )}

      {displayMeta?.note && (
        <div style={{ marginBottom: 8 }}>
          <Tag color={displayMeta.mode === 'full' ? 'default' : 'blue'}>
            {displayMeta.note}
          </Tag>
        </div>
      )}

      {graphStatusMessage && (
        <div style={{ marginBottom: 10 }}>
          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
            {graphStatusMessage}
          </Typography.Text>
        </div>
      )}

      {loading || rebuilding || (resolvedKgStatus === 'loading' && !hasCurrentGraph) ? (
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
          <CanvasGraph data={displayData} />

          {presentTypes.length > 0 && (
            <div style={{ marginTop: 10, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {presentTypes.slice(0, 8).map((type) => (
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
              显示 {Math.min(displayData.nodes.length, MAX_VISIBLE_NODES)} / {displayData.nodes.length} 个节点
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
            gap: 10,
            paddingTop: 40,
          }}
        >
          <span style={{ fontSize: 30, color: '#94a3b8' }}>◎</span>
          <Typography.Text type="secondary" style={{ fontSize: 12, textAlign: 'center' }}>
            当前回答还没有可展示的知识子图。回答完成后会优先显示对应证据子图，你也可以手动加载全图。
          </Typography.Text>
          <div style={{ display: 'flex', gap: 8 }}>
            <Button
              size="small"
              type="dashed"
              icon={<ReloadOutlined />}
              onClick={() => void loadFullGraph()}
              loading={loading}
            >
              手动加载全图
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
