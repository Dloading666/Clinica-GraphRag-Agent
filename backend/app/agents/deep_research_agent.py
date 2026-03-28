"""Deep Research Agent - 迭代多跳深度研究"""
import asyncio
import re
import json
import time
from typing import Annotated, Any, AsyncGenerator, Dict, List, Optional, Sequence, TypedDict

from langchain.prompts import ChatPromptTemplate
from langchain.tools import Tool
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from app.agents.base import run_async
from app.config.database import AsyncSessionLocal
from app.config.prompts.clinical_prompts import (
    LOCAL_SEARCH_SYSTEM_PROMPT,
    response_type,
)
from app.models.llm_factory import get_embeddings, get_llm
from app.search.local_search import LocalSearch
from app.search.naive_search import NaiveSearch

# ──────────────────────────────────────────────
# 提示词
# ──────────────────────────────────────────────

_DECOMPOSE_PROMPT = """你是一名临床研究专家。请将以下复杂临床问题分解为 2-4 个具体的子问题，以便逐步检索和分析。

## 复杂临床问题
{question}

## 已有证据摘要（若有）
{evidence_summary}

## 任务
请输出 JSON 格式的子问题列表：
{{"sub_questions": ["子问题1", "子问题2", "子问题3"]}}

注意：
- 子问题应具体、可检索
- 子问题应覆盖原问题的不同方面
- 避免重复已有证据中已回答的内容

请直接输出 JSON："""

_EVALUATE_PROMPT = """你是一名临床研究质量评估专家。请评估当前收集的证据是否足以回答原始问题。

## 原始临床问题
{question}

## 已收集的证据
{evidence}

## 评估标准
- 证据是否覆盖了问题的核心方面？
- 是否有明显的信息缺口？
- 证据质量是否满足临床决策需要？

## 输出要求
返回 JSON：{{"sufficient": true/false, "missing_aspects": ["缺失方面1", "缺失方面2"], "confidence": 0.0-1.0}}

请直接输出 JSON："""

_SYNTHESIZE_PROMPT = """## 原始临床问题
{question}

## 多轮深度研究收集的证据
{evidence}

## 子问题与回答摘要
{sub_answers}

## 要求
请综合以上多轮研究证据，提供{response_type}。
- 按逻辑顺序组织回答
- 对各来源信息进行批判性整合
- 指出证据的强度和局限性
- 提供可操作的临床建议"""


# ──────────────────────────────────────────────
# 状态定义
# ──────────────────────────────────────────────

class ResearchState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    question: str                    # 原始问题
    sub_questions: List[str]         # 分解后的子问题
    current_iteration: int           # 当前迭代轮次
    max_iterations: int              # 最大迭代次数
    evidence: List[Dict]             # 收集到的证据列表
    sub_answers: List[Dict]          # 子问题及其回答
    evidence_sufficient: bool        # 证据是否充分
    final_answer: str                # 最终回答


class DeepResearchAgent:
    """
    深度研究 Agent：迭代式多跳检索

    流程：
    decompose → search_sub_questions → evaluate → (loop or synthesize)
    最多迭代 3 次。
    """

    def __init__(self):
        self.llm = get_llm()
        self.stream_llm = get_llm(streaming=True)
        self.embeddings = get_embeddings()
        self.naive_search = NaiveSearch()
        self.local_search = LocalSearch()
        self.memory = MemorySaver()
        self.execution_log: List[Dict] = []
        self._setup_chains()
        self._setup_graph()

    # ──────────────────────────────────────────────
    # Chain 初始化
    # ──────────────────────────────────────────────

    def _setup_chains(self) -> None:
        self._decompose_chain = (
            ChatPromptTemplate.from_messages([
                ("system", "你是一名擅长临床研究方法论的专家。"),
                ("human", _DECOMPOSE_PROMPT),
            ])
            | self.llm
            | StrOutputParser()
        )
        self._evaluate_chain = (
            ChatPromptTemplate.from_messages([
                ("system", "你是一名临床证据质量评估专家。"),
                ("human", _EVALUATE_PROMPT),
            ])
            | self.llm
            | StrOutputParser()
        )
        self._synthesize_chain = (
            ChatPromptTemplate.from_messages([
                ("system", LOCAL_SEARCH_SYSTEM_PROMPT),
                ("human", _SYNTHESIZE_PROMPT),
            ])
            | self.llm
            | StrOutputParser()
        )

    # ──────────────────────────────────────────────
    # 图谱构建
    # ──────────────────────────────────────────────

    def _setup_graph(self) -> None:
        workflow = StateGraph(ResearchState)
        workflow.add_node("decompose", self._decompose_node)
        workflow.add_node("search", self._search_node)
        workflow.add_node("evaluate", self._evaluate_node)
        workflow.add_node("synthesize", self._synthesize_node)

        workflow.add_edge(START, "decompose")
        workflow.add_edge("decompose", "search")
        workflow.add_edge("search", "evaluate")
        workflow.add_conditional_edges(
            "evaluate",
            self._should_continue,
            {"continue": "decompose", "synthesize": "synthesize"},
        )
        workflow.add_edge("synthesize", END)

        self.graph = workflow.compile(checkpointer=self.memory)

    # ──────────────────────────────────────────────
    # 节点实现
    # ──────────────────────────────────────────────

    def _decompose_node(self, state: ResearchState) -> Dict:
        """分解问题为子问题"""
        question = state["question"]
        iteration = state.get("current_iteration", 0)

        # 已有证据摘要
        evidence = state.get("evidence", [])
        evidence_summary = ""
        if evidence:
            summaries = [e.get("summary", "")[:200] for e in evidence[-3:]]
            evidence_summary = "\n".join(summaries)

        self._log("decompose", f"第{iteration+1}轮，原问题: {question[:100]}", "")

        try:
            raw = self._decompose_chain.invoke({
                "question": question,
                "evidence_summary": evidence_summary,
            })
            json_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                sub_questions = data.get("sub_questions", [])
            else:
                sub_questions = [question]
        except Exception as e:
            print(f"[DeepResearch] 问题分解失败: {e}")
            sub_questions = [question]

        self._log("decompose", "", f"子问题: {sub_questions}")
        return {"sub_questions": sub_questions[:4]}  # 最多 4 个子问题

    def _search_node(self, state: ResearchState) -> Dict:
        """对每个子问题执行检索"""
        sub_questions = state.get("sub_questions", [])
        existing_evidence = list(state.get("evidence", []))
        sub_answers = list(state.get("sub_answers", []))

        for sub_q in sub_questions:
            self._log("search", sub_q, "")
            try:
                # 使用线程池执行异步检索
                context = run_async(self._search_for_question(sub_q))
                if context and "未检索到" not in context:
                    existing_evidence.append({
                        "question": sub_q,
                        "context": context,
                        "summary": context[:300],
                        "iteration": state.get("current_iteration", 0),
                    })
                    sub_answers.append({"question": sub_q, "context": context[:500]})
                    self._log("search", sub_q, context[:200])
            except Exception as e:
                print(f"[DeepResearch] 子问题检索失败 ({sub_q}): {e}")

        return {
            "evidence": existing_evidence,
            "sub_answers": sub_answers,
        }

    def _evaluate_node(self, state: ResearchState) -> Dict:
        """评估证据是否充分"""
        question = state["question"]
        evidence = state.get("evidence", [])
        iteration = state.get("current_iteration", 0)

        # 超过最大迭代次数，强制结束
        if iteration >= state.get("max_iterations", 3) - 1:
            return {
                "evidence_sufficient": True,
                "current_iteration": iteration + 1,
            }

        if not evidence:
            return {
                "evidence_sufficient": False,
                "current_iteration": iteration + 1,
            }

        # 汇总证据
        evidence_text = "\n\n---\n\n".join(
            [f"[子问题: {e['question']}]\n{e.get('summary', '')}" for e in evidence[-6:]]
        )

        try:
            raw = self._evaluate_chain.invoke({
                "question": question,
                "evidence": evidence_text[:2000],
            })
            json_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                sufficient = data.get("sufficient", False)
                self._log("evaluate", f"迭代{iteration+1}", f"证据充分: {sufficient}")
                return {
                    "evidence_sufficient": sufficient,
                    "current_iteration": iteration + 1,
                }
        except Exception as e:
            print(f"[DeepResearch] 证据评估失败: {e}")

        return {
            "evidence_sufficient": False,
            "current_iteration": iteration + 1,
        }

    def _synthesize_node(self, state: ResearchState) -> Dict:
        """综合所有证据生成最终回答"""
        question = state["question"]
        evidence = state.get("evidence", [])
        sub_answers = state.get("sub_answers", [])

        # 合并所有证据
        evidence_text = "\n\n---\n\n".join(
            [f"[迭代{e['iteration']+1} | 子问题: {e['question']}]\n{e.get('context', '')[:600]}"
             for e in evidence]
        )

        sub_answers_text = "\n".join(
            [f"Q: {sa['question']}\nA: {sa.get('context', '')[:200]}"
             for sa in sub_answers]
        )

        self._log("synthesize", question[:100], "开始综合...")
        try:
            answer = self._synthesize_chain.invoke({
                "question": question,
                "evidence": evidence_text[:4000],
                "sub_answers": sub_answers_text[:2000],
                "response_type": response_type,
            })
            self._log("synthesize", "", answer[:200])
        except Exception as e:
            answer = f"综合分析时出错：{str(e)}\n\n已收集的证据摘要：\n{evidence_text[:1000]}"

        return {
            "final_answer": answer,
            "messages": [AIMessage(content=answer)],
        }

    def _should_continue(self, state: ResearchState) -> str:
        """决定是否继续迭代"""
        sufficient = state.get("evidence_sufficient", False)
        iteration = state.get("current_iteration", 0)
        max_iter = state.get("max_iterations", 3)

        if sufficient or iteration >= max_iter:
            return "synthesize"
        return "continue"

    # ──────────────────────────────────────────────
    # 检索辅助
    # ──────────────────────────────────────────────

    async def _search_for_question(self, question: str) -> str:
        """对单个子问题执行向量 + 图谱联合检索"""
        async with AsyncSessionLocal() as db:
            naive_task = self.naive_search.search(question, db, top_k=5)
            local_task = self.local_search.search(question, db)
            naive_results, local_result = await asyncio.gather(
                naive_task, local_task, return_exceptions=True
            )

            parts = []
            if isinstance(naive_results, list) and naive_results:
                parts.append(self.naive_search.format_context(naive_results[:3]))
            if isinstance(local_result, dict):
                ctx = self.local_search.format_context(local_result)
                if ctx and "未检索到" not in ctx:
                    parts.append(ctx)

            return "\n\n".join(parts) if parts else "未检索到相关资料"

    # ──────────────────────────────────────────────
    # 日志
    # ──────────────────────────────────────────────

    def _log(self, node: str, input_data: Any, output_data: Any) -> None:
        self.execution_log.append({
            "node": node,
            "timestamp": time.time(),
            "input": str(input_data)[:200],
            "output": str(output_data)[:500],
        })

    # ──────────────────────────────────────────────
    # 公共接口
    # ──────────────────────────────────────────────

    def ask(self, query: str, thread_id: str = "default") -> str:
        """同步执行深度研究，返回最终回答"""
        self.execution_log = []
        config = {"configurable": {"thread_id": thread_id}}
        initial_state: ResearchState = {
            "messages": [HumanMessage(content=query)],
            "question": query,
            "sub_questions": [],
            "current_iteration": 0,
            "max_iterations": 3,
            "evidence": [],
            "sub_answers": [],
            "evidence_sufficient": False,
            "final_answer": "",
        }
        try:
            for _ in self.graph.stream(initial_state, config=config):
                pass
            state = self.memory.get(config)
            return state["channel_values"].get("final_answer", "未能生成回答")
        except Exception as e:
            return f"深度研究过程中出错：{str(e)}"

    def ask_with_trace(self, query: str, thread_id: str = "default") -> Dict:
        """同步执行深度研究，返回回答 + 执行日志"""
        answer = self.ask(query, thread_id)
        return {"answer": answer, "execution_log": self.execution_log}

    async def ask_stream(
        self, query: str, thread_id: str = "default"
    ) -> AsyncGenerator[str, None]:
        """流式输出深度研究结果"""
        result = await asyncio.to_thread(self.ask_with_trace, query, thread_id)
        answer = result["answer"]
        sentences = re.split(r"([。！？.!?]\s*)", answer)
        buffer = ""
        for chunk in sentences:
            buffer += chunk
            if len(buffer) >= 50 or any(
                p in buffer for p in ["。", "！", "？", ".", "!", "?"]
            ):
                yield buffer
                buffer = ""
                await asyncio.sleep(0.02)
        if buffer:
            yield buffer
