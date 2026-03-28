import axios from 'axios'
import type { AppConfig, KGData, DoneData } from '../types'

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
    axios.post(`${BASE_URL}/knowledge-base/rebuild-graph`),
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

  fetch(`${BASE_URL}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        onError(`HTTP ${response.status}: ${response.statusText}`)
        return
      }

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const parsed = JSON.parse(line.slice(6)) as {
                event: string
                data: unknown
              }
              if (parsed.event === 'done') {
                receivedDoneEvent = true
                onDone(parsed.data as DoneData)
              } else if (parsed.event === 'error') {
                onError(String(parsed.data))
              } else {
                onEvent(parsed.event, parsed.data)
              }
            } catch {
              // ignore malformed lines
            }
          }
        }
      }
      if (!receivedDoneEvent) {
        onDone()
      }
    })
    .catch((err: Error) => {
      if (err.name !== 'AbortError') onError(err.message)
    })

  return () => controller.abort()
}
