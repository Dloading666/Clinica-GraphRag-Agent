import { useEffect, useRef } from 'react'
import { Input, Button, Typography } from 'antd'
import { SendOutlined } from '@ant-design/icons'
import { useChatStore } from '../../stores/chatStore'
import { useChat } from '../../hooks/useChat'
import MessageItem from './MessageItem'

const { TextArea } = Input

export default function ChatPanel() {
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const { messages, isStreaming, draftMessage, setDraftMessage } =
    useChatStore()
  const { sendMessage } = useChat()

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSend = () => {
    if (!draftMessage.trim() || isStreaming) return
    sendMessage(draftMessage.trim())
    setDraftMessage('')
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        background:
          'linear-gradient(180deg, rgba(255,255,255,1) 0%, rgba(249,251,254,0.92) 100%)',
      }}
    >
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '24px 28px',
        }}
      >
        {messages.length === 0 ? (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              minHeight: '100%',
              padding: '44px 12px 72px',
              textAlign: 'center',
            }}
          >
            <div style={{ fontSize: 52, marginBottom: 18 }}>🩺</div>
            <Typography.Title
              level={2}
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
                fontSize: 15,
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
          <>
            {messages.map((msg, index) => (
              <MessageItem
                key={msg.id}
                message={msg}
                isStreaming={
                  isStreaming &&
                  index === messages.length - 1 &&
                  msg.role === 'assistant'
                }
              />
            ))}
          </>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div
        style={{
          padding: '6px 28px',
          borderTop: '1px solid #edf1f6',
          background: 'rgba(248,250,252,0.95)',
        }}
      >
        <Typography.Text type="secondary" style={{ fontSize: 11 }}>
          临床辅助系统提示：AI 生成结果仅供专业参考，不替代临床诊断与治疗决策。
        </Typography.Text>
      </div>

      <div
        style={{
          padding: '12px 28px 16px',
          background: '#fff',
        }}
      >
        <div className="chat-input-shell">
          <TextArea
            value={draftMessage}
            onChange={(e) => setDraftMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入临床问题或补充病史信息…（Enter 发送，Shift+Enter 换行）"
            autoSize={{ minRows: 1, maxRows: 5 }}
            variant="borderless"
            style={{
              flex: 1,
              background: 'transparent',
              resize: 'none',
              fontSize: 14,
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
