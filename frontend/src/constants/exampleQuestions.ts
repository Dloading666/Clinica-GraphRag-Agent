export interface KnowledgeExampleQuestion {
  source: string
  text: string
}

export const KNOWLEDGE_EXAMPLE_QUESTIONS: KnowledgeExampleQuestion[] = [
  {
    source: '中医基础理论',
    text: '从中医基础理论看，气滞、气逆、气陷分别有哪些辨证要点？',
  },
  {
    source: '病理学',
    text: '病理学中，可逆性损伤、坏死和凋亡的核心区别是什么？',
  },
  {
    source: '药理学',
    text: '药理学里的首过效应会怎样影响口服药物的生物利用度？',
  },
  {
    source: '药理学',
    text: '抗菌药物的 MIC、最低杀菌浓度和耐药性在临床选药中应如何理解？',
  },
]

export const KNOWLEDGE_EXAMPLE_TEXTS = KNOWLEDGE_EXAMPLE_QUESTIONS.map(
  (item) => item.text
)
