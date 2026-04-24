export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  agentType?: string
  thinkingSteps?: ThinkingStep[]
  traceSteps?: TraceStep[]
  kgData?: KGData
  kgStatus?: KGStatus
  sourceItems?: SourceItem[]
  retrievalStats?: RetrievalStats
  totalLatency?: number
  tokenCount?: number
  firstTokenLatencyMs?: number
  retrieveLatencyMs?: number
  answerCompleteLatencyMs?: number
  createdAt: Date
}

export interface TraceStep {
  node: string
  input?: string
  output?: string
  latency?: number
  icon?: string
}

export interface ThinkingStep {
  node: string
  label: string
  content: string
  done: boolean
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

export interface KGMeta {
  mode?: 'query' | 'source_items' | 'full'
  community_ids?: string[]
  source_entity_names?: string[]
  note?: string
}

export interface KGData {
  nodes: KGNode[]
  links: KGLink[]
  meta?: KGMeta
}

export type KGStatus = 'idle' | 'loading' | 'ready' | 'error'

export interface SourceItem {
  id: string
  source_type: 'chunk' | 'entity' | 'relation' | 'community' | string
  label: string
  title: string
  content: string
  document_name?: string
  entity_type?: string
}

export interface RetrievalStats {
  chunk_hits: number
  entity_hits: number
  community_hits: number
  relation_hits: number
  evidence_total: number
  used_query_expansion?: boolean
  knowledge_backed?: boolean
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
  chat_defer_kg?: boolean
  frontend_typing_effect?: boolean
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
  first_token_latency_ms?: number
  retrieve_latency_ms?: number
  answer_complete_latency_ms?: number
  retrieval_stats?: RetrievalStats
  source_items?: SourceItem[]
}

export interface KnowledgeBaseCounts {
  documents: number
  chunks: number
  entities: number
  relationships: number
  communities: number
}

export interface KnowledgeBaseStatus {
  job_id?: string | null
  status: 'idle' | 'running' | 'completed' | 'failed'
  stage: string
  message: string
  reason?: string | null
  path?: string | null
  started_at?: string | null
  finished_at?: string | null
  error?: string | null
  active?: boolean
  source_files: number
  counts: KnowledgeBaseCounts
  result?: {
    documents_processed?: number
    documents_failed?: number
    graph?: {
      status?: string
      chunks_processed?: number
      communities_created?: number
    }
  } | null
}
