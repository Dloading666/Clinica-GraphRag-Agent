import { useState } from 'react'
import { useChatStore } from '../../stores/chatStore'
import type { ThinkingStep } from '../../types'

interface ThinkingItemProps {
  step: ThinkingStep
}

function ThinkingItem({ step }: ThinkingItemProps) {
  const [expanded, setExpanded] = useState(false)
  const hasContent = step.content && step.content.length > 0

  return (
    <div
      style={{
        padding: '6px 12px',
        borderBottom: '1px solid #f0f0f0',
        opacity: step.done ? 1 : 0.7,
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          cursor: hasContent ? 'pointer' : 'default',
        }}
        onClick={() => hasContent && setExpanded(!expanded)}
      >
        <span style={{ fontSize: 12 }}>
          {step.done ? '✅' : '⏳'}
        </span>
        <span style={{ fontSize: 13, fontWeight: 500, color: '#333' }}>
          {step.label}
        </span>
        {hasContent && (
          <span style={{ marginLeft: 'auto', fontSize: 11, color: '#999' }}>
            {expanded ? '▼' : '▶'}
          </span>
        )}
      </div>
      {expanded && hasContent && (
        <div
          style={{
            marginTop: 6,
            marginLeft: 20,
            fontSize: 12,
            color: '#666',
            lineHeight: 1.6,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            background: '#fafafa',
            padding: '6px 10px',
            borderRadius: 4,
            maxHeight: 200,
            overflowY: 'auto',
          }}
        >
          {step.content}
        </div>
      )}
    </div>
  )
}

export default function ThinkingPanel() {
  const currentThinkingSteps = useChatStore((s) => s.currentThinkingSteps)
  const messages = useChatStore((s) => s.messages)
  const isStreaming = useChatStore((s) => s.isStreaming)
  const [visible, setVisible] = useState(true)
  const latestAssistantMessage = [...messages]
    .reverse()
    .find((message) => message.role === 'assistant')
  const thinkingSteps =
    currentThinkingSteps.length > 0
      ? currentThinkingSteps
      : !isStreaming
        ? latestAssistantMessage?.thinkingSteps ?? []
        : []

  if (thinkingSteps.length === 0) {
    return (
      <div
        style={{
          height: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#ccc',
          fontSize: 13,
        }}
      >
        思考过程将实时显示
      </div>
    )
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Header with toggle */}
      <div
        style={{
          padding: '4px 12px',
          borderBottom: '1px solid #f0f0f0',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          background: '#fafafa',
          flexShrink: 0,
        }}
      >
        <span style={{ fontSize: 12, color: '#666' }}>
          思考过程 · {thinkingSteps.length} 步
        </span>
        <button
          onClick={() => setVisible(!visible)}
          style={{
            marginLeft: 'auto',
            background: 'none',
            border: '1px solid #ddd',
            borderRadius: 4,
            padding: '1px 8px',
            fontSize: 11,
            cursor: 'pointer',
            color: '#666',
          }}
        >
          {visible ? '隐藏' : '显示'}
        </button>
      </div>

      {/* Thinking steps */}
      {visible && (
        <div
          style={{
            flex: 1,
            overflowY: 'auto',
          }}
        >
          {thinkingSteps.map((step, index) => (
            <ThinkingItem key={`${step.node}-${index}`} step={step} />
          ))}
        </div>
      )}
    </div>
  )
}
