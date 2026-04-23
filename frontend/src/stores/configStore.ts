import { create } from 'zustand'
import type { AppConfig } from '../types'

interface ConfigStore {
  config: AppConfig | null
  selectedStrategy: string
  topK: number
  similarityThreshold: number
  debugMode: boolean
  chatDeferKg: boolean
  typingEffectEnabled: boolean
  setConfig: (config: AppConfig) => void
  setStrategy: (strategy: string) => void
  setTopK: (k: number) => void
  setThreshold: (t: number) => void
  toggleDebug: () => void
}

export const useConfigStore = create<ConfigStore>((set) => ({
  config: null,
  selectedStrategy: 'naive_rag',
  topK: 15,
  similarityThreshold: 0.82,
  debugMode: false,
  chatDeferKg: true,
  typingEffectEnabled: false,
  setConfig: (config) =>
    set({
      config,
      topK: config.default_top_k,
      similarityThreshold: config.default_similarity_threshold,
      chatDeferKg: config.chat_defer_kg ?? true,
      typingEffectEnabled: config.frontend_typing_effect ?? false,
    }),
  setStrategy: (strategy) => set({ selectedStrategy: strategy }),
  setTopK: (topK) => set({ topK }),
  setThreshold: (similarityThreshold) => set({ similarityThreshold }),
  toggleDebug: () => set((state) => ({ debugMode: !state.debugMode })),
}))
