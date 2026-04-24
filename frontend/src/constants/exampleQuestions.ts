export interface KnowledgeExampleQuestion {
  source: string
  text: string
}

export const KNOWLEDGE_EXAMPLE_QUESTIONS: KnowledgeExampleQuestion[] = [
  {
    source: '常见症状',
    text: '头痛应该怎么进行治疗？',
  },
  {
    source: '心血管问题',
    text: '心脏不舒服加上高血压，怎么治疗？',
  },
  {
    source: '用药问题',
    text: '口服药效果不稳定，和首过效应有关吗？',
  },
  {
    source: '皮肤症状',
    text: '全身一热就全身发痒，这是什么原因？',
  },
]

export const KNOWLEDGE_EXAMPLE_TEXTS = KNOWLEDGE_EXAMPLE_QUESTIONS.map(
  (item) => item.text
)
