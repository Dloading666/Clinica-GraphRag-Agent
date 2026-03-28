export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  agentType?: string
  traceSteps?: TraceStep[]
  kgData?: KGData
  totalLatency?: number
  tokenCount?: number
  createdAt: Date
}

export interface TraceStep {
  node: string
  input?: string
  output?: string
  latency?: number
  icon?: string
}

export interface KGNode {
  id: string
  label: string
  type: string
  size?: number
  properties?: Record<string, unknown>
}

export interface KGLink {
  source: string
  target: string
  label: string
  weight?: number
}

export interface KGData {
  nodes: KGNode[]
  links: KGLink[]
}

export interface SearchStrategy {
  id: string
  name: string
  description: string
}

export interface AppConfig {
  search_strategies: SearchStrategy[]
  example_questions: string[]
  default_top_k: number
  default_similarity_threshold: number
}

export interface Session {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export interface DoneData {
  total_latency?: number
  token_count?: number
}
