import { create } from 'zustand'
import { v4 as uuidv4 } from 'uuid'
import type {
  DoneData,
  KGData,
  KGStatus,
  Message,
  ThinkingStep,
  TraceStep,
} from '../types'

function thinkingToTrace(step: ThinkingStep): TraceStep {
  return {
    node: step.label,
    output: step.content,
  }
}

function getLatestAssistantId(messages: Message[]): string | undefined {
  return [...messages].reverse().find((message) => message.role === 'assistant')?.id
}

function hasSameThinkingContent(a: ThinkingStep, b: ThinkingStep) {
  return (a.content ?? '').trim() === (b.content ?? '').trim()
}

function mergeThinkingStep(steps: ThinkingStep[], step: ThinkingStep) {
  const duplicateIndex = steps.findIndex(
    (existing) =>
      existing.node === step.node &&
      existing.label === step.label &&
      hasSameThinkingContent(existing, step)
  )

  if (duplicateIndex >= 0) {
    return steps.map((existing, index) =>
      index === duplicateIndex
        ? { ...existing, ...step, done: existing.done || step.done }
        : existing
    )
  }

  if (step.done) {
    const pendingIndex = steps.findIndex(
      (existing) =>
        existing.node === step.node &&
        existing.label === step.label &&
        !existing.done
    )

    if (pendingIndex >= 0) {
      return steps.map((existing, index) =>
        index === pendingIndex ? step : existing
      )
    }
  }

  return [...steps, step]
}

interface ChatStore {
  messages: Message[]
  currentSessionId: string | null
  isStreaming: boolean
  draftMessage: string
  currentTraceSteps: TraceStep[]
  currentThinkingSteps: ThinkingStep[]
  currentKgData: KGData | null
  currentKgStatus: KGStatus
  currentAnswer: string
  currentPhaseLabel: string
  totalLatency: number
  tokenCount: number
  firstTokenLatencyMs: number
  retrieveLatencyMs: number
  answerCompleteLatencyMs: number

  addUserMessage: (content: string) => string
  startAssistantMessage: () => string
  appendToAssistantMessage: (id: string, token: string) => void
  addTraceStep: (step: TraceStep) => void
  addThinkingStep: (step: ThinkingStep) => void
  setKgData: (id: string, data: KGData) => void
  setKgStatus: (id: string, status: KGStatus) => void
  finalizeAssistantMessage: (id: string, doneData?: DoneData) => void
  setDraftMessage: (message: string) => void
  setStreaming: (v: boolean) => void
  setSessionId: (id: string) => void
  setCurrentPhase: (phase: string) => void
  clearMessages: () => void
  resetCurrentState: () => void
}

export const useChatStore = create<ChatStore>((set, get) => ({
  messages: [],
  currentSessionId: null,
  isStreaming: false,
  draftMessage: '',
  currentTraceSteps: [],
  currentThinkingSteps: [],
  currentKgData: null,
  currentKgStatus: 'idle',
  currentAnswer: '',
  currentPhaseLabel: '',
  totalLatency: 0,
  tokenCount: 0,
  firstTokenLatencyMs: 0,
  retrieveLatencyMs: 0,
  answerCompleteLatencyMs: 0,

  addUserMessage: (content) => {
    const id = uuidv4()
    set((state) => ({
      messages: [
        ...state.messages,
        { id, role: 'user', content, createdAt: new Date() },
      ],
    }))
    return id
  },

  startAssistantMessage: () => {
    const id = uuidv4()
    set((state) => ({
      messages: [
        ...state.messages,
        {
          id,
          role: 'assistant',
          content: '',
          kgStatus: 'idle',
          createdAt: new Date(),
        },
      ],
      currentAnswer: '',
      currentPhaseLabel: '',
      currentTraceSteps: [],
      currentThinkingSteps: [],
      currentKgData: null,
      currentKgStatus: 'idle',
      totalLatency: 0,
      tokenCount: 0,
      firstTokenLatencyMs: 0,
      retrieveLatencyMs: 0,
      answerCompleteLatencyMs: 0,
    }))
    return id
  },

  appendToAssistantMessage: (id, token) => {
    set((state) => ({
      messages: state.messages.map((message) =>
        message.id === id ? { ...message, content: message.content + token } : message
      ),
      currentAnswer: state.currentAnswer + token,
    }))
  },

  addTraceStep: (step) => {
    set((state) => ({
      currentTraceSteps: [...state.currentTraceSteps, step],
    }))
  },

  addThinkingStep: (step) => {
    set((state) => {
      const currentThinkingSteps = mergeThinkingStep(
        state.currentThinkingSteps,
        step
      )
      const currentTraceSteps = currentThinkingSteps.map(thinkingToTrace)

      return {
        currentThinkingSteps,
        currentTraceSteps,
      }
    })
  },

  setKgData: (id, data) => {
    set((state) => ({
      messages: state.messages.map((message) =>
        message.id === id
          ? {
              ...message,
              kgData: data,
              kgStatus: 'ready',
            }
          : message
      ),
      currentKgData:
        getLatestAssistantId(state.messages) === id ? data : state.currentKgData,
      currentKgStatus:
        getLatestAssistantId(state.messages) === id ? 'ready' : state.currentKgStatus,
    }))
  },

  setKgStatus: (id, status) => {
    set((state) => ({
      messages: state.messages.map((message) =>
        message.id === id
          ? {
              ...message,
              kgStatus: status,
            }
          : message
      ),
      currentKgStatus:
        getLatestAssistantId(state.messages) === id ? status : state.currentKgStatus,
      currentKgData:
        getLatestAssistantId(state.messages) === id && status !== 'ready'
          ? null
          : state.currentKgData,
    }))
  },

  finalizeAssistantMessage: (id, doneData) => {
    const { currentTraceSteps, currentThinkingSteps, currentKgData, currentKgStatus } = get()
    const traceSteps =
      currentTraceSteps.length > 0
        ? currentTraceSteps
        : currentThinkingSteps.map(thinkingToTrace)

    set((state) => ({
      messages: state.messages.map((message) =>
        message.id === id
          ? {
              ...message,
              thinkingSteps: [...currentThinkingSteps],
              traceSteps,
              kgData: currentKgData ?? message.kgData,
              kgStatus: currentKgStatus,
              sourceItems: doneData?.source_items ?? message.sourceItems,
              retrievalStats: doneData?.retrieval_stats ?? message.retrievalStats,
              totalLatency: doneData?.total_latency,
              tokenCount: doneData?.token_count,
              firstTokenLatencyMs: doneData?.first_token_latency_ms,
              retrieveLatencyMs: doneData?.retrieve_latency_ms,
              answerCompleteLatencyMs: doneData?.answer_complete_latency_ms,
            }
          : message
      ),
      currentPhaseLabel: '',
      totalLatency: doneData?.total_latency ?? 0,
      tokenCount: doneData?.token_count ?? 0,
      firstTokenLatencyMs: doneData?.first_token_latency_ms ?? 0,
      retrieveLatencyMs: doneData?.retrieve_latency_ms ?? 0,
      answerCompleteLatencyMs: doneData?.answer_complete_latency_ms ?? 0,
    }))
  },

  setDraftMessage: (draftMessage) => set({ draftMessage }),
  setStreaming: (isStreaming) => set({ isStreaming }),
  setSessionId: (id) => set({ currentSessionId: id }),
  setCurrentPhase: (currentPhaseLabel) => set({ currentPhaseLabel }),

  clearMessages: () =>
    set({
      messages: [],
      currentSessionId: null,
      draftMessage: '',
      currentTraceSteps: [],
      currentThinkingSteps: [],
      currentKgData: null,
      currentKgStatus: 'idle',
      currentAnswer: '',
      currentPhaseLabel: '',
      totalLatency: 0,
      tokenCount: 0,
      firstTokenLatencyMs: 0,
      retrieveLatencyMs: 0,
      answerCompleteLatencyMs: 0,
    }),

  resetCurrentState: () =>
    set({
      currentTraceSteps: [],
      currentThinkingSteps: [],
      currentKgData: null,
      currentKgStatus: 'idle',
      currentAnswer: '',
      currentPhaseLabel: '',
      totalLatency: 0,
      tokenCount: 0,
      firstTokenLatencyMs: 0,
      retrieveLatencyMs: 0,
      answerCompleteLatencyMs: 0,
    }),
}))
