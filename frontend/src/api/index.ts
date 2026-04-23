import axios from 'axios'
import type { AppConfig, DoneData, KGData, KnowledgeBaseStatus } from '../types'

const BASE_URL = '/api'

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
  let attempt = 0

  const clearRetryTimer = () => {
    if (retryTimer !== null) {
      window.clearTimeout(retryTimer)
      retryTimer = null
    }
  }

  const startRequest = () => {
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
          onError(`HTTP ${response.status}: ${response.statusText}`)
          return
        }

        const reader = response.body?.getReader()
        if (!reader) {
          onError('\u54cd\u5e94\u6d41\u4e0d\u53ef\u7528\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5')
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

              if (parsed.event === 'done') {
                receivedDoneEvent = true
                onDone(parsed.data as DoneData)
              } else if (parsed.event === 'error') {
                onError(String(parsed.data))
              } else {
                onEvent(parsed.event, parsed.data)
              }
            } catch {
              // Ignore malformed frames and keep the stream alive.
            }
          }
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
        if (err.name === 'AbortError') return

        if (!receivedAnyEvent && attempt < 1 && !controller.signal.aborted) {
          attempt += 1
          retryTimer = window.setTimeout(startRequest, 500)
          return
        }

        onError(err.message || '\u7f51\u7edc\u8fde\u63a5\u4e2d\u65ad\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5')
      })
  }

  startRequest()

  return () => {
    clearRetryTimer()
    controller.abort()
  }
}
