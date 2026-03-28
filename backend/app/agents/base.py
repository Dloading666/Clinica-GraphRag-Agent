"""基础 Agent - 使用 LangGraph 状态机"""
import asyncio
import re
import time
from abc import ABC, abstractmethod
from typing import Annotated, Any, AsyncGenerator, Dict, List, Optional, Sequence, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from app.models.llm_factory import get_embeddings, get_llm


# ──────────────────────────────────────────────
# 异步辅助函数（在同步 Tool 函数中调用异步代码）
# ──────────────────────────────────────────────

def run_async(coro):
    """在同步上下文中安全地运行协程"""
    import concurrent.futures
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 当前已有事件循环运行（如 FastAPI），使用线程池避免嵌套
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


# ──────────────────────────────────────────────
# LangGraph 状态定义
# ──────────────────────────────────────────────

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]


# ──────────────────────────────────────────────
# 基类
# ──────────────────────────────────────────────

class BaseAgent(ABC):
    """使用 LangGraph 构建的临床问答 Agent 基类"""

    def __init__(self):
        self.llm = get_llm()
        self.stream_llm = get_llm(streaming=True)
        self.embeddings = get_embeddings()
        self.memory = MemorySaver()
        self.execution_log: List[Dict] = []
        self.tools = self._setup_tools()
        self._setup_graph()

    # ──────────────────────────────────────────────
    # 抽象接口
    # ──────────────────────────────────────────────

    @abstractmethod
    def _setup_tools(self) -> List:
        """配置并返回 Tool 列表"""
        ...

    @abstractmethod
    def _add_retrieval_edges(self, workflow: StateGraph) -> None:
        """在 workflow 中添加 retrieve → generate 的边"""
        ...

    @abstractmethod
    def _generate_node(self, state: AgentState) -> Dict:
        """Generate 节点：基于检索结果生成回答"""
        ...

    @abstractmethod
    def _extract_keywords(self, query: str) -> Dict[str, List[str]]:
        """从查询中提取关键词"""
        ...

    # ──────────────────────────────────────────────
    # 图谱构建
    # ──────────────────────────────────────────────

    def _setup_graph(self) -> None:
        """构建 LangGraph 状态机"""
        workflow = StateGraph(AgentState)
        workflow.add_node("agent", self._agent_node)
        workflow.add_node("retrieve", ToolNode(self.tools))
        workflow.add_node("generate", self._generate_node)
        workflow.add_edge(START, "agent")
        workflow.add_conditional_edges(
            "agent",
            tools_condition,
            {"tools": "retrieve", END: END},
        )
        self._add_retrieval_edges(workflow)
        workflow.add_edge("generate", END)
        self.graph = workflow.compile(checkpointer=self.memory)

    # ──────────────────────────────────────────────
    # 节点实现
    # ──────────────────────────────────────────────

    def _agent_node(self, state: AgentState) -> Dict:
        """Agent 节点：决定调用哪个 Tool"""
        messages = state["messages"]
        model = self.llm.bind_tools(self.tools)
        response = model.invoke(messages)
        self._log_execution(
            "agent",
            messages[-1].content if messages else "",
            response.content if hasattr(response, "content") else "",
        )
        return {"messages": [response]}

    # ──────────────────────────────────────────────
    # 执行日志
    # ──────────────────────────────────────────────

    def _log_execution(
        self,
        node_name: str,
        input_data: Any,
        output_data: Any,
    ) -> None:
        self.execution_log.append({
            "node": node_name,
            "timestamp": time.time(),
            "input": str(input_data)[:200] if input_data else "",
            "output": str(output_data)[:500] if output_data else "",
        })

    # ──────────────────────────────────────────────
    # 公共接口
    # ──────────────────────────────────────────────

    def ask(self, query: str, thread_id: str = "default") -> str:
        """同步执行查询，返回回答字符串"""
        self.execution_log = []
        config = {"configurable": {"thread_id": thread_id}}
        inputs = {"messages": [HumanMessage(content=query)]}
        try:
            for _ in self.graph.stream(inputs, config=config):
                pass
            state = self.memory.get(config)
            chat_history = state["channel_values"]["messages"]
            return chat_history[-1].content if chat_history else "未能生成回答"
        except Exception as e:
            return f"处理问题时出错：{str(e)}"

    def ask_with_trace(self, query: str, thread_id: str = "default") -> Dict:
        """同步执行查询，返回回答 + 执行日志"""
        self.execution_log = []
        config = {"configurable": {"thread_id": thread_id}}
        inputs = {"messages": [HumanMessage(content=query)]}
        try:
            for _ in self.graph.stream(inputs, config=config):
                pass
            state = self.memory.get(config)
            chat_history = state["channel_values"]["messages"]
            answer = chat_history[-1].content if chat_history else "未能生成回答"
            return {"answer": answer, "execution_log": self.execution_log}
        except Exception as e:
            error = f"处理问题时出错：{str(e)}"
            return {"answer": error, "execution_log": self.execution_log}

    async def ask_stream(
        self, query: str, thread_id: str = "default"
    ) -> AsyncGenerator[str, None]:
        """流式输出：按句子分块逐步返回"""
        result = await asyncio.to_thread(self.ask_with_trace, query, thread_id)
        answer = result["answer"]

        # 按句子边界分块流式输出
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
