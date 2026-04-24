import axios from 'axios'
import type { AppConfig, DoneData, KGData, KnowledgeBaseStatus } from '../types'

const BASE_URL = '/api'
const STREAM_STALL_TIMEOUT_MS = 95_000

export const api = {
  getConfig: () => axios.get<AppConfig>(`${BASE_URL}/chat/config`),
  getSessions: () => axios.get(`${BASE_URL}/chat/sessions`),
  getMessages: (sessionId: string) =>
    axios.get(`${BASE_URL}/chat/sessions/${sessionId}/messages`),
  getKgVisualization: (limit = 100) =>
    axios.get<KGData>(`${BASE_URL}/kg/visualization?limit=${limit}`),
  getKgForQuery: (q: string) =>
    axios.get<KGData>(`${BASE_URL}/kg/query?q=${encodeURIComponent(q)}`),
  rebuildKnowledgeGraph: () =>
    axios.post<KnowledgeBaseStatus>(`${BASE_URL}/knowledge-base/rebuild-graph`),
  getKnowledgeBaseStatus: () =>
    axios.get<KnowledgeBaseStatus>(`${BASE_URL}/knowledge-base/status`),
  getStats: () => axios.get(`${BASE_URL}/analytics/stats`),
}

export function createSSEConnection(
  body: Record<string, unknown>,
  onEvent: (event: string, data: unknown) => void,
  onDone: (data?: DoneData) => void,
  onError: (err: string) => void
): () => void {
  const controller = new AbortController()
  let receivedDoneEvent = false
  let receivedAnyEvent = false
  let retryTimer: number | null = null
  let stallTimer: number | null = null
  let attempt = 0
  let terminatedByError = false
  let lastProgressAt = Date.now()

  const clearRetryTimer = () => {
    if (retryTimer !== null) {
      window.clearTimeout(retryTimer)
      retryTimer = null
    }
  }

  const clearStallTimer = () => {
    if (stallTimer !== null) {
      window.clearInterval(stallTimer)
      stallTimer = null
    }
  }

  const markProgress = () => {
    lastProgressAt = Date.now()
  }

  const handleTerminalError = (message: string) => {
    if (terminatedByError || receivedDoneEvent) {
      return
    }
    terminatedByError = true
    clearRetryTimer()
    clearStallTimer()
    controller.abort()
    onError(message)
  }

  const armStallTimer = () => {
    clearStallTimer()
    stallTimer = window.setInterval(() => {
      if (controller.signal.aborted || receivedDoneEvent || terminatedByError) {
        clearStallTimer()
        return
      }
      if (Date.now() - lastProgressAt < STREAM_STALL_TIMEOUT_MS) {
        return
      }
      handleTerminalError('模型响应超时，请重试。')
    }, 1000)
  }

  const startRequest = () => {
    markProgress()
    armStallTimer()

    fetch(`${BASE_URL}/chat/stream`, {
      method: 'POST',
      headers: {
        Accept: 'text/event-stream',
        'Content-Type': 'application/json; charset=utf-8',
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          clearStallTimer()
          onError(`HTTP ${response.status}: ${response.statusText}`)
          return
        }

        const reader = response.body?.getReader()
        if (!reader) {
          clearStallTimer()
          onError('响应流不可用，请稍后重试')
          return
        }

        const decoder = new TextDecoder('utf-8')
        let buffer = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''

          for (const line of lines) {
            if (!line.startsWith('data: ')) {
              continue
            }

            try {
              const parsed = JSON.parse(line.slice(6)) as {
                event: string
                data: unknown
              }

              receivedAnyEvent = true
              if (!(parsed.event === 'status' && parsed.data === 'heartbeat')) {
                markProgress()
              }

              if (parsed.event === 'done') {
                receivedDoneEvent = true
                clearStallTimer()
                onDone(parsed.data as DoneData)
                return
              }

              if (parsed.event === 'error') {
                handleTerminalError(String(parsed.data || '模型响应异常，请重试。'))
                return
              }

              onEvent(parsed.event, parsed.data)
            } catch {
              // Ignore malformed frames and keep the stream alive.
            }
          }
        }

        clearStallTimer()
        if (terminatedByError) {
          return
        }
        if (!receivedDoneEvent) {
          if (!receivedAnyEvent && attempt < 1 && !controller.signal.aborted) {
            attempt += 1
            retryTimer = window.setTimeout(startRequest, 500)
            return
          }
          onDone()
        }
      })
      .catch((err: Error) => {
        clearStallTimer()
        if (err.name === 'AbortError') {
          return
        }

        if (!receivedAnyEvent && attempt < 1 && !controller.signal.aborted) {
          attempt += 1
          retryTimer = window.setTimeout(startRequest, 500)
          return
        }

        onError(err.message || '网络连接中断，请稍后重试')
      })
  }

  startRequest()

  return () => {
    clearRetryTimer()
    clearStallTimer()
    controller.abort()
  }
}
