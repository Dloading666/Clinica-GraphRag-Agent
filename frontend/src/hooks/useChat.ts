import { useCallback, useEffect, useRef } from 'react'
import { api, createSSEConnection } from '../api'
import { buildKgFromSourceItems } from '../lib/sourceGraph'
import { useChatStore } from '../stores/chatStore'
import { useConfigStore } from '../stores/configStore'
import type { DoneData, KGData, ThinkingStep, TraceStep } from '../types'

const STREAM_TICK_MS = 24

function splitIntoGlyphs(value: string) {
  return Array.from(value)
}

function getCharsPerTick(queueSize: number) {
  if (queueSize > 320) return 18
  if (queueSize > 180) return 12
  if (queueSize > 80) return 6
  return 3
}

function normalizeStreamError(err: string) {
  const trimmed = err.trim()
  const lower = trimmed.toLowerCase()

  if (!trimmed) {
    return '网络连接中断，请稍后重试'
  }

  if (
    lower.includes('networkerror') ||
    lower.includes('failed to fetch') ||
    lower.includes('load failed') ||
    lower === 'network error'
  ) {
    return '网络连接中断，请稍后重试'
  }

  if (lower.includes('response stream unavailable')) {
    return '响应流暂时不可用，请稍后重试'
  }

  if (
    lower.startsWith('http 502') ||
    lower.startsWith('http 503') ||
    lower.startsWith('http 504')
  ) {
    return '服务暂时不可用，请稍后再试'
  }

  return trimmed
}

export function useChat() {
  const addUserMessage = useChatStore((s) => s.addUserMessage)
  const startAssistantMessage = useChatStore((s) => s.startAssistantMessage)
  const appendToAssistantMessage = useChatStore(
    (s) => s.appendToAssistantMessage
  )
  const addTraceStep = useChatStore((s) => s.addTraceStep)
  const addThinkingStep = useChatStore((s) => s.addThinkingStep)
  const setKgData = useChatStore((s) => s.setKgData)
  const setKgStatus = useChatStore((s) => s.setKgStatus)
  const finalizeAssistantMessage = useChatStore(
    (s) => s.finalizeAssistantMessage
  )
  const setStreaming = useChatStore((s) => s.setStreaming)
  const setSessionId = useChatStore((s) => s.setSessionId)
  const setCurrentPhase = useChatStore((s) => s.setCurrentPhase)
  const currentSessionId = useChatStore((s) => s.currentSessionId)
  const resetCurrentState = useChatStore((s) => s.resetCurrentState)
  const isStreaming = useChatStore((s) => s.isStreaming)

  const selectedStrategy = useConfigStore((s) => s.selectedStrategy)
  const topK = useConfigStore((s) => s.topK)
  const similarityThreshold = useConfigStore((s) => s.similarityThreshold)
  const debugMode = useConfigStore((s) => s.debugMode)
  const chatDeferKg = useConfigStore((s) => s.chatDeferKg)
  const typingEffectEnabled = useConfigStore((s) => s.typingEffectEnabled)

  const activeAssistantIdRef = useRef<string | null>(null)
  const connectionCleanupRef = useRef<(() => void) | null>(null)
  const pendingDoneRef = useRef<DoneData | null>(null)
  const streamFinishedRef = useRef(false)
  const chunkBufferRef = useRef('')
  const flushFrameRef = useRef<number | null>(null)
  const typingQueueRef = useRef<string[]>([])
  const typingTimerRef = useRef<number | null>(null)

  const stopActiveConnection = useCallback(() => {
    if (connectionCleanupRef.current) {
      connectionCleanupRef.current()
      connectionCleanupRef.current = null
    }
  }, [])

  const stopTypingLoop = useCallback(() => {
    if (typingTimerRef.current !== null) {
      window.clearInterval(typingTimerRef.current)
      typingTimerRef.current = null
    }
  }, [])

  const stopFlushFrame = useCallback(() => {
    if (flushFrameRef.current !== null) {
      window.cancelAnimationFrame(flushFrameRef.current)
      flushFrameRef.current = null
    }
  }, [])

  const hasPendingAnswer = useCallback(() => {
    return typingQueueRef.current.length > 0 || chunkBufferRef.current.length > 0
  }, [])

  const flushBufferedAnswer = useCallback(
    (sync = false) => {
      const assistantId = activeAssistantIdRef.current
      if (!assistantId) {
        stopTypingLoop()
        stopFlushFrame()
        typingQueueRef.current = []
        chunkBufferRef.current = ''
        return
      }

      if (typingEffectEnabled) {
        if (typingQueueRef.current.length === 0) {
          return
        }

        const nextChunk = sync
          ? typingQueueRef.current.splice(0, typingQueueRef.current.length).join('')
          : typingQueueRef.current
              .splice(0, getCharsPerTick(typingQueueRef.current.length))
              .join('')

        if (nextChunk) {
          appendToAssistantMessage(assistantId, nextChunk)
        }
        return
      }

      if (!chunkBufferRef.current) {
        return
      }

      const nextChunk = chunkBufferRef.current
      chunkBufferRef.current = ''
      appendToAssistantMessage(assistantId, nextChunk)
    },
    [appendToAssistantMessage, stopFlushFrame, stopTypingLoop, typingEffectEnabled]
  )

  const resetStreamingState = useCallback(() => {
    stopTypingLoop()
    stopFlushFrame()
    typingQueueRef.current = []
    chunkBufferRef.current = ''
    pendingDoneRef.current = null
    streamFinishedRef.current = false
    activeAssistantIdRef.current = null
    setCurrentPhase('')
  }, [setCurrentPhase, stopFlushFrame, stopTypingLoop])

  const finalizeIfReady = useCallback(() => {
    const assistantId = activeAssistantIdRef.current
    if (!assistantId) return false
    if (!streamFinishedRef.current || hasPendingAnswer()) {
      return false
    }

    finalizeAssistantMessage(assistantId, pendingDoneRef.current ?? undefined)
    setStreaming(false)
    resetStreamingState()
    return true
  }, [
    finalizeAssistantMessage,
    hasPendingAnswer,
    resetStreamingState,
    setStreaming,
  ])

  const flushAllPending = useCallback(() => {
    stopTypingLoop()
    stopFlushFrame()
    flushBufferedAnswer(true)
  }, [flushBufferedAnswer, stopFlushFrame, stopTypingLoop])

  const ensureTypingLoop = useCallback(() => {
    if (!typingEffectEnabled || typingTimerRef.current !== null) {
      return
    }

    typingTimerRef.current = window.setInterval(() => {
      flushBufferedAnswer()
      if (typingQueueRef.current.length === 0) {
        stopTypingLoop()
        finalizeIfReady()
      }
    }, STREAM_TICK_MS)
  }, [finalizeIfReady, flushBufferedAnswer, stopTypingLoop, typingEffectEnabled])

  const ensureFlushFrame = useCallback(() => {
    if (typingEffectEnabled || flushFrameRef.current !== null) {
      return
    }

    flushFrameRef.current = window.requestAnimationFrame(() => {
      flushFrameRef.current = null
      flushBufferedAnswer(true)
      finalizeIfReady()
    })
  }, [finalizeIfReady, flushBufferedAnswer, typingEffectEnabled])

  const hydrateKgForMessage = useCallback(
    async (query: string, assistantId: string, doneData?: DoneData | null) => {
      const sourceItems = doneData?.source_items ?? []
      if (sourceItems.length > 0) {
        const graph = buildKgFromSourceItems(sourceItems)
        if (graph.nodes.length > 0 || graph.links.length > 0) {
          setKgData(assistantId, graph)
          return
        }
      }

      setKgStatus(assistantId, 'loading')
      try {
        const response = await api.getKgForQuery(query)
        setKgData(assistantId, response.data)
      } catch {
        setKgStatus(assistantId, 'error')
      }
    },
    [setKgData, setKgStatus]
  )

  useEffect(
    () => () => {
      stopActiveConnection()
      resetStreamingState()
    },
    [resetStreamingState, stopActiveConnection]
  )

  const sendMessage = useCallback(
    (message: string) => {
      const query = message.trim()
      if (!query || isStreaming) return

      stopActiveConnection()

      addUserMessage(query)
      const assistantId = startAssistantMessage()
      resetStreamingState()
      activeAssistantIdRef.current = assistantId
      resetCurrentState()
      setStreaming(true)

      const cleanup = createSSEConnection(
        {
          message: query,
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
            return
          }

          if (event === 'trace') {
            const traceData = data as Partial<TraceStep> & { node: string }
            setCurrentPhase(getNodeLabel(traceData.node))
            addTraceStep({
              node: getNodeLabel(traceData.node),
              input: traceData.input,
              output: traceData.output,
              latency: traceData.latency,
              icon: getNodeIcon(traceData.node),
            })
            return
          }

          if (event === 'thinking') {
            const thinkingData = data as ThinkingStep
            setCurrentPhase(thinkingData.label)
            addThinkingStep(thinkingData)
            return
          }

          if (event === 'answer') {
            setCurrentPhase('正在生成回答')
            const chunk = String(data)
            if (!chunk) return

            if (typingEffectEnabled) {
              typingQueueRef.current.push(...splitIntoGlyphs(chunk))
              flushBufferedAnswer()
              ensureTypingLoop()
              return
            }

            chunkBufferRef.current += chunk
            ensureFlushFrame()
            return
          }

          if (event === 'kg_data') {
            setKgData(assistantId, data as KGData)
          }
        },
        (doneData?: DoneData) => {
          connectionCleanupRef.current = null
          pendingDoneRef.current = doneData ?? null
          streamFinishedRef.current = true
          setCurrentPhase('回答完成')
          flushAllPending()
          finalizeIfReady()

          if (chatDeferKg) {
            void hydrateKgForMessage(query, assistantId, doneData ?? null)
          }
        },
        (err) => {
          connectionCleanupRef.current = null
          flushAllPending()

          const friendlyError = normalizeStreamError(err)
          const currentContent =
            useChatStore
              .getState()
              .messages.find((messageItem) => messageItem.id === assistantId)
              ?.content ?? ''
          const hasAnswerContent = Boolean(currentContent.trim())

          appendToAssistantMessage(
            assistantId,
            hasAnswerContent
              ? `\n\n连接中断，已保留已生成内容。${friendlyError}`
              : `抱歉，${friendlyError}。`
          )
          setCurrentPhase('回答中断')
          finalizeAssistantMessage(assistantId, undefined)
          setStreaming(false)
          resetStreamingState()
        }
      )

      connectionCleanupRef.current = cleanup
      return cleanup
    },
    [
      addThinkingStep,
      addTraceStep,
      addUserMessage,
      appendToAssistantMessage,
      chatDeferKg,
      currentSessionId,
      debugMode,
      ensureFlushFrame,
      ensureTypingLoop,
      finalizeAssistantMessage,
      finalizeIfReady,
      flushAllPending,
      flushBufferedAnswer,
      hydrateKgForMessage,
      isStreaming,
      resetCurrentState,
      resetStreamingState,
      selectedStrategy,
      setCurrentPhase,
      setKgData,
      setSessionId,
      setStreaming,
      similarityThreshold,
      startAssistantMessage,
      stopActiveConnection,
      topK,
      typingEffectEnabled,
    ]
  )

  return { sendMessage, isStreaming }
}

function getNodeLabel(node: string): string {
  const labels: Record<string, string> = {
    agent: '实体提取',
    retrieve: '向量搜索',
    generate: '逻辑推演与生成',
    reduce: '图谱汇总',
    naive_search: '向量搜索',
    local_search: '图谱扩展',
    global_search: '全局搜索',
    extract_keywords: '关键词提取',
    fast_cache_hit: '缓存命中',
    global_cache_hit: '全局缓存命中',
    decompose: '问题分解',
    search: '知识检索',
    evaluate: '证据评估',
    synthesize: '综合生成',
  }
  return labels[node] || node
}

function getNodeIcon(node: string): string {
  const icons: Record<string, string> = {
    agent: '🧠',
    retrieve: '📚',
    generate: '✍️',
    reduce: '🧩',
    local_search: '🗂️',
    global_search: '🌐',
    decompose: '📝',
    search: '🔎',
    evaluate: '⚖️',
    synthesize: '🪄',
  }
  return icons[node] || '•'
}
