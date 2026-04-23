import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Avatar, Typography } from 'antd'
import { UserOutlined } from '@ant-design/icons'
import type { Message } from '../../types'
import { useChatStore } from '../../stores/chatStore'
import { useProfileStore } from '../../stores/profileStore'

interface Props {
  message: Message
  isStreaming?: boolean
}

function getElapsedSeconds(createdAt: Date | string) {
  return Math.max(
    0,
    Math.floor((Date.now() - new Date(createdAt).getTime()) / 1000)
  )
}

export default function MessageItem({
  message,
  isStreaming = false,
}: Props) {
  const isUser = message.role === 'user'
  const avatarDataUrl = useProfileStore((s) => s.avatarDataUrl)
  const currentPhaseLabel = useChatStore((s) => s.currentPhaseLabel)
  const [elapsedSeconds, setElapsedSeconds] = useState(() =>
    getElapsedSeconds(message.createdAt)
  )

  useEffect(() => {
    setElapsedSeconds(getElapsedSeconds(message.createdAt))
  }, [message.createdAt, message.id])

  useEffect(() => {
    if (!isStreaming) return

    const updateElapsed = () => {
      setElapsedSeconds(getElapsedSeconds(message.createdAt))
    }

    updateElapsed()
    const timer = window.setInterval(updateElapsed, 1000)

    return () => window.clearInterval(timer)
  }, [isStreaming, message.createdAt])

  const showFinalLatency =
    message.totalLatency !== undefined && message.totalLatency > 0
  const showTokenCount =
    message.tokenCount !== undefined && message.tokenCount > 0
  const showStreamingFooter = isStreaming && Boolean(message.content)
  const showFooter = showStreamingFooter || showFinalLatency || showTokenCount
  const phaseLabel = currentPhaseLabel || '思考中'

  if (isUser) {
    return (
      <div
        style={{
          display: 'flex',
          justifyContent: 'flex-end',
          marginBottom: 18,
          gap: 10,
          alignItems: 'flex-start',
        }}
      >
        <div
          style={{
            maxWidth: '72%',
            background: 'linear-gradient(135deg, #e8f4ff 0%, #d6ebff 100%)',
            border: '1px solid #b8d9ff',
            borderRadius: '12px 12px 2px 12px',
            padding: '10px 14px',
          }}
        >
          <Typography.Text
            style={{ fontSize: 14, color: '#1a1a2e', lineHeight: '1.6' }}
          >
            {message.content}
          </Typography.Text>
        </div>
        <Avatar
          src={avatarDataUrl ?? undefined}
          icon={!avatarDataUrl ? <UserOutlined /> : undefined}
          style={{ background: '#1677ff', flexShrink: 0, marginTop: 2 }}
          size={32}
        />
      </div>
    )
  }

  return (
    <div
      style={{
        display: 'flex',
        marginBottom: 22,
        gap: 10,
        alignItems: 'flex-start',
      }}
    >
      <Avatar
        style={{
          background: 'linear-gradient(135deg, #52c41a, #389e0d)',
          flexShrink: 0,
          marginTop: 2,
          fontSize: 16,
        }}
        size={32}
      >
        🩺
      </Avatar>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            background: '#fff',
            border: '1px solid #f0f0f0',
            borderRadius: '2px 12px 12px 12px',
            padding: '12px 16px',
            boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
          }}
        >
          {message.content ? (
            <div className="markdown-content">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
              {isStreaming ? (
                <span
                  aria-hidden="true"
                  style={{
                    display: 'inline-block',
                    marginTop: 2,
                    color: '#1677ff',
                    fontSize: 16,
                    fontWeight: 700,
                    animation: 'pulse 1s infinite',
                  }}
                >
                  ▍
                </span>
              ) : null}
            </div>
          ) : (
            <div
              style={{
                color: '#9aa7b8',
                fontSize: 13,
                display: 'flex',
                alignItems: 'center',
                gap: 8,
              }}
            >
              <span
                style={{
                  display: 'inline-block',
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: '#1677ff',
                  animation: 'pulse 1s infinite',
                }}
              />
              <span>{phaseLabel}</span>
              <span
                style={{
                  color: '#b6c2d1',
                  fontSize: 12,
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {elapsedSeconds} 秒
              </span>
            </div>
          )}
        </div>
        {showFooter ? (
          <div
            style={{
              marginTop: 4,
              display: 'flex',
              gap: 10,
              paddingLeft: 4,
              flexWrap: 'wrap',
            }}
          >
            {showStreamingFooter ? (
              <span
                style={{
                  fontSize: 11,
                  color: '#97a6ba',
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {phaseLabel} · 已用时 {elapsedSeconds} 秒
              </span>
            ) : null}
            {!isStreaming && showFinalLatency ? (
              <span style={{ fontSize: 11, color: '#bbb' }}>
                用时 {message.totalLatency!.toFixed(2)}s
              </span>
            ) : null}
            {showTokenCount ? (
              <span style={{ fontSize: 11, color: '#bbb' }}>
                {message.tokenCount!.toLocaleString()} tokens
              </span>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  )
}
