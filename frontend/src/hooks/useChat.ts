import { useCallback } from 'react'
import { useChatStore } from '../stores/chatStore'
import { useConfigStore } from '../stores/configStore'
import { createSSEConnection } from '../api'
import type { DoneData, KGData, TraceStep } from '../types'

export function useChat() {
  const {
    addUserMessage,
    startAssistantMessage,
    appendToAssistantMessage,
    addTraceStep,
    setKgData,
    finalizeAssistantMessage,
    setStreaming,
    setSessionId,
    currentSessionId,
    resetCurrentState,
    isStreaming,
  } = useChatStore()

  const { selectedStrategy, topK, similarityThreshold, debugMode } =
    useConfigStore()

  const sendMessage = useCallback(
    (message: string) => {
      if (!message.trim() || isStreaming) return

      addUserMessage(message)
      const assistantId = startAssistantMessage()
      resetCurrentState()
      setStreaming(true)

      const cleanup = createSSEConnection(
        {
          message,
          session_id: currentSessionId,
          agent_type: selectedStrategy,
          top_k: topK,
          similarity_threshold: similarityThreshold,
          debug: debugMode,
        },
        (event, data) => {
          if (event === 'session') {
            const sessionData = data as { session_id: string }
            setSessionId(sessionData.session_id)
          } else if (event === 'trace') {
            const traceData = data as Partial<TraceStep> & { node: string }
            addTraceStep({
              node: getNodeLabel(traceData.node),
              input: traceData.input,
              output: traceData.output,
              latency: traceData.latency,
              icon: getNodeIcon(traceData.node),
            })
          } else if (event === 'answer') {
            appendToAssistantMessage(assistantId, String(data))
          } else if (event === 'kg_data') {
            setKgData(data as KGData)
          }
        },
        (doneData?: DoneData) => {
          if (doneData) {
            finalizeAssistantMessage(
              assistantId,
              doneData.total_latency ?? 0,
              doneData.token_count ?? 0
            )
          } else {
            finalizeAssistantMessage(assistantId, 0, 0)
          }
          setStreaming(false)
        },
        (err) => {
          appendToAssistantMessage(assistantId, `\n\n❌ 错误: ${err}`)
          setStreaming(false)
        }
      )

      return cleanup
    },
    [
      isStreaming,
      currentSessionId,
      selectedStrategy,
      topK,
      similarityThreshold,
      debugMode,
      addUserMessage,
      startAssistantMessage,
      resetCurrentState,
      setStreaming,
      setSessionId,
      addTraceStep,
      appendToAssistantMessage,
      setKgData,
      finalizeAssistantMessage,
    ]
  )

  return { sendMessage, isStreaming }
}

function getNodeLabel(node: string): string {
  const labels: Record<string, string> = {
    agent: '实体抽取',
    retrieve: '向量搜索 (Vector Retrieval)',
    generate: '逻辑推演与生成',
    reduce: '图谱汇总',
    naive_search: '向量搜索',
    local_search: '图谱扩展 (KG Expansion)',
    global_search: '全局搜索',
    extract_keywords: '关键词提取',
    fast_cache_hit: '缓存命中',
    global_cache_hit: '全局缓存命中',
  }
  return labels[node] || node
}

function getNodeIcon(node: string): string {
  const icons: Record<string, string> = {
    agent: '⚡',
    retrieve: '🔍',
    generate: '✍️',
    local_search: '🕸️',
    global_search: '🌐',
  }
  return icons[node] || '●'
}
