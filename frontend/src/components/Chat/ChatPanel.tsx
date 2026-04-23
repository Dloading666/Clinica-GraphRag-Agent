import { useCallback, useEffect, useRef } from 'react'
import { Button, Input, Typography } from 'antd'
import { SendOutlined } from '@ant-design/icons'
import MessageItem from './MessageItem'
import { useChat } from '../../hooks/useChat'
import { useChatStore } from '../../stores/chatStore'

const { TextArea } = Input

const SCROLL_FOLLOW_THRESHOLD = 96

interface ChatPanelProps {
  isMobile?: boolean
}

function isNearBottom(element: HTMLDivElement) {
  return (
    element.scrollHeight - element.scrollTop - element.clientHeight <=
    SCROLL_FOLLOW_THRESHOLD
  )
}

export default function ChatPanel({ isMobile = false }: ChatPanelProps) {
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const scrollFrameRef = useRef<number | null>(null)
  const autoFollowRef = useRef(true)
  const previousMessageCountRef = useRef(0)
  const previousLatestMessageIdRef = useRef<string | null>(null)

  const messages = useChatStore((s) => s.messages)
  const isStreaming = useChatStore((s) => s.isStreaming)
  const draftMessage = useChatStore((s) => s.draftMessage)
  const setDraftMessage = useChatStore((s) => s.setDraftMessage)
  const { sendMessage } = useChat()

  const latestMessage = messages[messages.length - 1]
  const latestMessageId = latestMessage?.id ?? null
  const latestMessageRole = latestMessage?.role
  const latestMessageContent = latestMessage?.content ?? ''

  const cancelScheduledScroll = useCallback(() => {
    if (scrollFrameRef.current !== null) {
      window.cancelAnimationFrame(scrollFrameRef.current)
      scrollFrameRef.current = null
    }
  }, [])

  const scheduleScrollToBottom = useCallback(
    (behavior: ScrollBehavior = 'auto') => {
      cancelScheduledScroll()

      scrollFrameRef.current = window.requestAnimationFrame(() => {
        scrollFrameRef.current = null
        const element = scrollContainerRef.current
        if (!element) {
          return
        }

        element.scrollTo({
          top: element.scrollHeight,
          behavior,
        })
      })
    },
    [cancelScheduledScroll]
  )

  const handleScroll = useCallback(() => {
    const element = scrollContainerRef.current
    if (!element) {
      return
    }

    autoFollowRef.current = isNearBottom(element)
  }, [])

  useEffect(() => () => cancelScheduledScroll(), [cancelScheduledScroll])

  useEffect(() => {
    const isNewMessage =
      messages.length !== previousMessageCountRef.current ||
      latestMessageId !== previousLatestMessageIdRef.current

    if (isNewMessage && (latestMessageRole === 'user' || messages.length <= 2)) {
      autoFollowRef.current = true
    }

    if (autoFollowRef.current) {
      scheduleScrollToBottom(isStreaming ? 'auto' : 'smooth')
    }

    previousMessageCountRef.current = messages.length
    previousLatestMessageIdRef.current = latestMessageId
  }, [
    isStreaming,
    latestMessageContent,
    latestMessageId,
    latestMessageRole,
    messages.length,
    scheduleScrollToBottom,
  ])

  const handleSend = () => {
    if (!draftMessage.trim() || isStreaming) return

    autoFollowRef.current = true
    sendMessage(draftMessage.trim())
    setDraftMessage('')
  }

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      handleSend()
    }
  }

  return (
    <div
      className={`chat-panel${isMobile ? ' chat-panel--mobile' : ''}`}
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        minHeight: 0,
        background:
          'linear-gradient(180deg, rgba(255,255,255,1) 0%, rgba(249,251,254,0.92) 100%)',
      }}
    >
      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        className="chat-panel__messages"
        style={{
          flex: 1,
          minHeight: 0,
          overflowY: 'auto',
          overscrollBehavior: 'contain',
          padding: isMobile ? '16px 14px' : '24px 28px',
        }}
      >
        {messages.length === 0 ? (
          <div
            className="chat-panel__empty"
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              minHeight: '100%',
              padding: isMobile ? '24px 8px 48px' : '44px 12px 72px',
              textAlign: 'center',
            }}
          >
            <div style={{ fontSize: isMobile ? 42 : 52, marginBottom: 18 }}>
              🩺
            </div>
            <Typography.Title
              level={isMobile ? 3 : 2}
              style={{
                color: '#15233a',
                marginBottom: 10,
                textAlign: 'center',
                letterSpacing: '0.01em',
              }}
            >
              临床诊疗问答助手
            </Typography.Title>
            <Typography.Paragraph
              style={{
                marginBottom: 10,
                fontSize: isMobile ? 14 : 15,
                lineHeight: 1.8,
                color: '#536176',
                maxWidth: 620,
              }}
            >
              结合知识图谱与多种检索策略，帮助你快速查询病理学、药理学与中医基础理论等相关内容。
            </Typography.Paragraph>
            <Typography.Text
              style={{
                fontSize: 12,
                color: '#7a889b',
                letterSpacing: '0.04em',
              }}
            >
              左侧已提供 4 个示例问题，可直接点击填入提问框。
            </Typography.Text>
          </div>
        ) : (
          messages.map((message, index) => (
            <MessageItem
              key={message.id}
              message={message}
              isStreaming={
                isStreaming &&
                index === messages.length - 1 &&
                message.role === 'assistant'
              }
            />
          ))
        )}
      </div>

      <div
        className="chat-panel__notice"
        style={{
          padding: isMobile ? '8px 14px' : '6px 28px',
          borderTop: '1px solid #edf1f6',
          background: 'rgba(248,250,252,0.95)',
        }}
      >
        <Typography.Text type="secondary" style={{ fontSize: 11 }}>
          临床辅助系统提示：AI 生成结果仅供专业参考，不替代临床诊断与治疗决策。
        </Typography.Text>
      </div>

      <div
        className="chat-panel__composer"
        style={{
          padding: isMobile
            ? '10px 14px calc(12px + env(safe-area-inset-bottom, 0px))'
            : '12px 28px 16px',
          background: '#fff',
        }}
      >
        <div className="chat-input-shell">
          <TextArea
            value={draftMessage}
            onChange={(event) => setDraftMessage(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入临床问题或补充病史信息…（Enter 发送，Shift+Enter 换行）"
            autoSize={{ minRows: 1, maxRows: isMobile ? 4 : 5 }}
            variant="borderless"
            style={{
              flex: 1,
              background: 'transparent',
              resize: 'none',
              fontSize: isMobile ? 15 : 14,
            }}
          />
          <Button
            type="primary"
            icon={<SendOutlined />}
            onClick={handleSend}
            disabled={!draftMessage.trim() || isStreaming}
            loading={isStreaming}
            style={{ borderRadius: 10, marginBottom: 2 }}
          />
        </div>
      </div>
    </div>
  )
}
