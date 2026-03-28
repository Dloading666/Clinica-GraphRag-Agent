import { create } from 'zustand'
import { v4 as uuidv4 } from 'uuid'
import type { Message, TraceStep, KGData } from '../types'

interface ChatStore {
  messages: Message[]
  currentSessionId: string | null
  isStreaming: boolean
  draftMessage: string
  currentTraceSteps: TraceStep[]
  currentKgData: KGData | null
  currentAnswer: string
  totalLatency: number
  tokenCount: number

  addUserMessage: (content: string) => string
  startAssistantMessage: () => string
  appendToAssistantMessage: (id: string, token: string) => void
  addTraceStep: (step: TraceStep) => void
  setKgData: (data: KGData) => void
  finalizeAssistantMessage: (
    id: string,
    latency: number,
    tokenCount: number
  ) => void
  setDraftMessage: (message: string) => void
  setStreaming: (v: boolean) => void
  setSessionId: (id: string) => void
  clearMessages: () => void
  resetCurrentState: () => void
}

export const useChatStore = create<ChatStore>((set, get) => ({
  messages: [],
  currentSessionId: null,
  isStreaming: false,
  draftMessage: '',
  currentTraceSteps: [],
  currentKgData: null,
  currentAnswer: '',
  totalLatency: 0,
  tokenCount: 0,

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
        { id, role: 'assistant', content: '', createdAt: new Date() },
      ],
      currentAnswer: '',
    }))
    return id
  },

  appendToAssistantMessage: (id, token) => {
    set((state) => ({
      messages: state.messages.map((m) =>
        m.id === id ? { ...m, content: m.content + token } : m
      ),
      currentAnswer: state.currentAnswer + token,
    }))
  },

  addTraceStep: (step) => {
    set((state) => ({
      currentTraceSteps: [...state.currentTraceSteps, step],
    }))
  },

  setKgData: (data) => set({ currentKgData: data }),

  finalizeAssistantMessage: (id, latency, tokenCount) => {
    const { currentTraceSteps, currentKgData } = get()
    set((state) => ({
      messages: state.messages.map((m) =>
        m.id === id
          ? {
              ...m,
              traceSteps: currentTraceSteps,
              kgData: currentKgData ?? undefined,
              totalLatency: latency,
              tokenCount,
            }
          : m
      ),
      totalLatency: latency,
      tokenCount,
    }))
  },

  setDraftMessage: (draftMessage) => set({ draftMessage }),
  setStreaming: (isStreaming) => set({ isStreaming }),
  setSessionId: (id) => set({ currentSessionId: id }),
  clearMessages: () =>
    set({ messages: [], currentSessionId: null, draftMessage: '' }),
  resetCurrentState: () =>
    set({ currentTraceSteps: [], currentKgData: null, currentAnswer: '' }),
}))
